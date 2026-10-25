/* Host HAL: the same application built for this computer. Driven over stdin/stdout so the
 * server can run it like a board: virtual time, pin levels in, pin levels and text out.
 *
 * stdin:  "p <pin> <0|1>"  set an input pin's level (buttons pull to 0)
 *         "a <ch> <0..4095>" ADC channel value
 *         "s <ms>"          run ms ticks
 *         "q"               quit
 * stdout: "U <text>"        a serial console line
 *         "G <ms> <pin> <level>"  an output pin changed
 *         "S <row> <text>"  a screen row (after each step)
 *         "D <ms>"          step done
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bara_hal.h"
#include "bara_config.h"

void app_init(void);
void app_tick(u32 now);
extern char bara_screen[SCREEN_ROWS][SCREEN_COLS + 1];

static u32 now_ms;
static u8 in_level[256];
static int out_level[256];
static u16 adc_val[16];
static char line[256];
static int line_n;
/* matrix rows are outputs driven low to select; a column pin reads the AND of its keys */
static u8 key_row_of[256][8];

void hal_init(void) {
  memset(in_level, 1, sizeof in_level);
  for (int i = 0; i < 256; i++) out_level[i] = -1;
  for (int i = 0; i < 16; i++) adc_val[i] = 2048;
}
void hal_wait_tick(void) { now_ms++; }
u32 hal_millis(void) { return now_ms; }
void hal_input_pullup(u8 pin) { (void)pin; }
void hal_output(u8 pin) { (void)pin; }
int hal_read(u8 pin) {
  int level = in_level[pin];
  /* matrix: a pressed key between this column and a row driven low pulls the column low */
  for (int r = 0; r < 8; r++) {
    u8 row = key_row_of[pin][r];
    if (row && out_level[row - 1] == 0) level = 0;
  }
  return level;
}
static int quiet_pin(u8 pin) {
#if MATRIX_ROWS > 0
  static const u8 rows[MATRIX_ROWS] = MATRIX_ROW_PINS; /* scan strobes are not reported */
  for (int r = 0; r < MATRIX_ROWS; r++)
    if (rows[r] == pin) return 1;
#endif
  (void)pin;
  return 0;
}
void hal_write(u8 pin, int level) {
  if (pin == PIN_NONE) return;
  if (out_level[pin] != level) {
    out_level[pin] = level;
    if (!quiet_pin(pin)) printf("G %u %u %d\n", now_ms, pin, level);
  }
}
u16 hal_adc(u8 ch) { return adc_val[ch & 15]; }
void hal_putc(char c) {
  if (c == '\n' || line_n == (int)sizeof line - 1) {
    line[line_n] = 0;
    printf("U %s\n", line);
    line_n = 0;
    return;
  }
  line[line_n++] = c;
}
void hal_settle(void) {}

int main(void) {
  char cmd[128];
  hal_init();
  app_init();
  fflush(stdout);
  while (fgets(cmd, sizeof cmd, stdin)) {
    if (cmd[0] == 'q') break;
    if (cmd[0] == 'p') {
      int pin = 0, lvl = 1;
      sscanf(cmd + 1, "%d %d", &pin, &lvl);
      in_level[pin & 255] = (u8)lvl;
    } else if (cmd[0] == 'm') { /* "m <col> <row> <0|1>": matrix key at col/row closed (1) or open */
      int col = 0, row = 0, closed = 0;
      sscanf(cmd + 1, "%d %d %d", &col, &row, &closed);
      for (int r = 0; r < 8; r++) {
        if (closed && key_row_of[col & 255][r] == 0) {
          key_row_of[col & 255][r] = (u8)(row + 1);
          break;
        }
        if (!closed && key_row_of[col & 255][r] == row + 1) key_row_of[col & 255][r] = 0;
      }
    } else if (cmd[0] == 'a') {
      int ch = 0, v = 2048;
      sscanf(cmd + 1, "%d %d", &ch, &v);
      adc_val[ch & 15] = (u16)v;
    } else if (cmd[0] == 's') {
      int ms = 1;
      sscanf(cmd + 1, "%d", &ms);
      for (int i = 0; i < ms; i++) {
        hal_wait_tick();
        app_tick(hal_millis());
      }
      for (int r = 0; r < SCREEN_ROWS; r++) printf("S %d %s\n", r, bara_screen[r]);
      printf("D %u\n", now_ms);
    }
    fflush(stdout);
  }
  return 0;
}
