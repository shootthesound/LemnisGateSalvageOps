"""The game's list of playable maps (PlayableMaps on ConvergenceGameInstanceBP's defaults): read it, and write a copy
with extra maps, so maps made with the kit get their own entry (any name, any game mode) instead of replacing one.

Each entry is a PlayableMap struct of tagged properties: level path (string), display name and lore (text), game
mode (enum), thumbnail and flags. A new entry is a copy of an existing one with those values changed. Everything it
needs is inline or already in the asset's name table, so only the array and the export holding it grow.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mapgeo  # noqa: E402
import pakfile  # noqa: E402
from mapgeo import Reader  # noqa: E402

ASSET = 'LemnisGate/Content/Core/ConvergenceGameInstanceBP'
MODES = {'CTF': 'CaptureTheFlags', 'CAP': 'Capture', 'DM': 'Deathmatch', 'DST': 'Destroy', 'EVA': 'Evacuate',
         'ASN': 'Assassinate'}
UEXP_TAG = b'\xc1\x83\x2a\x9e'


def fstring(s):
    if s.isascii():
        b = s.encode('ascii') + b'\0'
        return struct.pack('<i', len(b)) + b
    b = s.encode('utf-16-le') + b'\0\0'
    return struct.pack('<i', -(len(b) // 2)) + b


def read_fstring(b, o):
    n = struct.unpack_from('<i', b, o)[0]
    o += 4
    if n >= 0:
        return b[o:o + n - 1].decode('ascii', 'replace'), o + n
    return b[o:o - n * 2 - 2].decode('utf-16-le'), o - n * 2


def text(namespace, key, source):
    """FText with a base history: unknown keys fall back to the source string."""
    return struct.pack('<i', 0) + b'\0' + fstring(namespace) + fstring(key) + fstring(source)


class MapList:
    def __init__(self, paks):
        self.header = pakfile.find(paks, ASSET + '.uasset')
        self.body = pakfile.find(paks, ASSET + '.uexp')
        self.pkg = pkg = mapgeo.Package(self.header, self.body)
        self.cdo = next(i for i, e in enumerate(pkg.exports, 1) if e['name'].startswith('Default__'))
        self.names = {n: i for i, n in enumerate(pkg.names)}
        self._find_array()

    def _tag_header(self, r):
        """Read one property tag; returns (name, type, size, value offset) or None at the end."""
        pkg = self.pkg
        start = r.o
        name = pkg.fname(r)
        if name == 'None':
            return None
        ptype = pkg.fname(r)
        size_at = r.o
        size, _ = r.i32(), r.i32()
        if ptype == 'StructProperty':
            pkg.fname(r); r.raw(16)
        elif ptype == 'BoolProperty':
            r.raw(1)
        elif ptype in ('ByteProperty', 'EnumProperty', 'ArrayProperty', 'SetProperty'):
            pkg.fname(r)
        elif ptype == 'MapProperty':
            pkg.fname(r); pkg.fname(r)
        if r.raw(1)[0]:
            r.raw(16)
        return name, ptype, size, r.o, size_at, start

    def _find_array(self):
        pkg = self.pkg
        e = pkg.exports[self.cdo - 1]
        r = Reader(pkg.b, e['offset'])
        while True:
            t = self._tag_header(r)
            if t is None:
                raise KeyError('PlayableMaps not found')
            name, ptype, size, value, size_at, _ = t
            if name == 'PlayableMaps':
                break
            r.o = value + size
        self.array_size_at, self.array_value, self.array_size = size_at, value, size
        r = Reader(pkg.b, value)
        self.count = r.i32()
        inner = self._tag_header(r)
        self.inner_size_at = inner[4]
        self.entries = []  # (start, end) of each struct's tagged properties
        for _ in range(self.count):
            start = r.o
            while self._skip(r):
                pass
            self.entries.append((start, r.o))

    def _skip(self, r):
        t = self._tag_header(r)
        if t is None:
            return False
        r.o = t[3] + t[2]
        return True

    def entry(self, k):
        """Entry k as {field: (type, value offset, size)} plus decoded basics."""
        start, end = self.entries[k]
        r = Reader(self.pkg.b, start)
        fields = {}
        while True:
            t = self._tag_header(r)
            if t is None:
                break
            name, ptype, size, value, size_at, tag_start = t
            fields[name] = (ptype, value, size, size_at, tag_start)
            r.o = value + size
        out = {'fields': fields}
        b = self.pkg.b
        if 'levelFullPath' in fields:
            out['level'] = read_fstring(b, fields['levelFullPath'][1])[0]
        if 'gameModeType' in fields:
            out['mode'] = self.pkg.fname(Reader(b, fields['gameModeType'][1])).split('::')[-1]
        if 'mapDisplayName' in fields:
            o = fields['mapDisplayName'][1] + 4
            history = b[o]
            o += 1
            if history == 0:  # base: namespace, key, source string
                _, o = read_fstring(b, o)
                _, o = read_fstring(b, o)
                out['name'] = read_fstring(b, o)[0]
            elif history == 255 and struct.unpack_from('<i', b, o)[0]:  # culture-invariant string
                out['name'] = read_fstring(b, o + 4)[0]
        if 'BuildFlags' in fields:
            out['flags'] = struct.unpack_from('<i', b, fields['BuildFlags'][1])[0]
        out['tutorial'] = 'tutorialMap' in fields and b[fields['tutorialMap'][4] + 24] == 1 if 'tutorialMap' in fields else False
        return out

    def find(self, level_name):
        """Index of the entry whose level is named level_name (e.g. CTF_Arches)."""
        for k in range(self.count):
            if self.entry(k).get('level', '').rsplit('.', 1)[-1].lower() == level_name.lower():
                return k
        raise KeyError(level_name)

    def set_mode(self, k, mode):
        """Change entry k's game mode in place (an enum name: same size)."""
        mode_name = 'EGameModeType::' + mode
        if mode_name not in self.names:
            raise KeyError('No game mode %s' % mode)
        value = self.entry(k)['fields']['gameModeType'][1]
        b = bytearray(self.pkg.b)
        struct.pack_into('<ii', b, value, self.names[mode_name], 0)
        self.pkg.b = bytes(b)

    def new_entry(self, template, level, name, mode, lore=None):
        """Bytes of a copy of entry `template` with another level path, display name, game mode (and lore)."""
        start, end = self.entries[template]
        b = self.pkg.b
        fields = self.entry(template)['fields']
        mode_name = 'EGameModeType::' + mode
        if mode_name not in self.names:
            raise KeyError('No game mode %s; known: %s' % (mode, ', '.join(MODES.values())))
        replace = {
            'levelFullPath': fstring(level),
            'mapDisplayName': text('Maps', 'SalvageOps_%s_Name' % name.replace(' ', '_'), name),
            'gameModeType': struct.pack('<ii', self.names[mode_name], 0),
        }
        if lore is not None:
            replace['mapLore'] = text('Maps', 'SalvageOps_%s_Lore' % name.replace(' ', '_'), lore)
        out = bytearray()
        pos = start
        for field, (ptype, value, size, size_at, tag_start) in sorted(fields.items(), key=lambda kv: kv[1][1]):
            if field not in replace:
                continue
            new = replace[field]
            out += b[pos:size_at] + struct.pack('<i', len(new)) + b[size_at + 4:value] + new
            pos = value + size
        out += b[pos:end]
        return bytes(out)

    def write(self, extra):
        """(header, body) of the asset with `extra` entries (bytes from new_entry) appended to PlayableMaps."""
        if not extra:
            return self.header, self.body
        add = b''.join(extra)
        grow = len(add)
        pkg = self.pkg
        b = bytearray(pkg.b)
        last_end = self.entries[-1][1]
        b[last_end:last_end] = add
        struct.pack_into('<i', b, self.array_size_at, self.array_size + grow)
        struct.pack_into('<i', b, self.inner_size_at, struct.unpack_from('<i', b, self.inner_size_at)[0] + grow)
        struct.pack_into('<i', b, self.array_value, self.count + len(extra))
        header, body = bytes(b[:len(self.header)]), bytes(b[len(self.header):])
        return self._fix_header(header, grow, last_end), body

    def _fix_header(self, header, grow, at):
        """Grow the export holding `at` and shift everything serialized after it."""
        d = bytearray(header)
        o = 20
        o += 4 + 20 * struct.unpack_from('<i', d, o)[0]
        o += 4  # TotalHeaderSize
        _, o = pakfile._fstring(d, o)
        o += 4 + 8 + 8
        ec, eo = struct.unpack_from('<ii', d, o)
        o += 16  # exports, imports
        o += 4 + 8 + 4 + 4  # depends, soft refs, searchable names, thumbnails
        o += 16  # guid
        o += 4 + 8 * struct.unpack_from('<i', d, o)[0]  # generations
        for _ in range(2):  # saved-by and compatible-with engine versions
            o += 10
            _, o = pakfile._fstring(d, o)
        o += 4  # compression flags
        o += 4 + 0 * struct.unpack_from('<i', d, o)[0]  # compressed chunks (none in cooked packages)
        o += 4  # package source
        n = struct.unpack_from('<i', d, o)[0]
        o += 4
        for _ in range(n):
            _, o = pakfile._fstring(d, o)
        o += 4  # asset registry data offset
        bulk = struct.unpack_from('<q', d, o)[0]
        if bulk >= at:
            struct.pack_into('<q', d, o, bulk + grow)
        for k in range(ec):
            p = eo + k * 104
            size, offset = struct.unpack_from('<qq', d, p + 28)
            if offset <= at < offset + size:
                struct.pack_into('<q', d, p + 28, size + grow)
            elif offset > at:
                struct.pack_into('<q', d, p + 36, offset + grow)
        return bytes(d)


if __name__ == '__main__':
    import build
    ml = MapList(pakfile.game_paks(build.find_game()))
    for k in range(ml.count):
        e = ml.entry(k)
        print('%2d %-22s %-16s flags=%-3s tut=%d %s' % (k, e.get('name'), e.get('mode'), e.get('flags'), e['tutorial'],
                                                     e.get('level')))
