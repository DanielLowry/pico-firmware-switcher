// Built-in demo client for the managed C++ runtime.
//
// This example shows the exact client surface downstream apps are expected to
// provide: include `switcher_client.h`, define `client_app_main()`, and keep
// all application logic inside that function. The switcher runtime owns
// startup, BOOTSEL switching, and core0, so the demo intentionally stays inside
// the supported core1 contract.

#include <stdio.h>

#include "pico/stdlib.h"
#include "switcher_client.h"

extern "C" void client_app_main(void) {
    while (true) {
        printf("demo client tick\n");
        sleep_ms(1000);
    }
}
