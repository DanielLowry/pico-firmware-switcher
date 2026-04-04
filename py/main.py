"""Static switcher-owned `main.py` template for managed MicroPython.

This file stays fixed in the repo and is copied to the Pico device root by the
managed MicroPython sync flow. It imports the switcher-owned metadata module,
adds `/app` to `sys.path`, then imports and invokes the configured client
entrypoint from the client-owned application area.
"""

import sys

import _switcher_profile

if _switcher_profile.APP_ROOT not in sys.path:
    sys.path.insert(0, _switcher_profile.APP_ROOT)

_module = __import__(
    _switcher_profile.ENTRY_MODULE,
    None,
    None,
    (_switcher_profile.ENTRY_FUNCTION,),
)
_entry = getattr(_module, _switcher_profile.ENTRY_FUNCTION)
_entry()
