This project aims to make it possible to switch Raspberry Pi Pico firmware remotely (e.g., over SSH) without pressing the BOOTSEL button. Typical UF2s are a MicroPython firmware image or a C/C++ program. Doing this remotely requires a way to drop into the UF2 bootloader from whatever firmware is currently running.

Current state (early prototype)
- MicroPython side: `bootloader_trigger.py` (calls `machine.bootloader()`) and `boot.py` (prints `FW:PY` on boot; copy this onto the board).
- C++ side: `bootloader_trigger` firmware prints `FW:CPP` at startup, then waits for the key sequence `r` then `u` and calls `reset_usb_boot(...)` to enter UF2 mode.
- Python CLI is now available as `pico.py` (`detect`, `to-py`, `to-cpp`, `flash`, `install-py-files`).
- Existing shell scripts still work, but they are now legacy helpers.

Plan (target workflow)
- Add a small Python CLI (`pico.py`) with `to-py` and `to-cpp` commands.
- Detect current firmware by reading the boot banner (`FW:PY` / `FW:CPP`) over serial.
- Trigger UF2 mode remotely:
  - MicroPython: run `bootloader_trigger.py` via `mpremote`.
  - C++: send a single `'b'` over serial to drop into UF2 mode.
- Wait for the `RPI-RP2` mount and copy the requested UF2.
- Optional flags:
  - `--sync` to copy MicroPython project files after switching to MicroPython.
  - `--build` to rebuild the C++ UF2 before flashing.

Repo layout (relevant bits)
- `uf2s/` — stored UF2 images (MicroPython and the built C++ bootloader).
- `pico.py` — single host CLI for switching/detecting/flashing.
- SQLite audit log — defaults to `.pico-switcher/events.sqlite3` in the repo root.
- `requirements.txt` — Python dependencies (`pyserial`, `mpremote`, `peewee`, and `tomli` on Python < 3.11).
- `py/bootloader_trigger.py` — MicroPython bootloader trigger.
- `cpp/` — C++ sources and build outputs (including `build/bootloader_trigger.uf2`).
- `shell/` — helper scripts for flashing and triggering.

Prerequisites
- Linux only (scripts assume `/dev/ttyACM*` and `lsblk`).
- Python 3.10+ and `uv` (recommended) or `pip`.
- `mpremote` installed and able to talk to your Pico (for the MicroPython trigger).
- Pico SDK installed and `PICO_SDK_PATH` exported (required for the C++ build; see below).
- ARM GCC toolchain (`arm-none-eabi-gcc`) available on `PATH` or set via `PICO_TOOLCHAIN_PATH`.
- A build tool installed (`make` or `ninja`).
- Pico shows up as `RPI-RP2` when in BOOTSEL mode.
- A serial port path for the Pico (commonly `/dev/ttyACM0` on Linux).

Pico SDK setup (required for the C++ build)
1) Get the SDK (with submodules). Command: `git clone --recursive https://github.com/raspberrypi/pico-sdk`
2) Export `PICO_SDK_PATH` to the SDK root (one-off): `export PICO_SDK_PATH=path_to_sdk`

Toolchain + build tools (for Linux)
- Debian/Ubuntu: `sudo apt update` then `sudo apt install -y gcc-arm-none-eabi cmake make`
- If you prefer Ninja: `sudo apt install -y ninja-build`, then use `cmake -G Ninja ..` and `ninja bootloader_trigger`

Python environment setup (uv)
```
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```
- Recommended command form: `uv run python pico.py ...`

Identify the current firmware
- Make sure `py/boot.py` is on the MicroPython filesystem so it prints `FW:PY` on boot.
- The C++ bootloader trigger prints `FW:CPP` on boot after you flash the rebuilt UF2.
- Host helper: `./detect_firmware.py /dev/ttyACM0` (default port) reads the banner and reports the mode; requires `pyserial`.
- CLI: `python pico.py detect --port /dev/ttyACM0` (uses boot banner, then falls back to an `mpremote` probe for MicroPython)

Build the C++ UF2
- Requirements: Pico SDK set up (`PICO_SDK_PATH` exported), CMake + Make/Ninja.
- From the repo root:
  ```
  mkdir -p cpp/build
  cd cpp/build
  cmake ..
  make bootloader_trigger
  ```
  The UF2 will be at `cpp/build/bootloader_trigger.uf2` (copy or link it into `uf2s/` if you want it alongside the others).

Common CMake errors and fixes
- `Compiler 'arm-none-eabi-gcc' not found`. Fix: install `gcc-arm-none-eabi` or set `PICO_TOOLCHAIN_PATH` to the directory that contains `bin/arm-none-eabi-gcc`. Example: `export PICO_TOOLCHAIN_PATH=/opt/gcc-arm-none-eabi-*/bin`
- `CMake was unable to find a build program corresponding to "Unix Makefiles"`. Fix: install `make` or switch to Ninja (`sudo apt install ninja-build`, then re-run `cmake -G Ninja ..`).

Usage (single CLI, recommended)
1) Switch to MicroPython
   - `python pico.py to-py --port /dev/ttyACM0 --verbose`
   - This detects mode, triggers BOOTSEL, mounts `RPI-RP2` if needed, flashes the MicroPython UF2, then installs `py/boot.py` + `py/bootloader_trigger.py`.
   - If already in MicroPython mode, UF2 flashing is skipped by default (use `--force-flash` to override).

2) Switch to C++
   - `python pico.py to-cpp --port /dev/ttyACM0 --verbose`
   - This detects mode, triggers BOOTSEL, mounts `RPI-RP2` if needed, and flashes the C++ UF2.
   - If already in C++ mode, UF2 flashing is skipped by default (use `--force-flash` to override).

3) Flash any UF2 while already in BOOTSEL
   - `python pico.py flash /path/to/file.uf2 --verbose`

4) Only install MicroPython helper files
   - `python pico.py install-py-files --port /dev/ttyACM0`

5) Record a state snapshot manually
   - `python pico.py log-state --port /dev/ttyACM0 --source manual`
   - This appends the current detected state (`py`, `cpp`, `bootsel`, or `unknown`) to the SQLite log.

6) View recent history
   - `python pico.py history --kind all --limit 20`
   - Prints recent switch/flash/helper events plus recorded state snapshots from the SQLite log.

7) Install a 1-minute state snapshot timer
   - `python pico.py install-state-timer --port /dev/ttyACM0 --enable`
   - This writes `systemd --user` units that call `pico.py log-state` every minute and enables the timer.

8) Create and send a one-off database backup
   - First create `.pico-switcher/backup.toml` in the repo root:
     ```
     [local]
     staging_dir = "backups"
     compress = true

     [remote]
     host = "backup-box.local"
     user = "backuponly"
     path = "/srv/pico-switcher/backups"
     ssh_key_path = "pico_switcher_backup"
     port = 22
     connect_timeout_seconds = 10
     ```
   - Then run: `python pico.py backup-db`
   - This creates a consistent snapshot of the SQLite log database, transfers it to the configured remote host with `rsync` over SSH, and deletes the local staged copy after a successful transfer.

9) If autodetect misses your mode
   - Override explicitly: `--mode py`, `--mode cpp`, or `--mode bootsel`.

Logging and state history
- Every normal CLI action now records structured events in SQLite, including mode detection, BOOTSEL triggers, UF2 flashes, helper installs, switch skips, and command failures.
- Default database path: `.pico-switcher/events.sqlite3` in the repo root
- Override the database location with `--db-path /path/to/pico-events.sqlite3` or `PICO_SWITCHER_DB=/path/to/pico-events.sqlite3`.
- `log-state` is intentionally tolerant: if the Pico is unplugged or detection fails, it still records a snapshot row with mode `unknown`.
- The generated `systemd --user` service stores absolute paths to the current repo and Python interpreter. If you move the repo or recreate the venv/interpreter, rerun `install-state-timer`.

Backup configuration
- `backup-db` reads `.pico-switcher/backup.toml` in the repo root by default. Override it with `--config /path/to/backup.toml`.
- The backup config currently controls the local staging directory, whether staged files are gzip-compressed, and the remote SSH/rsync destination.
- `backup-db` still uses the normal `--db-path` flag to choose which SQLite file to back up.
- Relative `staging_dir` and `ssh_key_path` values are resolved relative to the config file location, so repo-local paths work cleanly.
- Remote backups require key-based SSH access. The configured `ssh_key_path` must point to a local private key file that already works for the remote backup account.
- If the remote transfer fails, the staged backup file is left in the local staging directory for later manual inspection or retry.
- `.pico-switcher/` is ignored by Git so repo-local config, staged backups, and repo-local SSH key files are not committed accidentally.
- The one exception is installed `systemd` unit files: if you use `install-state-timer`, the generated units still need to be written somewhere `systemd` can actually load them from.

Usage (manual workflow, legacy scripts)
1) Flash MicroPython UF2 (from BOOTSEL mode)
   - Put the Pico in BOOTSEL mode (button + power) once.
   - Run: `./shell/load_micropython_uf2.sh`
   - This copies `uf2s/Pico-MicroPython-20250415-v1.25.0.uf2` to the `RPI-RP2` volume.

2) Install MicroPython helper files (once per MicroPython flash)
   - Run: `./shell/install_micropython_files.sh /dev/ttyACM0`
   - This copies `py/boot.py` and `py/bootloader_trigger.py` onto the Pico filesystem.

3) Drop to UF2 bootloader from MicroPython (remote)
   - Ensure the Pico is running MicroPython and expose the serial port (e.g., `/dev/ttyACM0`).
   - Run: `./shell/trigger_py_boot.sh /dev/ttyACM0 true`
   - This uses `mpremote` to execute `bootloader_trigger.py`, which reboots the board into UF2 mode (the `RPI-RP2` drive should appear).

4) Flash the C++ bootloader trigger UF2
   - With the board now in UF2 mode, run: `./shell/load_cpp_bootloader_uf2.sh`
   - This copies `uf2s/bootloader_trigger.uf2` (built from `cpp/bootloader_trigger.cpp`) to the Pico.

5) Use the C++ bootloader trigger
   - Connect to the Pico over serial (e.g., `screen /dev/ttyACM0 115200`).
   - Press `r` then `u` to reboot into UF2 mode. From there, you can copy another UF2 to `RPI-RP2` (e.g., via `./shell/load_uf2.sh <filename.uf2>`).

Next steps (priority order)
- Change the C++ trigger to a single `'b'` command (still print `FW:CPP` on boot).
- Add `--sync` (MicroPython project copy) and `--build` (C++ rebuild) flags.
- Add a minimal config file (serial port, mount point, UF2 paths) to avoid hardcoding.

Notes
- MicroPython itself ships as a UF2 (already in `uf2s/`); your Python files (`boot.py`, `bootloader_trigger.py`, later your app) are copied directly onto the MicroPython filesystem, not built into a UF2.
