"""Create editor copies of the game's static meshes from files mapkit/meshes.py wrote (run by kit.py setup).

They replace the cube placeholders, so the editor shows real shapes. The cooked map still references the game's own
meshes: only map files are packed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_common import LIB, log, run, JOB  # noqa: E402


def main():
    made, failed = [], []
    for i, (path, file) in enumerate(JOB['meshes']):
        if LIB.import_mesh(path, file):
            made.append(path)
        else:
            failed.append(path)
            log('  could not import %s' % path)
        if i % 100 == 0:
            log('%d/%d meshes' % (i, len(JOB['meshes'])))
    return {'made': made, 'failed': failed}


run(main)
