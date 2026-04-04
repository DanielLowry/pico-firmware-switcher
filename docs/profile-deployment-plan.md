# Profile-Based Pico Deployment Plan

## Summary

This repo will move from a hard-coded Pico firmware switcher into a profile-driven deployment tool that can load client-provided MicroPython or C++ applications while keeping the switching path under switcher ownership.

The migration goal is:

- keep host-driven switching between MicroPython and C++ on one Pico
- load client functionality each time a profile is deployed
- make deployments profile-based rather than repo-hard-coded
- keep the switcher runtime in control of the pieces required for reliable switching
- keep testing lightweight and compatible with the existing GitHub CI

This plan is intentionally honest about scope: v1 is a managed contract, not a sandbox. Supported client code keeps switching reliable. Arbitrary client code can still bypass the managed path, and physical BOOTSEL remains the recovery path.

## Target End State

### Host-side behavior

- Root config file: `pico-switcher.toml`
- Config resolution order:
  - `--config <path>`
  - `PICO_SWITCHER_CONFIG`
  - upward search from the current working directory for `pico-switcher.toml`
- Relative paths resolve from the config file directory.
- Absolute paths are supported so client assets may live outside this repo.
- A built-in demo/default profile remains available during migration.

### Profile model

- One `default_profile`
- Named profiles under `[profiles.<name>]`
- Optional shared host defaults such as:
  - `port`
  - `mount_base`
  - `device_id`
  - base MicroPython UF2 path
- Python profile contract:
  - `source_dir`
  - `entry_module`
  - `entry_function` with default `main`
- C++ profile contract:
  - `source_dir`
  - `sources`
  - `output_uf2`

### Public command shape

- `detect`
- `flash`
- `to-py --profile <name>`
- `sync-py --profile <name>`
- `build-cpp --profile <name>`
- `to-cpp --profile <name>`

CLI flags continue to override config values.

### Detect behavior

Detect should distinguish runtime mode from active managed profile.

Structured detect result:

- `mode`: `py`, `cpp`, `bootsel`, or `unknown`
- `managed`: `true` or `false`
- `profile`: profile name when a managed deployment is active, otherwise `null`

Examples:

- unmanaged/default MicroPython: `mode=py`, `managed=false`, `profile=null`
- managed MicroPython profile: `mode=py`, `managed=true`, `profile=blink`
- unmanaged/default C++: `mode=cpp`, `managed=false`, `profile=null`
- managed C++ profile: `mode=cpp`, `managed=true`, `profile=demo`

The API should return the structured shape. The CLI should print a readable summary.

### MicroPython runtime contract

- The switcher owns reserved root files:
  - `boot.py`
  - `main.py`
  - generated metadata module, default name `_switcher_profile.py`
- Client files are mirrored only into `/app`
- `boot.py` remains switcher-owned for banner and startup control
- `main.py` remains switcher-owned and calls `app.<entry_module>.<entry_function>()`
- Switching from MicroPython uses the host command `mpremote ... bootloader`
- Stale file removal is limited to `/app`

### C++ runtime contract

The switcher runtime owns:

- `main()`
- USB stdio initialization
- boot and profile banner printing
- host command parsing
- BOOTSEL entry
- launching core1

The client provides exactly one supported entrypoint:

- `void client_app_main(void);`

Supported client behavior:

- runs on core1
- may use normal Pico SDK APIs on core1
- may write to stdout with `printf`
- may loop forever on core1

Unsupported client behavior:

- owning `main()`
- reading stdin
- initializing or tearing down stdio
- launching, resetting, or otherwise managing cores directly
- calling bootloader entry directly

The host-to-runtime BOOTSEL request should use a reserved text command rather than a raw one-byte trigger.

### Architecture direction

The host code should be split into three main layers:

- profile/config loading and validation
- Python/C++ packaging and build planning
- device detection, bootloader trigger, and flash workflow

The CLI should become a thin wrapper over these services. A small supported host-side Python API can be added after the core services are stable.

## MVP Phases

The MVP ends when the repo can reliably deploy managed MicroPython and managed C++ profiles from the host and report which managed profile is active.

### Phase 1: Profile Core and Config Loading

Goal: add profiles without changing the current switching behavior yet.

Changes:

- add `pico-switcher.toml` parsing and validation
- add profile data structures for Python and C++
- add `--profile` to profile-aware commands
- resolve all profile paths relative to the config file
- preserve the existing default/demo flow through a built-in demo profile
- keep current hard-coded switching behavior as the fallback implementation
- add initial documentation for the config shape, client contract, and current CLI-first integration path

Impact:

- no firmware behavior change yet
- no downstream app testing needed beyond config sanity checks

Testing:

- small unit tests for config discovery
- validation tests for unknown profile, missing path, external absolute path, and reserved filename collisions

### Phase 2: Managed MicroPython Deployment

Goal: make MicroPython profile deployment fully managed by the switcher.

Changes:

- add a packaging/sync layer for Python profiles
- introduce switcher-owned `boot.py`, `main.py`, and generated `_switcher_profile.py`
- mirror client `source_dir` into `/app`
- remove stale files only within `/app`
- replace `import bootloader_trigger` with host-side `mpremote ... bootloader`
- add `sync-py --profile`
- make `to-py --profile` flash if needed, reconnect, then install reserved files plus `/app`

Impact:

- managed Python profiles become usable by downstream apps
- MicroPython switching no longer depends on a client-visible trigger module

Downstream app checkpoint:

- first cut point for MicroPython-only client testing
- downstream apps can validate import path, entrypoint shape, and `/app` sync behavior

Testing:

- small unit tests for generated metadata content and sync planning
- mocked `mpremote` tests for bootloader trigger and file copy command generation
- one manual smoke test on hardware:
  - deploy a Python profile
  - verify `detect`
  - verify stale files under `/app` are removed
  - verify reserved root files remain switcher-owned

### Phase 3: Managed C++ Runtime and Build

Goal: make C++ profile deployment managed by the switcher runtime.

Changes:

- split the current C++ firmware into switcher runtime plus client app entrypoint
- introduce `client_app_main()`
- move the client to core1
- reserve stdin for the switcher command channel
- allow stdout for client logging
- replace the raw byte trigger with a reserved text BOOTSEL command
- build one UF2 per C++ profile from switcher runtime plus client sources
- add `build-cpp --profile`
- make `to-cpp --profile` optionally build, switch, and flash the selected UF2

Impact:

- both Python and C++ profiles are now managed under one profile model
- the C++ contract becomes explicit enough for downstream client code to target

Downstream app checkpoint:

- first cut point for apps that need both Python and C++
- downstream apps can validate the managed C++ entrypoint and switching behavior while the client loop is active

Testing:

- small unit tests for build planning and C++ profile validation
- one local build smoke test against the demo profile
- one manual hardware smoke test:
  - build and flash a managed C++ profile
  - confirm the runtime banner
  - confirm the BOOTSEL command still works while the client runs on core1

### Phase 4: Detect, Reporting, and MVP Stabilization

Goal: make managed deployments visible and stabilize the MVP behavior.

Changes:

- expand detect to return `mode`, `managed`, and `profile`
- for MicroPython, read generated metadata from the managed runtime
- for C++, print or expose generated profile identifiers in the runtime banner
- update CLI output to be readable while keeping structured detect available internally
- add profile context to logs where cheap and useful
- keep raw `flash` and the demo/default flow working during migration

Impact:

- deployment state is now inspectable rather than inferred only from `py`/`cpp`
- the MVP is stable enough for broader downstream app testing

Downstream app checkpoint:

- main MVP cut point for downstream app integration testing
- use this checkpoint to validate end-to-end switching, profile selection, and detect/reporting before adding post-MVP polish

Testing:

- small unit tests for detect result formatting
- one manual switch smoke test:
  - `to-py --profile X`
  - `detect`
  - `to-cpp --profile X`
  - `detect`
  - switch back again

## Target End State Phases

These phases are useful, but not required for the MVP cut point above.

### Phase 5: Thin Host API Over Core Services

Goal: expose a supported host-side Python API without creating a second architecture.

Changes:

- expose small service objects or helper functions for:
  - config loading
  - profile resolution
  - detect
  - `to_py`
  - `sync_py`
  - `build_cpp`
  - `to_cpp`
- keep the CLI as a thin wrapper over the same services
- add packaging metadata only when the API surface is stable enough to support

Impact:

- other host-side tools can import the switcher instead of shelling out to the CLI

Testing:

- a few unit tests that call the service layer directly
- no heavy API compatibility matrix yet

### Phase 6: Multi-Device Awareness and Logging Cleanup

Goal: make logs and config more useful when more than one Pico may exist.

Changes:

- add `device_id` or `device_name` as explicit host-side config
- store that identity alongside the resolved serial port in logs
- keep profile context in snapshots and switch events
- do not attempt hardware fingerprinting unless it becomes necessary

Impact:

- logs become easier to interpret when multiple boards are in use

Testing:

- unit tests for config and log field propagation

### Phase 7: Documentation and Release Polish

Goal: make the new model easy to adopt for future client apps.

Changes:

- update README and examples around profiles
- document the client contract and supported host import path clearly once the public API exists
- add one demo Python client profile and one demo C++ client profile
- document the managed C++ contract clearly
- document the MicroPython reserved-file model clearly
- remove or retire legacy helper scripts when they no longer add value

Impact:

- easier downstream adoption
- cleaner repo story after migration

Testing:

- documentation examples should be exercised manually
- keep CI light

## Lightweight Testing Strategy

The project should favor a small test suite plus manual hardware smoke tests.

### What should be covered automatically

- config discovery and path resolution
- profile validation
- detect result formatting
- command planning for `mpremote` and build steps
- small CLI-to-service wiring tests where cheap

These tests should stay mock-heavy and avoid real hardware access.

### What should stay manual

- actual serial detection against a Pico
- BOOTSEL transitions
- MicroPython file sync against a real device
- C++ runtime behavior on core0/core1
- real switching between Python and C++ on hardware

### CI expectations

Use the existing GitHub CI as the main automated gate.

Keep CI limited to:

- Python unit tests
- `compileall`
- basic import sanity

Do not add hardware-in-the-loop CI for this project.

Do not add large end-to-end mocked test pyramids unless a specific bug justifies them.

### Suggested manual smoke checklist per implementation phase

- Phase 2:
  - deploy one Python profile
  - verify entrypoint execution
  - verify `detect`
  - verify stale `/app` cleanup
- Phase 3:
  - build and flash one C++ profile
  - verify runtime banner
  - verify BOOTSEL command from the host
- Phase 4:
  - switch Python -> C++ -> Python with one profile
  - verify detect shows managed profile state at each step

## Assumptions and Defaults

- Host-driven switching is the only supported switching path in v1.
- Client code may still call low-level bootloader APIs directly, but that is outside the supported contract.
- MicroPython reserved root files stay under switcher ownership.
- C++ client code runs on core1 and may use normal Pico SDK APIs there.
- C++ client code may write stdout but may not read stdin.
- The C++ BOOTSEL request moves to a reserved text command.
- The host-side Python API is a post-MVP thin layer over the same core services used by the CLI.
