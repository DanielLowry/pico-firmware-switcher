// Built-in demo C++ client entrypoint for the migration profile.
//
// This file gives the Phase 1 demo profile a concrete C++ client source even
// before the managed runtime exists. Later phases will compile files like this
// into the switcher-owned runtime and call `client_app_main()` on core1.

#include <stdio.h>

extern "C" void client_app_main(void) {
    printf("demo client\n");
}
