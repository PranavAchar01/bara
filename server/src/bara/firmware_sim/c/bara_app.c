/* bara firmware application: scan the inputs, debounce them, report them over USB HID and the
 * serial console, drive the status LED and speaker, and keep the screen's text buffer.
 * Portable C, no libc: it builds the same for the chip and for the host test harness. */
#include "bara_hal.h"
#include "bara_config.h"

enum { IN_BUTTON = 0, IN_KEY = 1, IN_SWITCH = 2, IN_ENC = 3, IN_AXIS = 4, IN_MKEY = 5, IN_SENSOR = 6 };

typedef struct {
  const char *label;
  u8 kind;
  u8 pin;  /* button/switch/key pin, matrix column, encoder A */
  u8 pin2; /* matrix row, encoder B */
  u8 hid;  /* keyboard usage, 0 = none */
  u8 adc;  /* ADC channel for an axis or sensor */
  const char *unit; /* sensor unit */
  i32 lo10, hi10;   /* sensor range, tenths of a unit */
  i32 rest10;       /* sensor resting value, tenths of a unit */
} bara_input_t;

#include "bara_inputs.h"

/* The screen's text: what the display shows, one string per row. */
char bara_screen[SCREEN_ROWS][SCREEN_COLS + 1];
/* Last HID report: keyboard [mods, 0, k1..k6] or gamepad [btn lo, btn hi, x, y]. */
u8 bara_hid[8];
volatile u32 bara_presses;

static u8 level[N_INPUTS];   /* debounced: 1 = pressed */
static u8 rawprev[N_INPUTS]; /* last raw sample */
static u32 since[N_INPUTS];  /* when the raw sample last changed */
static u8 encprev[N_INPUTS];
static i16 axisv[N_INPUTS];
static u32 last_blink;
static u8 blink_on;
static u32 tone_until;
static u8 tone_level;
static int held;
static u32 last_axis;
static u32 last_clock;
static u32 uptime_s;
static i32 sensorv[N_INPUTS]; /* last reported reading, tenths of a unit */
static u8 sensor_init[N_INPUTS];
static u8 alert;
static u32 last_sense;

/* ---- text out, no printf --------------------------------------------------------------- */
static void puts_(const char *s) {
  while (*s) hal_putc(*s++);
}
static void putu(u32 v) {
  static const u32 pow10[] = {1000000000u, 100000000u, 10000000u, 1000000u, 100000u, 10000u, 1000u, 100u, 10u, 1u};
  int started = 0;
  for (int i = 0; i < 10; i++) {
    char d = '0';
    while (v >= pow10[i]) {
      v -= pow10[i];
      d++;
    }
    if (d != '0' || started || i == 9) {
      hal_putc(d);
      started = 1;
    }
  }
}
static void puti(int v) {
  if (v < 0) {
    hal_putc('-');
    putu((u32)(-v));
  } else {
    hal_putc('+');
    putu((u32)v);
  }
}
static void puthex2(u8 v) {
  static const char hex[] = "0123456789ABCDEF";
  hal_putc(hex[v >> 4]);
  hal_putc(hex[v & 15]);
}
static void stamp(u32 now) {
  hal_putc('[');
  putu(now);
  puts_(" ms] ");
}

/* ---- screen ----------------------------------------------------------------------------- */
static void line_set3(int row, const char *a, const char *b, const char *c) {
  if (row >= SCREEN_ROWS) return;
  char *d = bara_screen[row];
  int n = 0;
  while (a && *a && n < SCREEN_COLS) d[n++] = *a++;
  while (b && *b && n < SCREEN_COLS) d[n++] = *b++;
  while (c && *c && n < SCREEN_COLS) d[n++] = *c++;
  while (n < SCREEN_COLS) d[n++] = ' ';
  d[SCREEN_COLS] = 0;
}
static void line_set(int row, const char *a, const char *b) { line_set3(row, a, b, 0); }
static void utoa_(u32 v, char *out) {
  char tmp[11];
  int n = 0;
  static const u32 pow10[] = {1000000000u, 100000000u, 10000000u, 1000000u, 100000u, 10000u, 1000u, 100u, 10u, 1u};
  int started = 0;
  for (int i = 0; i < 10; i++) {
    char d = '0';
    while (v >= pow10[i]) {
      v -= pow10[i];
      d++;
    }
    if (d != '0' || started || i == 9) {
      tmp[n++] = d;
      started = 1;
    }
  }
  for (int i = 0; i < n; i++) out[i] = tmp[i];
  out[n] = 0;
}

#include "bara_game.h"

/* ---- HID -------------------------------------------------------------------------------- */
static void hid_send(void) {
  puts_("HID ");
#if DEVICE_KEYBOARD
  puts_("kb");
#else
  puts_("pad");
#endif
  for (int i = 0; i < (DEVICE_KEYBOARD ? 8 : 4); i++) {
    hal_putc(' ');
    puthex2(bara_hid[i]);
  }
  hal_putc('\n');
}
static void hid_key(u8 usage, int down) {
  if (!usage) return;
  if (usage >= 0xE0) {
    u8 bit = (u8)(1u << (usage - 0xE0));
    bara_hid[0] = down ? (u8)(bara_hid[0] | bit) : (u8)(bara_hid[0] & ~bit);
  } else {
    for (int i = 2; i < 8; i++) {
      if (down && bara_hid[i] == 0) {
        bara_hid[i] = usage;
        break;
      }
      if (!down && bara_hid[i] == usage) bara_hid[i] = 0;
    }
  }
  hid_send();
}
static void hid_button(int bit, int down) {
  if (bit < 0 || bit > 15) return;
  u8 *b = &bara_hid[bit >> 3];
  u8 m = (u8)(1u << (bit & 7));
  *b = down ? (u8)(*b | m) : (u8)(*b & ~m);
  hid_send();
}
static void consumer(u16 usage) {
  puts_("HIDC ");
  puthex2((u8)(usage >> 8));
  puthex2((u8)usage);
  hal_putc('\n');
}

/* ---- events ----------------------------------------------------------------------------- */
static int button_bit(int idx) {
  int bit = 0;
  for (int i = 0; i < idx; i++)
    if (BARA_INPUTS[i].kind == IN_BUTTON || BARA_INPUTS[i].kind == IN_SWITCH) bit++;
  return bit;
}

static void event(int i, int down, u32 now) {
  const bara_input_t *in = &BARA_INPUTS[i];
  stamp(now);
  if (in->kind == IN_SWITCH) puts_(down ? "switch on  " : "switch off ");
  else puts_(down ? "press   " : "release ");
  puts_(in->label);
  hal_putc('\n');
  if (down) {
    bara_presses++;
    held++;
    tone_until = now + TONE_MS;
    char n[11];
    utoa_(bara_presses, n);
    line_set(1, "> ", in->label);
    line_set(2, "Presses: ", n);
  } else if (held > 0) {
    held--;
  }
  if (down) game_button(i, now);
  if (in->kind == IN_KEY || in->kind == IN_MKEY) hid_key(in->hid, down);
  else if (in->kind == IN_BUTTON || in->kind == IN_SWITCH) hid_button(button_bit(i), down);
}

static void debounce(int i, int raw, u32 now) {
  if (raw != rawprev[i]) {
    rawprev[i] = (u8)raw;
    since[i] = now;
  } else if (raw != level[i] && now - since[i] >= DEBOUNCE_MS) {
    level[i] = (u8)raw;
    event(i, raw, now);
  }
}

static void encoder(int i, u32 now) {
  const bara_input_t *in = &BARA_INPUTS[i];
  u8 a = (u8)!hal_read(in->pin);
  u8 b = (u8)!hal_read(in->pin2);
  if (a && !encprev[i]) {
    /* A leads B clockwise: B is still open when A closes */
    int cw = !b;
    stamp(now);
    puts_("turn    ");
    puts_(in->label);
    puts_(cw ? " clockwise\n" : " anticlockwise\n");
    consumer(cw ? 0x00E9 : 0x00EA); /* Volume Increment / Decrement */
    line_set3(1, "> ", in->label, cw ? " right" : " left");
    tone_until = now + TONE_MS;
  }
  encprev[i] = a;
}

static void axis(int i, u32 now) {
  const bara_input_t *in = &BARA_INPUTS[i];
  int v = ((int)hal_adc(in->adc) - 2048) >> 4; /* -128..127 */
  if (v > -AXIS_DEADZONE && v < AXIS_DEADZONE) v = 0;
  int d = v - axisv[i];
  if (d >= 4 || d <= -4 || (v == 0 && axisv[i] != 0)) {
    axisv[i] = (i16)v;
    stamp(now);
    puts_("axis    ");
    puts_(in->label);
    hal_putc(' ');
    puti(v);
    hal_putc('\n');
    /* gamepad report: buttons in bytes 0-1, then one signed byte per axis */
    int slot = 2;
    for (int k = 0; k < i; k++)
      if (BARA_INPUTS[k].kind == IN_AXIS) slot++;
    if (slot < 8) bara_hid[slot] = (u8)(i8)v;
    game_axis(i, v);
    hid_send();
    char n[12];
    n[0] = v < 0 ? '-' : '+';
    utoa_((u32)(v < 0 ? -v : v), n + 1);
    line_set3(SCREEN_ROWS > 3 ? 3 : SCREEN_ROWS - 1, in->label, " ", n);
  }
}

/* The smallest cores have no divide instruction and the image links no runtime library, so divide by
 * shift and subtract. */
static u32 udiv_(u32 n, u32 d) {
  u32 q = 0, r = 0;
  for (int b = 31; b >= 0; b--) {
    r = (r << 1) | ((n >> b) & 1u);
    if (r >= d) {
      r -= d;
      q |= 1u << b;
    }
  }
  return q;
}

static void put_tenths(int v, char *out) {
  int n = 0;
  if (v < 0) {
    out[n++] = '-';
    v = -v;
  }
  char t[12];
  u32 whole = udiv_((u32)v, 10u);
  utoa_(whole, t);
  for (int i = 0; t[i]; i++) out[n++] = t[i];
  out[n++] = '.';
  out[n++] = (char)('0' + ((u32)v - whole * 10u));
  out[n] = 0;
}

/* A sensor is read through the ADC; the reading is converted to its physical unit, reported on the
 * serial console and the screen, and a reading in the outer tenth of its range raises the alert. */
static void sensor(int i, u32 now) {
  const bara_input_t *in = &BARA_INPUTS[i];
  int k = 0;
  for (int j = 0; j < i; j++)
    if (BARA_INPUTS[j].kind == IN_SENSOR) k++;
  int raw = (int)hal_adc(in->adc);
  int span = in->hi10 - in->lo10;
  int v10 = in->lo10 + (int)udiv_((u32)span * (u32)raw, 4095u);
  int d = v10 - sensorv[i];
  int step = (int)udiv_((u32)span, 100u);
  if (step < 1) step = 1;
  if (!sensor_init[i] || d >= step || d <= -step) {
    sensor_init[i] = 1;
    sensorv[i] = v10;
    char n[16];
    put_tenths(v10, n);
    stamp(now);
    puts_("sense   ");
    puts_(in->label);
    hal_putc(' ');
    puts_(n);
    hal_putc(' ');
    puts_(in->unit);
    hal_putc('\n');
    if (k + 1 < SCREEN_ROWS) line_set3(k + 1, n, in->unit, "");
  }
  int pct = (int)udiv_((u32)(v10 - in->lo10) * 100u, (u32)(span ? span : 1));
  int rest = (int)udiv_((u32)(in->rest10 - in->lo10) * 100u, (u32)(span ? span : 1));
  /* the end a sensor rests at is normal (a full battery, an empty room); only the far end alerts */
  if ((pct <= 10 && rest > 10) || (pct >= 90 && rest < 90)) alert |= (u8)(1u << (k & 7));
  else alert &= (u8)~(1u << (k & 7));
}

static void matrix_scan(u32 now) {
#if MATRIX_ROWS > 0
  static const u8 rows[MATRIX_ROWS] = MATRIX_ROW_PINS;
  for (int r = 0; r < MATRIX_ROWS; r++) {
    hal_write(rows[r], 0);
    hal_settle();
    for (int i = 0; i < N_INPUTS; i++) {
      if (BARA_INPUTS[i].kind == IN_MKEY && BARA_INPUTS[i].pin2 == rows[r]) debounce(i, !hal_read(BARA_INPUTS[i].pin), now);
    }
    hal_write(rows[r], 1);
  }
#else
  (void)now;
#endif
}

void app_init(void) {
  for (int i = 0; i < N_INPUTS; i++) {
    const bara_input_t *in = &BARA_INPUTS[i];
    if (in->kind == IN_AXIS || in->kind == IN_SENSOR) continue;
    hal_input_pullup(in->pin);
    if (in->kind == IN_ENC) hal_input_pullup(in->pin2);
  }
#if MATRIX_ROWS > 0
  static const u8 rows[MATRIX_ROWS] = MATRIX_ROW_PINS;
  for (int r = 0; r < MATRIX_ROWS; r++) {
    hal_output(rows[r]);
    hal_write(rows[r], 1);
  }
#endif
  if (LED_PIN != PIN_NONE) {
    hal_output(LED_PIN);
    hal_write(LED_PIN, LED_ACTIVE_LOW);
  }
  if (TONE_PIN != PIN_NONE) hal_output(TONE_PIN);
  if (MOTOR_PIN != PIN_NONE) hal_output(MOTOR_PIN);
  for (int r = 0; r < SCREEN_ROWS; r++) line_set(r, "", "");
  line_set(0, BARA_NAME, "");
  line_set(1, "Ready", "");
  line_set(2, "Presses: 0", "");
  puts_("\nbara-fw " BARA_FW_VERSION " | " BARA_NAME " | " BARA_MCU "\n");
  puts_("inputs ");
  putu(N_INPUTS);
  puts_(" | blink ");
  putu(BLINK_MS);
  puts_(" ms | debounce ");
  putu(DEBOUNCE_MS);
  puts_(" ms\nready\n");
  game_init();
}

void app_tick(u32 now) {
  for (int i = 0; i < N_INPUTS; i++) {
    const bara_input_t *in = &BARA_INPUTS[i];
    if (in->kind == IN_BUTTON || in->kind == IN_KEY || in->kind == IN_SWITCH) debounce(i, !hal_read(in->pin), now);
    else if (in->kind == IN_ENC) encoder(i, now);
    else if (in->kind == IN_AXIS && now - last_axis >= 8) axis(i, now);
    else if (in->kind == IN_SENSOR && now - last_sense >= 100) sensor(i, now);
  }
  if (now - last_sense >= 100) last_sense = now;
  if (now - last_axis >= 8) last_axis = now;
  matrix_scan(now);
  game_tick(now);
  if (LED_PIN != PIN_NONE) {
    int on;
    if ((LED_ON_PRESS && held > 0) || alert) on = 1;
    else {
      if (now - last_blink >= BLINK_MS) {
        last_blink = now;
        blink_on = (u8)!blink_on;
      }
      on = blink_on;
    }
    hal_write(LED_PIN, LED_ACTIVE_LOW ? !on : on);
  }
  if (TONE_PIN != PIN_NONE) {
    if ((int)(tone_until - now) > 0 || (alert && ((now >> 8) & 1u) == 0)) tone_level = (u8)!tone_level; /* 500 Hz square at a 1 ms tick */
    else tone_level = 0;
    hal_write(TONE_PIN, tone_level);
  }
  if (MOTOR_PIN != PIN_NONE) hal_write(MOTOR_PIN, held > 0 || alert ? 1 : 0);
  if (now - last_clock >= 1000) {
    last_clock = now;
    char n[11];
    utoa_(++uptime_s, n);
    if (SCREEN_ROWS > 3 && !N_AXES && !N_SENSORS) line_set3(3, "Up ", n, " s");
  }
}

#ifndef BARA_NO_MAIN
int main(void) {
  hal_init();
  app_init();
  for (;;) {
    hal_wait_tick();
    app_tick(hal_millis());
  }
}
#endif
