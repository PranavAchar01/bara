/* The few libc routines the compiler may emit calls to in a freestanding build. */
typedef unsigned int size_t_;
void *memset(void *d, int c, size_t_ n) {
  volatile unsigned char *p = (volatile unsigned char *)d;
  while (n--) *p++ = (unsigned char)c;
  return d;
}
void *memcpy(void *d, const void *s, size_t_ n) {
  volatile unsigned char *p = (volatile unsigned char *)d;
  const unsigned char *q = (const unsigned char *)s;
  while (n--) *p++ = *q++;
  return d;
}
void *memmove(void *d, const void *s, size_t_ n) {
  volatile unsigned char *p = (volatile unsigned char *)d;
  const unsigned char *q = (const unsigned char *)s;
  if (p < q) {
    while (n--) *p++ = *q++;
  } else {
    while (n--) p[n] = q[n];
  }
  return d;
}
