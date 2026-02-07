// bootloader_trigger.cpp

// Include necessary Pico SDK headers
#include <stdio.h>
#include "pico/stdlib.h"      // Standard Pico SDK functions
#include "pico/bootrom.h"     // For reset_usb_boot

// Single trigger key used by host tooling.
const char TRIGGER_KEY = 'b';

static void enter_uf2_bootloader() {
    printf("Rebooting into UF2 bootloader mode...\n");
    sleep_ms(100); // Short delay for message to flush
    reset_usb_boot(0, 0); // Enter UF2 bootloader
}

int main() {
    stdio_init_all(); // Initialize all standard I/O (USB serial)
    sleep_ms(100);    // Let USB settle

    printf("FW:CPP\n"); // Banner so the host can identify firmware
    printf("Press '%c' to reboot into UF2 bootloader mode.\n", TRIGGER_KEY);

    while (true) {
        int ch1 = getchar_timeout_us(0);
        if (ch1 == PICO_ERROR_TIMEOUT) {
            sleep_ms(10); // Small delay to avoid busy-waiting
            continue;
        }

        printf("You pressed: '%c'\n", ch1);

        if (ch1 == TRIGGER_KEY) {
            enter_uf2_bootloader();
        } else {
            printf("Unknown command. Press '%c'.\n", TRIGGER_KEY);
        }
    }

    return 0;
}
