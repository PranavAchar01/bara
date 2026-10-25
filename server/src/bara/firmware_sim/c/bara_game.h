/* bara firmware game: a snake game the firmware plays on the display's framebuffer when the
 * device has a screen and is not a keyboard. Included into bara_app.c after the input table and
 * the console helpers, so it reads the same inputs the rest of the firmware does.
 *
 * The framebuffer is one byte per pixel, values 0 (background) to 3. The simulator reads
 * `bara_fb` out of the chip's RAM and draws it on the display part, so what is shown is what
 * this code drew. Steering: D-pad buttons or a joystick when the device has them; otherwise the
 * first two buttons turn left and right. Any other button starts a round. */
#ifndef BARA_GAME_H
#define BARA_GAME_H

#if GAME_MODE

#define CELL 4
#define TOP 8 /* pixels reserved for the score */
#define GCOLS (FB_W / CELL)
#define GROWS ((FB_H - TOP) / CELL)
#define MAXLEN (GCOLS * GROWS)

u8 bara_fb[FB_W * FB_H];

enum { G_READY = 0, G_RUN = 1, G_OVER = 2 };

static u8 g_state;
static u16 g_len;
static u8 g_x[MAXLEN], g_y[MAXLEN]; /* body, head first */
static i8 g_dx, g_dy, g_ndx, g_ndy;
static u8 g_fx, g_fy;
static u8 g_dirty = 1;
static u32 g_score, g_best, g_last, g_rng = 12345u;
static i8 g_dirbtn[4]; /* input index of up, down, left, right; -1 when absent */
static i8 g_turn[2];   /* input index of turn-left, turn-right when there is no D-pad */
static i8 g_axx = -1, g_axy = -1;

static u32 g_rand(void) {
  g_rng = g_rng * 1664525u + 1013904223u;
  return g_rng >> 8;
}

static int has_word(const char *s, const char *w) {
  for (; *s; s++) {
    const char *a = s, *b = w;
    while (*a && *b && ((*a | 32) == *b)) {
      a++;
      b++;
    }
    if (!*b) return 1;
  }
  return 0;
}

static void px(int x, int y, u8 v) {
  if (x >= 0 && y >= 0 && x < FB_W && y < FB_H) bara_fb[y * FB_W + x] = v;
}
static void rect(int x, int y, int w, int h, u8 v) {
  for (int j = 0; j < h; j++)
    for (int i = 0; i < w; i++) px(x + i, y + j, v);
}

/* 3x5 digits, one row per 3 bits */
static const u8 DIGITS[10][5] = {{7, 5, 5, 5, 7}, {2, 6, 2, 2, 7}, {7, 1, 7, 4, 7}, {7, 1, 7, 1, 7}, {5, 5, 7, 1, 1},
                                 {7, 4, 7, 1, 7}, {7, 4, 7, 5, 7}, {7, 1, 1, 1, 1}, {7, 5, 7, 5, 7}, {7, 5, 7, 1, 7}};
static int draw_num(int x, int y, u32 v, u8 col) {
  char t[11];
  utoa_(v, t);
  int n = 0;
  for (; t[n]; n++) {
  }
  for (int k = 0; k < n; k++)
    for (int r = 0; r < 5; r++)
      for (int c = 0; c < 3; c++)
        if (DIGITS[t[k] - '0'][r] & (4 >> c)) px(x + k * 4 + c, y + r, col);
  return n * 4;
}

static void place_food(void) {
  for (int tries = 0; tries < 200; tries++) {
    u8 x = (u8)(((g_rand() & 0xFFFFu) * GCOLS) >> 16), y = (u8)(((g_rand() & 0xFFFFu) * GROWS) >> 16);
    int clash = 0;
    for (int i = 0; i < g_len; i++)
      if (g_x[i] == x && g_y[i] == y) clash = 1;
    if (!clash) {
      g_fx = x;
      g_fy = y;
      return;
    }
  }
}

static void game_draw(u32 now) {
  for (int i = 0; i < FB_W * FB_H; i++) bara_fb[i] = 0;
  int w = draw_num(1, 1, g_score, 3);
  (void)w;
  draw_num(FB_W - 13, 1, g_best, 1);
  for (int x = 0; x < FB_W; x++) {
    px(x, TOP - 1, 3);
    px(x, FB_H - 1, 3);
  }
  for (int y = TOP - 1; y < FB_H; y++) {
    px(0, y, 3);
    px(FB_W - 1, y, 3);
  }
  rect(g_fx * CELL + 1, TOP + g_fy * CELL + 1, CELL - 2, CELL - 2, 2);
  for (int i = g_len - 1; i >= 0; i--) rect(g_x[i] * CELL + 1, TOP + g_y[i] * CELL + 1, CELL - 2, CELL - 2, i == 0 ? 2 : 1);
  if (g_state == G_READY && ((now >> 8) & 1)) rect(FB_W / 2 - 6, TOP + (FB_H - TOP) / 2 - 2, 12, 4, 3);
  if (g_state == G_OVER) {
    for (int x = 2; x < FB_W - 2; x += 2) {
      px(x, TOP + 1, 2);
      px(x, FB_H - 3, 2);
    }
  }
}

static void game_reset(void) {
  g_len = 3;
  for (int i = 0; i < g_len; i++) {
    g_x[i] = (u8)(GCOLS / 2 - i);
    g_y[i] = (u8)(GROWS / 2);
  }
  g_dx = g_ndx = 1;
  g_dy = g_ndy = 0;
  g_score = 0;
  place_food();
}

static void game_init(void) {
  for (int k = 0; k < 4; k++) g_dirbtn[k] = -1;
  g_turn[0] = g_turn[1] = -1;
  int nbtn = 0;
  for (int i = 0; i < N_INPUTS; i++) {
    const bara_input_t *in = &BARA_INPUTS[i];
    if (in->kind == IN_AXIS) {
      if (has_word(in->label, " x") && g_axx < 0) g_axx = (i8)i;
      if (has_word(in->label, " y") && g_axy < 0) g_axy = (i8)i;
    } else if (in->kind == IN_BUTTON) {
      if (has_word(in->label, "up")) g_dirbtn[0] = (i8)i;
      else if (has_word(in->label, "down")) g_dirbtn[1] = (i8)i;
      else if (has_word(in->label, "left")) g_dirbtn[2] = (i8)i;
      else if (has_word(in->label, "right")) g_dirbtn[3] = (i8)i;
      else if (nbtn < 2) g_turn[nbtn] = (i8)i;
      if (!has_word(in->label, "reset") && !has_word(in->label, "boot")) nbtn++;
    }
  }
  if (g_axx < 0 || g_axy < 0) {
    int seen = 0;
    for (int i = 0; i < N_INPUTS; i++)
      if (BARA_INPUTS[i].kind == IN_AXIS) {
        if (seen == 0 && g_axx < 0) g_axx = (i8)i;
        else if (g_axy < 0 && i != g_axx) g_axy = (i8)i;
        seen++;
      }
  }
  game_reset();
  g_state = G_READY;
  game_draw(0);
  puts_("game snake: press a button to start\n");
}

static void steer(int dx, int dy) {
  if (dx == -g_dx && dy == -g_dy) return; /* no reversing into the neck */
  g_ndx = (i8)dx;
  g_ndy = (i8)dy;
}

static void game_start(void) {
  g_dirty = 1;
  game_reset();
  g_state = G_RUN;
  puts_("game start\n");
}

/* A button went down. */
static void game_button(int i, u32 now) {
  const bara_input_t *in = &BARA_INPUTS[i];
  if (in->kind != IN_BUTTON || has_word(in->label, "reset") || has_word(in->label, "boot")) return;
  g_rng += now;
  if (g_state != G_RUN) game_start();
  if (i == g_dirbtn[0]) steer(0, -1);
  else if (i == g_dirbtn[1]) steer(0, 1);
  else if (i == g_dirbtn[2]) steer(-1, 0);
  else if (i == g_dirbtn[3]) steer(1, 0);
  else if (g_dirbtn[0] < 0 && g_dirbtn[2] < 0 && (i == g_turn[0] || i == g_turn[1])) {
    int left = i == g_turn[0];
    /* turn 90 degrees from the heading */
    int ndx = left ? g_dy : -g_dy, ndy = left ? -g_dx : g_dx;
    steer(ndx, ndy);
  }
}

static void game_axis(int i, int v) {
  if (i != g_axx && i != g_axy) return;
  if ((v < 60 && v > -60)) return;
  if (g_state != G_RUN) game_start();
  if (i == g_axx && v > 60) steer(1, 0);
  else if (i == g_axx && v < -60) steer(-1, 0);
  else if (i == g_axy && v > 60) steer(0, -1); /* stick up reads positive */
  else if (i == g_axy && v < -60) steer(0, 1);
}

static void game_step(void) {
  g_dx = g_ndx;
  g_dy = g_ndy;
  int nx = g_x[0] + g_dx, ny = g_y[0] + g_dy;
  int dead = nx < 0 || ny < 0 || nx >= GCOLS || ny >= GROWS;
  int eat = !dead && nx == g_fx && ny == g_fy;
  for (int i = 0; i < g_len - (eat ? 0 : 1) && !dead; i++)
    if (g_x[i] == nx && g_y[i] == ny) dead = 1;
  if (dead) {
    g_state = G_OVER;
    if (g_score > g_best) g_best = g_score;
    puts_("game over score ");
    putu(g_score);
    hal_putc('\n');
    return;
  }
  if (eat && g_len < MAXLEN) g_len++;
  for (int i = g_len - 1; i > 0; i--) {
    g_x[i] = g_x[i - 1];
    g_y[i] = g_y[i - 1];
  }
  g_x[0] = (u8)nx;
  g_y[0] = (u8)ny;
  if (eat) {
    g_score++;
    place_food();
    puts_("game score ");
    putu(g_score);
    hal_putc('\n');
  }
}

static void game_tick(u32 now) {
  static u32 blink = 99;
  u32 period = 140 - (g_score > 12 ? 60 : g_score * 5);
  u8 dirty = g_dirty;
  if (g_state == G_RUN && now - g_last >= period) {
    g_last = now;
    game_step();
    dirty = 1;
  }
  if (g_state == G_READY && ((now >> 8) & 1) != blink) {
    blink = (now >> 8) & 1;
    dirty = 1;
  }
  if (dirty) {
    g_dirty = 0;
    game_draw(now);
  }
}

#else
static void game_init(void) {}
static void game_button(int i, u32 now) {
  (void)i;
  (void)now;
}
static void game_axis(int i, int v) {
  (void)i;
  (void)v;
}
static void game_tick(u32 now) { (void)now; }
#endif
#endif
