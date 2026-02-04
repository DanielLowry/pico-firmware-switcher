This project aims to make it possible to switch Raspberry Pi Pico firmware remotely (e.g., over SSH) without pressing the BOOTSEL button. Typical UF2s are a MicroPython firmware image or a C/C++ program. Doing this remotely requires a way to drop into the UF2 bootloader from whatever firmware is currently running.

Current state (early prototype)
- MicroPython side: `bootloader_trigger.py` (calls `machine.bootloader()`) and `boot.py` (prints `FW:PY` on boot; copy this onto the board).
- C++ side: `bootloader_trigger` firmware prints `FW:CPP` at startup, then waits for the key sequence `r` then `u` and calls `reset_usb_boot(...)` to enter UF2 mode.
- Python CLI is now available as `pico_switcher.py` (`detect`, `to-py`, `to-cpp`, `flash`, `install-py-files`).
- Existing shell scripts still work, but they are now legacy helpers.

Plan (target workflow)
- Add a small Python CLI (`pico_switcher.py`) with `to-py` and `to-cpp` commands.
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
- `requirements.txt` — Python dependencies (`pyserial`, `mpremote`).
- `py/bootloader_trigger.py` — MicroPython bootloader trigger.
- `cpp/` — C++ sources and build outputs (including `build/bootloader_trigger.uf2`).
- `shell/` — helper scripts for flashing and triggering.

Prerequisites
- Linux only (scripts assume `/dev/ttyACM*` and `lsblk`).
- Python 3.10+ and `uv` (recommended) or `pip`.
- `mpremote` installed and able to talk to your Pico (for the MicroPython trigger).
- Pico shows up as `RPI-RP2` when in BOOTSEL mode.
- A serial port path for the Pico (commonly `/dev/ttyACM0` on Linux).

Python environment setup (uv)
```
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

Identify the current firmware
- Make sure `py/boot.py` is on the MicroPython filesystem so it prints `FW:PY` on boot.
- The C++ bootloader trigger prints `FW:CPP` on boot after you flash the rebuilt UF2.
- Host helper: `./detect_firmware.py /dev/ttyACM0` (default port) reads the banner and reports the mode; requires `pyserial`.
- CLI: `python pico_switcher.py detect --port /dev/ttyACM0`

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

Usage (single CLI, recommended)
1) Switch to MicroPython
   - `python pico_switcher.py to-py --port /dev/ttyACM0 --verbose`
   - This detects mode, triggers BOOTSEL, mounts `RPI-RP2` if needed, flashes the MicroPython UF2, then installs `py/boot.py` + `py/bootloader_trigger.py`.

2) Switch to C++
   - `python pico_switcher.py to-cpp --port /dev/ttyACM0 --verbose`
   - This detects mode, triggers BOOTSEL, mounts `RPI-RP2` if needed, and flashes the C++ UF2.

3) Flash any UF2 while already in BOOTSEL
   - `python pico_switcher.py flash /path/to/file.uf2 --verbose`

4) Only install MicroPython helper files
   - `python pico_switcher.py install-py-files --port /dev/ttyACM0`

5) If autodetect misses your mode
   - Override explicitly: `--mode py`, `--mode cpp`, or `--mode bootsel`.

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
