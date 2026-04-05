// Public client interface for the managed Pico switcher C++ runtime.
//
// Client code that wants to be built into a managed switcher UF2 should include
// this header and define `client_app_main()`. The switcher runtime owns
// `main()`, USB stdio setup, the host command channel, BOOTSEL entry, and core0.
// The client entrypoint is launched on core1 and may use normal Pico SDK APIs
// there, including `printf` for stdout logging.
//
// Supported client behavior:
// - define `extern "C" void client_app_main(void);`
// - run application logic on core1
// - use Pico SDK helpers from that client code
// - write stdout with `printf`
//
// Unsupported client behavior:
// - define `main()`
// - read stdin or own the switcher command channel
// - call `reset_usb_boot(...)` directly
// - manage multicore startup/reset directly
// - reinitialize stdio
//
// This is a managed contract, not sandboxing. Unsupported code may still
// compile, but it is outside the supported integration model and may break
// switching.

#ifndef PICO_SWITCHER_CLIENT_H
#define PICO_SWITCHER_CLIENT_H

#ifdef __cplusplus
extern "C" {
#endif

void client_app_main(void);

#ifdef __cplusplus
}
#endif

#endif  // PICO_SWITCHER_CLIENT_H
