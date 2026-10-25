/* RP2040 HAL, register level (RP2040 datasheet build-date 2023-06). No pico-sdk: XOSC at
 * 12 MHz as clk_ref/clk_sys, SIO GPIO, UART0 on GP0, TIMER alarm 0 for a 1 ms tick, ADC. */
#include "bara_hal.h"
#include "bara_config.h"

#define REG(a) (*(volatile u32 *)(a))
#define CLR(a) (*(volatile u32 *)((a) + 0x3000u)) /* atomic clear alias */

#define CLOCKS 0x40008000u
#define RESETS 0x4000C000u
#define IO_BANK0 0x40014000u
#define PADS_BANK0 0x4001C000u
#define XOSC 0x40024000u
#define UART0 0x40034000u
#define ADC 0x4004C000u
#define TIMER 0x40054000u
#define WATCHDOG 0x40058000u
#define SIO 0xD0000000u

static u32 ticks;
static u32 next_alarm;

void hal_init(void) {
  /* crystal oscillator, then clk_ref and clk_sys from it */
  REG(XOSC + 0x00) = 0xAA0;                    /* CTRL FREQ_RANGE 1_15MHZ */
  REG(XOSC + 0x0C) = 47;                       /* STARTUP delay */
  REG(XOSC + 0x00) = 0xAA0 | (0xFABu << 12);   /* ENABLE */
  while (!(REG(XOSC + 0x04) & (1u << 31))) {   /* STATUS.STABLE */
  }
  REG(CLOCKS + 0x30) = 2;                      /* CLK_REF_CTRL SRC = xosc */
  REG(CLOCKS + 0x3C) = 0;                      /* CLK_SYS_CTRL SRC = clk_ref */
  REG(CLOCKS + 0x48) = (1u << 11);             /* CLK_PERI_CTRL ENABLE, AUXSRC clk_sys */
  REG(CLOCKS + 0x60) = (1u << 11) | (3u << 5); /* CLK_ADC_CTRL ENABLE, AUXSRC xosc */
  REG(WATCHDOG + 0x2C) = (1u << 9) | 12;       /* TICK: 1 us from 12 MHz */
  u32 bits = (1u << 0) | (1u << 5) | (1u << 8) | (1u << 21) | (1u << 22); /* adc io pads timer uart0 */
  CLR(RESETS + 0x0) = bits;
  while ((REG(RESETS + 0x8) & bits) != bits) {
  }
  REG(IO_BANK0 + 0x04 + 8 * 0) = 2; /* GP0 = UART0 TX */
  REG(UART0 + 0x24) = 6;            /* IBRD: 12 MHz / (16 * 115200) = 6.51 */
  REG(UART0 + 0x28) = 33;           /* FBRD */
  REG(UART0 + 0x2C) = (3u << 5) | (1u << 4); /* LCR_H 8N1, FIFO */
  REG(UART0 + 0x30) = (1u << 0) | (1u << 8) | (1u << 9); /* CR UARTEN TXE RXE */
  REG(ADC + 0x00) = 1; /* CS.EN */
  next_alarm = REG(TIMER + 0x28) + 1000;
  REG(TIMER + 0x10) = next_alarm; /* ALARM0 */
}

void hal_wait_tick(void) {
  while (!(REG(TIMER + 0x34) & 1)) /* INTR.ALARM_0 */
    __asm__ volatile("wfe");
  REG(TIMER + 0x34) = 1; /* clear */
  next_alarm += 1000;
  REG(TIMER + 0x10) = next_alarm;
  ticks++;
}

u32 hal_millis(void) { return ticks; }

void hal_input_pullup(u8 pin) {
  if (pin == PIN_NONE) return;
  REG(IO_BANK0 + 0x04 + 8u * pin) = 5;                  /* FUNCSEL SIO */
  REG(PADS_BANK0 + 0x04 + 4u * pin) = 0x40 | 0x10 | 0x08 | 0x02; /* IE, 4 mA, PUE, SCHMITT */
}

void hal_output(u8 pin) {
  if (pin == PIN_NONE) return;
  REG(IO_BANK0 + 0x04 + 8u * pin) = 5;
  REG(PADS_BANK0 + 0x04 + 4u * pin) = 0x40 | 0x10;
  REG(SIO + 0x24) = 1u << pin; /* GPIO_OE_SET */
}

int hal_read(u8 pin) { return (REG(SIO + 0x04) >> pin) & 1; }

void hal_write(u8 pin, int level) {
  if (pin == PIN_NONE) return;
  REG(SIO + (level ? 0x14 : 0x18)) = 1u << pin; /* GPIO_OUT_SET / CLR */
}

u16 hal_adc(u8 ch) {
  REG(PADS_BANK0 + 0x04 + 4u * (26u + ch)) = 0x80; /* OD, input disabled: analog */
  REG(ADC + 0x00) = 1 | ((u32)ch << 12) | (1u << 2); /* EN, AINSEL, START_ONCE */
  while (!(REG(ADC + 0x00) & (1u << 8))) {           /* READY */
  }
  return (u16)(REG(ADC + 0x04) & 0xFFF);
}

void hal_putc(char c) {
  while (REG(UART0 + 0x18) & (1u << 5)) { /* FR.TXFF */
  }
  REG(UART0 + 0x00) = (u8)c;
}

void hal_settle(void) {
  for (volatile int i = 0; i < 4; i++) {
  }
}

/* ---- startup ---------------------------------------------------------------------------- */
extern u32 __data_load, __data_start, __data_end, __bss_start, __bss_end, __stack_top;
int main(void);

void Reset_Handler(void) {
  u32 *src = &__data_load;
  if (src != &__data_start)
    for (u32 *dst = &__data_start; dst < &__data_end;) *dst++ = *src++;
  for (u32 *dst = &__bss_start; dst < &__bss_end;) *dst++ = 0;
  REG(0xE000ED08) = IMAGE_ORIGIN; /* VTOR */
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
    0, 0, 0, 0,
    0, 0, 0, (void *)Default_Handler,
    0, 0, (void *)Default_Handler, (void *)Default_Handler,
};
