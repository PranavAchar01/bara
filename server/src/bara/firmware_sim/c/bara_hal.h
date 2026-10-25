/* bara firmware HAL: what the application needs from a chip. One implementation per target
 * (hal_nrf52840.c, hal_rp2040.c) and one for the host build (hal_host.c). */
#ifndef BARA_HAL_H
#define BARA_HAL_H

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef signed short i16;
typedef signed char i8;

#define PIN_NONE 255

void hal_init(void);
/* Sleep until the next 1 ms system tick. */
void hal_wait_tick(void);
u32 hal_millis(void);
void hal_input_pullup(u8 pin);
void hal_output(u8 pin);
/* Pin level, 1 = high. */
int hal_read(u8 pin);
void hal_write(u8 pin, int level);
/* 12-bit ADC sample of channel ch (0..4095). */
u16 hal_adc(u8 ch);
void hal_putc(char c);
/* A few microseconds for a matrix row to settle. */
void hal_settle(void);

#endif
