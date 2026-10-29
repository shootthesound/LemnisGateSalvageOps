"""Check a cooked map against the game: every asset it references must exist in the game's paks (or ours) with
the same name and class, and every native class in the game's executable. A miss means the map would load with
something missing in-game, usually a stand-in that does not match the game's asset."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mapgeo  # noqa: E402
import pakfile  # noqa: E402


class CookedFolder:
    """Cooked files under Content/<sub> of a cook output, readable like a pak (the kit's own assets)."""

    def __init__(self, cooked, sub):
        self.files = {}
        base = os.path.join(cooked, 'LemnisGate', 'Content')
        for root, _, names in os.walk(os.path.join(base, sub)):
            for n in names:
                full = os.path.join(root, n)
                self.files['LemnisGate/Content/' + os.path.relpath(full, base).replace(os.sep, '/')] = full

    def read(self, name):
        return open(self.files[name], 'rb').read()


class Checker:
    def __init__(self, paks, exe_path):
        self.paks = paks
        self.exe = open(exe_path, 'rb').read()
        self.packages = {}

    def exports(self, path):
        if path not in self.packages:
            asset = 'LemnisGate/Content/' + path[len('/Game/'):]
            self.packages[path] = None
            for ext in ('.uasset', '.umap'):
                try:
                    pkg = mapgeo.Package(pakfile.find(self.paks, asset + ext), pakfile.find(self.paks, asset + '.uexp'))
                except KeyError:
                    continue
                self.packages[path] = {(e['name'], e['class']) for e in pkg.exports}
                break
        return self.packages[path]

    def check(self, umap, uexp):
        pkg = mapgeo.Package(open(umap, 'rb').read(), open(uexp, 'rb').read())
        problems = []
        for im in pkg.imports:
            if im['class'] == 'Package':
                continue
            chain, o = [im['name']], im['outer']
            while o < 0:
                chain.append(pkg.imports[-o - 1]['name'])
                o = pkg.imports[-o - 1]['outer']
            package = chain[-1]
            if package.startswith('/Game/'):
                found = self.exports(package)
                if found is None:
                    problems.append('%s is not in the game' % package)
                elif (im['name'], im['class']) not in found:
                    problems.append('%s has no %s %s' % (package, im['class'], im['name']))
            elif package == '/Script/LemnisGate' and im['class'] in ('Class', 'Enum', 'ScriptStruct'):
                if im['name'].encode('utf-16-le') not in self.exe:
                    problems.append('the game has no native %s %s' % (im['class'], im['name']))
        return sorted(set(problems))
