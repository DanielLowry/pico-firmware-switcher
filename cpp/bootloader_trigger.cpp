// bootloader_trigger.cpp

// Include necessary Pico SDK headers
#include <stdio.h>
#include "pico/stdlib.h"      // Standard Pico SDK functions
#include "hardware/watchdog.h"// For watchdog_reboot
#include "pico/bootrom.h"     // For reset_usb_boot

// The keys the user must press in sequence to trigger UF2 mode
const char TRIGGER_KEY1 = 'r'; // reboot
const char TRIGGER_KEY2 = 'u'; // uf2 mode

int main() {
    stdio_init_all(); // Initialize all standard I/O (USB serial)
    sleep_ms(100);    // Let USB settle

    printf("FW:CPP\n"); // Banner so the host can identify firmware
    printf("Press '%c' then '%c' to reboot into UF2 bootloader mode.\n", TRIGGER_KEY1, TRIGGER_KEY2);

    while (true) {
        // Wait for the first key (non-blocking)
        int ch1 = getchar_timeout_us(0);
        if (ch1 != PICO_ERROR_TIMEOUT) {
            printf("You pressed: '%c'\n", ch1);

            if (ch1 == TRIGGER_KEY1) {
                // First key correct, prompt for second key
                printf("Now press '%c' to confirm reboot.\n", TRIGGER_KEY2);

                // Wait for the second key (non-blocking)
                while (true) {
                    int ch2 = getchar_timeout_us(0);
                    if (ch2 != PICO_ERROR_TIMEOUT) {
                        printf("You pressed: '%c'\n", ch2);

                        if (ch2 == TRIGGER_KEY2) {
                            // Both keys correct, reboot into UF2 bootloader
                            printf("Rebooting into UF2 bootloader mode...\n");
                            sleep_ms(100); // Short delay for message to flush
                            reset_usb_boot(0, 0); // Enter UF2 bootloader
                        } else {
                            // Second key incorrect, restart process
                            printf("Incorrect second key. Start over.\n");
                        }
                        break; // Exit inner loop to start over
                    }
                    sleep_ms(10); // Small delay to avoid busy-waiting
                }
            } else {
                // First key incorrect, prompt again
                printf("Incorrect first key. Please press '%c' first.\n", TRIGGER_KEY1);
            }
        }
        sleep_ms(10); // Small delay to avoid busy-waiting
    }

    return 0;
}
