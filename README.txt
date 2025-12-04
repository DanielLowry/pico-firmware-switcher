This project aims to make it possible to switch Raspberry Pi Pico firmware remotely (e.g., over SSH) without pressing the BOOTSEL button. Typical UF2s are a MicroPython firmware image or a C/C++ program. Doing this remotely requires a way to drop into the UF2 bootloader from whatever firmware is currently running.

Current state (early prototype)
- MicroPython side: `bootloader_trigger.py` (calls `machine.bootloader()`) and `boot.py` (prints `FW:PY` on boot; copy this onto the board).
- C++ side: `bootloader_trigger` firmware prints `FW:CPP` at startup, then waits for the key sequence `r` then `u` and calls `reset_usb_boot(...)` to enter UF2 mode.
- Python CLI and auto-detection described in `Pico Firmware Switcher.md` are not implemented yet; switching is done with the shell scripts below.

Repo layout (relevant bits)
- `uf2s/` — stored UF2 images (MicroPython and the built C++ bootloader).
- `py/bootloader_trigger.py` — MicroPython bootloader trigger.
- `cpp/` — C++ sources and build outputs (including `build/bootloader_trigger.uf2`).
- `shell/` — helper scripts for flashing and triggering.

Prerequisites
- `mpremote` installed and able to talk to your Pico (for the MicroPython trigger).
- Pico shows up as `RPI-RP2` when in BOOTSEL mode.
- A serial port path for the Pico (commonly `/dev/ttyACM0` on Linux).

Identify the current firmware
- Make sure `py/boot.py` is on the MicroPython filesystem so it prints `FW:PY` on boot.
- The C++ bootloader trigger prints `FW:CPP` on boot after you flash the rebuilt UF2.
- Host helper: `./detect_firmware.py /dev/ttyACM0` (default port) reads the banner and reports the mode; requires `pyserial`.

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

Usage (manual workflow)
1) Flash MicroPython UF2 (from BOOTSEL mode)
   - Put the Pico in BOOTSEL mode (button + power) once.
   - Run: `./shell/load_micropython_uf2.sh`
   - This copies `uf2s/Pico-MicroPython-20250415-v1.25.0.uf2` to the `RPI-RP2` volume.

2) Drop to UF2 bootloader from MicroPython (remote)
   - Ensure the Pico is running MicroPython and expose the serial port (e.g., `/dev/ttyACM0`).
   - Run: `./shell/trigger_py_boot.sh /dev/ttyACM0 true`
   - This uses `mpremote` to execute `bootloader_trigger.py`, which reboots the board into UF2 mode (the `RPI-RP2` drive should appear).

3) Flash the C++ bootloader trigger UF2
   - With the board now in UF2 mode, run: `./shell/load_cpp_bootloader_uf2.sh`
   - This copies `uf2s/bootloader_trigger.uf2` (built from `cpp/bootloader_trigger.cpp`) to the Pico.

4) Use the C++ bootloader trigger
   - Connect to the Pico over serial (e.g., `screen /dev/ttyACM0 115200`).
   - Press `r` then `u` to reboot into UF2 mode. From there, you can copy another UF2 to `RPI-RP2` (e.g., via `./shell/load_uf2.sh <filename.uf2>`).

Notes and next steps
- The single-command Python CLI and banner-based auto-detection described in `Pico Firmware Switcher.md` are not present yet.
- The C++ trigger currently uses the two-key `r`/`u` sequence; the planned `FW:CPP` + single `'b'` trigger is still to come.
- MicroPython itself ships as a UF2 (already in `uf2s/`); your Python files (`boot.py`, `bootloader_trigger.py`, later your app) are copied directly onto the MicroPython filesystem, not built into a UF2.
