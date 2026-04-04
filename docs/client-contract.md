# Client Contract

## Executive Summary

- Phase 1 is CLI-first. Clients should use `pico.py` with `--profile`; a supported importable host API is planned later.
- Config lives in `pico-switcher.toml`. The switcher loads a default profile plus any named client profiles.
- Python profiles declare a source directory and entrypoint shape. They must not ship switcher-owned root files such as `boot.py` or `main.py`.
- C++ profiles declare a source directory, source list, and output UF2 path.
- The later managed runtime will keep switching under switcher ownership while client code plugs into that runtime.

## Phase 1 Status

Phase 1 adds config discovery, profile loading, and profile validation. It does not yet add managed Python sync or the managed C++ runtime.

Examples:

```bash
python pico.py to-py --config pico-switcher.toml --profile demo
python pico.py to-cpp --config pico-switcher.toml --profile demo
```

A supported importable host API is planned, but it is not part of the Phase 1 contract. Until that API exists, direct imports of internal modules should be treated as unstable implementation details.

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

### Managed MicroPython contract

- the switcher owns root `boot.py`
- the switcher owns root `main.py`
- the switcher owns generated metadata at root
- client files are mirrored under `/app`
- the switcher calls `app.<entry_module>.<entry_function>()`

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
