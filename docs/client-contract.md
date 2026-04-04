# Client Contract

## Executive Summary

- The current integration path is still CLI-first. Clients should use `pico.py` with `--profile`; a supported importable host API is planned later.
- Config lives in `pico-switcher.toml`. The switcher loads a default profile plus any named client profiles.
- Python profiles declare a source directory and entrypoint shape. They must not ship switcher-owned root files such as `boot.py` or `main.py`.
- C++ profiles declare a source directory, source list, and output UF2 path.
- Managed MicroPython deployment is now switcher-owned: the switcher syncs root runtime files plus the client app under `/app`.
- The later managed C++ runtime will keep switching under switcher ownership while client code plugs into that runtime.

## Current Status

Implemented now:

- config discovery and profile validation
- `to-py --profile ...` for switch-then-sync MicroPython deployment
- `sync-py --profile ...` for syncing managed MicroPython files without switching

Not implemented yet:

- supported importable host API
- managed C++ runtime and build contract

Examples:

```bash
python pico.py to-py --config pico-switcher.toml --profile demo
python pico.py sync-py --config pico-switcher.toml --profile demo
python pico.py to-cpp --config pico-switcher.toml --profile demo
```

A supported importable host API is planned, but it is not part of the current contract. Until that API exists, direct imports of internal modules should be treated as unstable implementation details.

## Config Contract

The config file is named `pico-switcher.toml`.

Resolution order:

- `--config <path>`
- `PICO_SWITCHER_CONFIG`
- upward search from the current working directory

Relative paths resolve from the config file directory. Absolute paths are also supported.

## Profile Shape

One `default_profile` is selected by default. Named profiles live under `[profiles.<name>]`.

Optional host defaults under `[host]`:

- `port`
- `mount_base`
- `device_id`
- `micropython_uf2`
- `cpp_uf2`

### Python profile

Python profiles use this shape:

```toml
[profiles.my_app.python]
source_dir = "path/to/python_app"
entry_module = "app_main"
entry_function = "main"
```

- `source_dir` is the client source root
- `entry_module` is the module the switcher will call in the managed runtime phase
- `entry_function` defaults to `main`
- top-level reserved files `boot.py`, `main.py`, and `_switcher_profile.py` are not allowed in `source_dir`

### C++ profile

C++ profiles use this shape:

```toml
[profiles.my_app.cpp]
source_dir = "path/to/cpp_app"
sources = ["client_app.cpp"]
output_uf2 = "build/my_app.uf2"
```

- `source_dir` is the client source root
- `sources` are resolved relative to `source_dir`
- `output_uf2` is resolved relative to the config file directory

## Target Managed Runtime Contract

Here, "managed runtime structure" means the switcher controls the startup files
and overall on-device layout, while the client code lives in a dedicated
application area.

### Managed MicroPython contract

- the switcher owns static root `boot.py`
- the switcher owns static root `main.py`
- the switcher owns generated metadata at root
- client files are mirrored under `/app`
- the switcher calls `app.<entry_module>.<entry_function>()`

In other words, the managed runtime structure on the Pico is:

- device root: switcher-owned startup/runtime files
- `/app`: client-owned code and assets

Status:

- implemented in the host-side sync flow
- detect still reports only `py` vs `cpp` for now; profile-aware detect is a later phase

### Managed C++ contract

The client provides:

```cpp
void client_app_main(void);
```

Supported client behavior:

- run on core1
- use Pico SDK APIs on core1
- write stdout with `printf`

Unsupported client behavior:

- own `main()`
- read stdin
- reinitialize stdio
- manage multicore directly
- call bootloader entry directly

This is a managed contract, not sandboxing. Unsupported client code can still bypass these rules, so physical BOOTSEL remains the recovery path.
