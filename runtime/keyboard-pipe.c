/* FreeRDP 3.32's Unicode pipe treats EAGAIN as fatal and sleeps 5 ms per key edge.
 * Scope both workarounds to that pipe's reader thread; leave all other I/O/timers alone.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static ssize_t (*original_read)(int, void *, size_t);
static void (*original_sleep)(unsigned int);
static __thread int keyboard_fd = -1;

__attribute__((constructor)) static void initialize(void) {
    original_read = dlsym(RTLD_NEXT, "read");
    original_sleep = dlsym(RTLD_NEXT, "Sleep");
}

static int is_keyboard_pipe(int fd) {
    if (keyboard_fd == fd) return 1;
    const char *expected = getenv("RDP_KEYBOARD_PIPE");
    if (!expected) return 0;
    char link[64], target[4096];
    int saved_errno = errno;
    snprintf(link, sizeof(link), "/proc/self/fd/%d", fd);
    ssize_t size = readlink(link, target, sizeof(target) - 1);
    if (size >= 0) target[size] = '\0';
    int matches = size >= 0 && strcmp(target, expected) == 0;
    errno = saved_errno;
    if (matches) keyboard_fd = fd;
    return matches;
}

ssize_t read(int fd, void *buffer, size_t count) {
    ssize_t result = original_read(fd, buffer, count);
    if (is_keyboard_pipe(fd) && result < 0 &&
        (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) {
        errno = 0;
        return 0; /* FreeRDP's existing idle loop retries this read. */
    }
    return result;
}

void Sleep(unsigned int milliseconds) {
    if (keyboard_fd >= 0 && milliseconds == 5) { original_sleep(1); return; }
    if (keyboard_fd >= 0 && milliseconds == 100) { original_sleep(10); return; }
    original_sleep(milliseconds);
}
