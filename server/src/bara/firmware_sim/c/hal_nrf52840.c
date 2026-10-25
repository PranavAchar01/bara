/* nRF52840 HAL, register level (nRF52840 Product Specification v1.7). No SoftDevice, no SDK:
 * GPIO P0/P1, legacy UART0 for the console, RTC0 at ~1 kHz for the tick, SAADC for axes. */
#include "bara_hal.h"
#include "bara_config.h"

#define REG(a) (*(volatile u32 *)(a))

#define CLOCK 0x40000000u
#define UART0 0x40002000u
#define SAADC 0x40007000u
#define RTC0 0x4000B000u
#define P0 0x50000000u
#define P1 0x50000300u

static u32 port(u8 pin) { return pin >= 32 ? P1 : P0; }
static u32 bit(u8 pin) { return 1u << (pin & 31); }

static volatile i16 adc_result;

void hal_init(void) {
  REG(CLOCK + 0x104) = 0; /* EVENTS_LFCLKSTARTED */
  REG(CLOCK + 0x518) = 1; /* LFCLKSRC = XTAL */
  REG(CLOCK + 0x008) = 1; /* TASKS_LFCLKSTART */
  while (!REG(CLOCK + 0x104)) {
  }
  REG(RTC0 + 0x508) = 32; /* PRESCALER: 32768 / 33 = 993 Hz */
  REG(RTC0 + 0x000) = 1;  /* TASKS_START */
  REG(UART0 + 0x50C) = SERIAL_TX_PIN; /* PSEL.TXD */
  REG(UART0 + 0x524) = 0x01D7E000u;   /* BAUDRATE 115200 */
  REG(UART0 + 0x500) = 4;             /* ENABLE */
  REG(UART0 + 0x008) = 1;             /* TASKS_STARTTX */
  REG(SAADC + 0x5F0) = 2;             /* RESOLUTION 12 bit */
  REG(SAADC + 0x500) = 1;             /* ENABLE */
}

void hal_wait_tick(void) {
  while (!REG(RTC0 + 0x100)) /* EVENTS_TICK */
    __asm__ volatile("wfe");
  REG(RTC0 + 0x100) = 0;
}

u32 hal_millis(void) {
  u32 c = REG(RTC0 + 0x504); /* COUNTER, 24 bit */
  return (u32)(((unsigned long long)c * 33000u) >> 15);
}

void hal_input_pullup(u8 pin) {
  if (pin == PIN_NONE) return;
  REG(port(pin) + 0x700 + 4u * (pin & 31)) = (3u << 2); /* DIR in, INPUT connect, PULL up */
}

void hal_output(u8 pin) {
  if (pin == PIN_NONE) return;
  REG(port(pin) + 0x700 + 4u * (pin & 31)) = 3u; /* DIR out, INPUT disconnect */
}

int hal_read(u8 pin) { return (REG(port(pin) + 0x510) & bit(pin)) != 0; }

void hal_write(u8 pin, int level) {
  if (pin == PIN_NONE) return;
  REG(port(pin) + (level ? 0x508 : 0x50C)) = bit(pin); /* OUTSET / OUTCLR */
}

u16 hal_adc(u8 ch) {
  REG(SAADC + 0x510) = (u32)ch + 1u; /* CH[0].PSELP = AINch */
  REG(SAADC + 0x62C) = (u32)&adc_result; /* RESULT.PTR */
  REG(SAADC + 0x630) = 1;                /* RESULT.MAXCNT */
  REG(SAADC + 0x104) = 0;                /* EVENTS_END */
  REG(SAADC + 0x000) = 1;                /* TASKS_START */
  REG(SAADC + 0x004) = 1;                /* TASKS_SAMPLE */
  while (!REG(SAADC + 0x104)) {
  }
  i16 v = adc_result;
  return (u16)(v < 0 ? 0 : v > 4095 ? 4095 : v);
}

void hal_putc(char c) {
  REG(UART0 + 0x11C) = 0; /* EVENTS_TXDRDY */
  REG(UART0 + 0x51C) = (u8)c; /* TXD */
  while (!REG(UART0 + 0x11C)) {
  }
}

void hal_settle(void) {
  for (volatile int i = 0; i < 8; i++) {
  }
}

/* ---- startup ---------------------------------------------------------------------------- */
extern u32 __data_load, __data_start, __data_end, __bss_start, __bss_end, __stack_top;
int main(void);

void Reset_Handler(void) {
  u32 *src = &__data_load;
  for (u32 *dst = &__data_start; dst < &__data_end;) *dst++ = *src++;
  for (u32 *dst = &__bss_start; dst < &__bss_end;) *dst++ = 0;
  REG(0xE000ED08) = IMAGE_ORIGIN; /* SCB->VTOR */
  main();
  for (;;) {
  }
}

void Default_Handler(void) {
  for (;;) {
  }
}

__attribute__((section(".vectors"), used)) const void *const vectors[16] = {
    &__stack_top, (void *)Reset_Handler, (void *)Default_Handler, (void *)Default_Handler,
    (void *)Default_Handler, (void *)Default_Handler, (void *)Default_Handler, 0,
    0, 0, 0, (void *)Default_Handler,
    (void *)Default_Handler, 0, (void *)Default_Handler, (void *)Default_Handler,
};
