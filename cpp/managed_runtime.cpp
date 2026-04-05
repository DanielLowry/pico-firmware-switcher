// Managed C++ runtime owned by the Pico switcher.
//
// This runtime is the C++ equivalent of the managed MicroPython layout: the
// switcher owns startup, stdio, profile banners, and the BOOTSEL control path,
// while client code plugs in through `client_app_main()` on core1. The host
// always talks to this runtime over stdin/stdout, and the client must stay
// within the contract declared in `switcher_client.h`.

#include <stdio.h>
#include <string.h>

#include "pico/bootrom.h"
#include "pico/multicore.h"
#include "pico/stdlib.h"
#include "switcher_client.h"

#ifndef PICO_SWITCHER_PROFILE_NAME
#define PICO_SWITCHER_PROFILE_NAME "demo"
#endif

#ifndef PICO_SWITCHER_BOOTSEL_COMMAND
#define PICO_SWITCHER_BOOTSEL_COMMAND "BOOTSEL"
#endif

namespace {

constexpr size_t COMMAND_BUFFER_SIZE = 64;

void client_core1_entry() {
    client_app_main();
    printf("client_app_main returned; idling core1\n");
    while (true) {
        sleep_ms(1000);
    }
}

void print_runtime_banner() {
    printf("FW:CPP\n");
    printf("PROFILE:CPP:%s\n", PICO_SWITCHER_PROFILE_NAME);
    printf("BOOTSEL_CMD:%s\n", PICO_SWITCHER_BOOTSEL_COMMAND);
}

void enter_uf2_bootloader() {
    printf("Entering UF2 bootloader...\n");
    sleep_ms(100);
    multicore_reset_core1();
    sleep_ms(20);
    reset_usb_boot(0, 0);
}

void handle_command(const char* command) {
    if (strcmp(command, PICO_SWITCHER_BOOTSEL_COMMAND) == 0) {
        enter_uf2_bootloader();
        return;
    }

    printf("Unknown command: %s\n", command);
}

void maybe_dispatch_command(char* command_buffer, size_t* command_length) {
    int ch = getchar_timeout_us(0);
    if (ch == PICO_ERROR_TIMEOUT) {
        return;
    }

    if (ch == '\r' || ch == '\n') {
        if (*command_length == 0) {
            return;
        }
        command_buffer[*command_length] = '\0';
        handle_command(command_buffer);
        *command_length = 0;
        return;
    }

    if (*command_length >= COMMAND_BUFFER_SIZE - 1) {
        printf("Discarding oversized command\n");
        *command_length = 0;
        return;
    }

    command_buffer[*command_length] = static_cast<char>(ch);
    *command_length += 1;
}

}  // namespace

int main() {
    stdio_init_all();
    sleep_ms(150);

    print_runtime_banner();
    multicore_launch_core1(client_core1_entry);

    char command_buffer[COMMAND_BUFFER_SIZE] = {0};
    size_t command_length = 0;

    while (true) {
        maybe_dispatch_command(command_buffer, &command_length);
        tight_loop_contents();
        sleep_ms(10);
    }

    return 0;
}
