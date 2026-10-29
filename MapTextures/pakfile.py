"""Read Lemnis Gate's .pak files (UE 4.26, pak version 11, uncompressed, unencrypted) and patch map name tables."""
import os
import struct

PAK_FOOTER = 221  # v11: guid(16) encrypted(1) magic(4) version(4) offset(8) size(8) hash(20) 5 x 32-byte compression names
ENTRY_HEADER = 53  # serialized FPakEntry in front of each file's data when uncompressed


def _fstring(b, o):
    n = struct.unpack_from('<i', b, o)[0]
    o += 4
    if n == 0:
        return '', o
    if n < 0:
        return b[o:o - 2 * n].decode('utf-16-le')[:-1], o - 2 * n
    return b[o:o + n - 1].decode('utf-8', 'replace'), o + n


class Pak:
    def __init__(self, path):
        self.path = path
        self.f = open(path, 'rb')
        self.f.seek(0, 2)
        self.f.seek(self.f.tell() - PAK_FOOTER)
        footer = self.f.read(PAK_FOOTER)
        magic, version = struct.unpack_from('<II', footer, 17)
        if magic != 0x5A6F12E1 or version != 11:
            raise ValueError('%s: unsupported pak (version %d)' % (path, version))
        index_offset, index_size = struct.unpack_from('<qq', footer, 25)
        self.f.seek(index_offset)
        b = self.f.read(index_size)
        self.mount, o = _fstring(b, 0)
        o += 12  # entry count, path hash seed
        has_path_hash_index = struct.unpack_from('<I', b, o)[0]
        o += 4
        if has_path_hash_index:
            o += 36  # offset, size, hash
        o += 4  # bHasFullDirectoryIndex
        dir_offset, dir_size = struct.unpack_from('<qq', b, o)
        o += 36
        n = struct.unpack_from('<i', b, o)[0]
        self.encoded = b[o + 4:o + 4 + n]
        self.f.seek(dir_offset)
        d = self.f.read(dir_size)
        self.files = {}
        o = 4
        for _ in range(struct.unpack_from('<i', d, 0)[0]):
            dirname, o = _fstring(d, o)
            count = struct.unpack_from('<i', d, o)[0]
            o += 4
            for _ in range(count):
                name, o = _fstring(d, o)
                self.files[(self.mount + dirname + name).replace('../../../', '')] = struct.unpack_from('<i', d, o)[0]
                o += 4

    def read(self, name):
        o = self.files[name]
        flags = struct.unpack_from('<I', self.encoded, o)[0]
        o += 4
        if flags & (1 << 31):
            offset = struct.unpack_from('<I', self.encoded, o)[0]
            o += 4
        else:
            offset = struct.unpack_from('<Q', self.encoded, o)[0]
            o += 8
        size = struct.unpack_from('<I' if flags & (1 << 30) else '<Q', self.encoded, o)[0]
        if (flags >> 23) & 0x3f or flags & (1 << 22):
            raise ValueError('%s is compressed or encrypted' % name)
        self.f.seek(offset + ENTRY_HEADER)
        return self.f.read(size)


def game_paks(game):
    folder = os.path.join(game, 'LemnisGate', 'Content', 'Paks')
    return [Pak(os.path.join(folder, f)) for f in sorted(os.listdir(folder))
            if f.startswith('pakchunk') and f.endswith('.pak')]


def find(paks, name):
    for p in paks:
        if name in p.files:
            return p.read(name)
    raise KeyError(name)


# ---------------------------------------------------------------- name hashes (FCrc, UE 4.26)

def _crc_table(poly, reflect):
    table = []
    for i in range(256):
        if reflect:
            c = i
            for _ in range(8):
                c = (c >> 1) ^ poly if c & 1 else c >> 1
        else:
            c = i << 24
            for _ in range(8):
                c = ((c << 1) ^ poly) if c & 0x80000000 else c << 1
            c &= 0xFFFFFFFF
        table.append(c)
    return table


_DEPRECATED = _crc_table(0x04C11DB7, False)
_CRC32 = _crc_table(0xEDB88320, True)


def strihash_deprecated(s):
    """FCrc::Strihash_DEPRECATED on the upper-cased name (FNameEntry non-case-preserving hash)."""
    h = 0
    for ch in s:
        c = ord(ch.upper())
        for byte in (c & 0xFF, (c >> 8) & 0xFF) if c > 0xFF else (c,):
            h = ((h >> 8) & 0x00FFFFFF) ^ _DEPRECATED[(h ^ byte) & 0xFF]
    return h


def strcrc32(s):
    """FCrc::StrCrc32 (case-preserving hash): each character is fed as 4 bytes."""
    crc = 0xFFFFFFFF
    for ch in s:
        c = ord(ch)
        for _ in range(4):
            crc = (crc >> 8) ^ _CRC32[(crc ^ c) & 0xFF]
            c >>= 8
    return ~crc & 0xFFFFFFFF


# ---------------------------------------------------------------- package name table

def name_table(data):
    """Return (entries, name_offset) where entries are (offset, string, stored_hashes) from a .uasset/.umap header."""
    o = 4
    legacy = struct.unpack_from('<i', data, o)[0]
    o += 4
    if legacy != -4:
        o += 4
    o += 8
    o += 4 + 20 * struct.unpack_from('<i', data, o)[0]  # custom versions
    o += 4
    _, o = _fstring(data, o)
    o += 4  # package flags
    count, offset = struct.unpack_from('<ii', data, o)
    entries, p = [], offset
    for _ in range(count):
        start = p
        s, p = _fstring(data, p)
        entries.append((start, s, struct.unpack_from('<HH', data, p)))
        p += 4
    return entries


def replace_names(data, mapping):
    """Return `data` with whole name-table strings replaced; new strings must be the same length and ASCII."""
    out = bytearray(data)
    done = set()
    for start, s, _ in name_table(data):
        if s in mapping:
            new = mapping[s]
            if len(new) != len(s) or not new.isascii():
                raise ValueError('Replacement must be ASCII and the same length: %r -> %r' % (s, new))
            n = struct.unpack_from('<i', out, start)[0]
            if n <= 0:
                raise ValueError('Unexpected wide name %r' % s)
            out[start + 4:start + 4 + len(new)] = new.encode('ascii')
            struct.pack_into('<HH', out, start + 4 + n, strihash_deprecated(new) & 0xFFFF, strcrc32(new) & 0xFFFF)
            done.add(s)
    missing = set(mapping) - done
    if missing:
        raise KeyError('Not in name table: %s' % sorted(missing))
    return bytes(out)
