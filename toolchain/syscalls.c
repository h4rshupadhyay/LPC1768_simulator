/* SPDX-License-Identifier: MIT.
 * Bare-metal newlib hooks. No host filesystem or process API is exposed.
 * Debuggers may read lpc_console_buffer/length to display stdout and stderr.
 */
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/stat.h>
#include <sys/types.h>

volatile char lpc_console_buffer[4096];
volatile unsigned lpc_console_length;
extern char _heap_start, _heap_end;

void *_sbrk(ptrdiff_t increment) {
  static char *current;
  if (!current) current = &_heap_start;
  ptrdiff_t available = &_heap_end - current;
  ptrdiff_t used = current - &_heap_start;
  if (increment > available || increment < -used) {
    errno = ENOMEM;
    return (void *)-1;
  }
  char *previous = current;
  current += increment;
  return previous;
}
int _write(int fd, const void *data, size_t size) {
  if (fd != 1 && fd != 2) { errno = EBADF; return -1; }
  const char *text = data;
  for (size_t i = 0; i < size; i++) {
    unsigned pos = lpc_console_length;
    if (pos < sizeof(lpc_console_buffer) - 1) {
      lpc_console_buffer[pos] = text[i];
      lpc_console_length = pos + 1;
      lpc_console_buffer[pos + 1] = 0;
    }
  }
  return (int)size;
}
int _read(int fd, void *data, size_t size) { (void)data; (void)size;
  if (fd != 0) { errno = EBADF; return -1; }
  return 0;
}
int _close(int fd) { (void)fd; errno = EBADF; return -1; }
int _fstat(int fd, struct stat *out) {
  if (fd < 0 || fd > 2) { errno = EBADF; return -1; }
  out->st_mode = S_IFCHR;
  return 0;
}
int _isatty(int fd) { return fd >= 0 && fd <= 2; }
off_t _lseek(int fd, off_t offset, int whence) {
  (void)fd; (void)offset; (void)whence; errno = ESPIPE; return -1;
}
int _getpid(void) { return 1; }
int _kill(int pid, int sig) { (void)pid; (void)sig; errno = EINVAL; return -1; }
__attribute__((noreturn)) void _exit(int status) { (void)status; for (;;) {} }
