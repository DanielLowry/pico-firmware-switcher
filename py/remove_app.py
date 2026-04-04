"""MicroPython helper used by the host sync flow to clear the managed `/app` tree.

This file is stored in the repo so the device-side removal logic is visible and
maintainable like the other MicroPython-side files. The host reads its contents
and executes it over `mpremote` before copying the next client tree into `/app`.
"""

import os


def _rm_tree(path):
    try:
        os.stat(path)
    except OSError:
        return
    try:
        names = os.listdir(path)
    except OSError:
        os.remove(path)
        return
    for name in names:
        child = path + "/" + name
        _rm_tree(child)
    os.rmdir(path)


_rm_tree("/app")
