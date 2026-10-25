"""Firmware simulation: generate C firmware from a build's pin map, compile it with a real
cross compiler, run it on a CPU emulator with the board's peripherals modelled, and check the
analog side with ngspice.

What runs where, said plainly in every result:
- target build: `zig cc` (clang/LLVM) for the build's MCU, a flashable ELF + UF2.
- emulation: the compiled ARM machine code runs in Unicorn (QEMU's CPU core). GPIO, UART,
  timer/RTC, ADC and clock registers are modelled in Python; nothing else is.
- host simulation: the same firmware logic built for this Mac against a HAL shim, used for the
  unit tests and for MCUs the emulator does not cover (ESP32, AVR).
"""
