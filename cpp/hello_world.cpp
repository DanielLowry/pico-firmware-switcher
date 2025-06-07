#include <stdio.h>
#include "pico/stdlib.h"

// Entry point of the program
int main() {
    // Initialize all standard I/O (UART, USB, etc.)
    stdio_init_all();

    // Print "Hello, World!" to the standard output
    printf("Hello, World!\n");

    // Infinite loop to keep the program running
    while (true) {
        tight_loop_contents(); // Hint to the compiler that nothing happens here
    }

    // This line will never be reached 
    return 0;
}