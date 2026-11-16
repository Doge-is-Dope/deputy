"""Run a command confined to its conversation's folder: it may read and run the system, and read and write only that
folder (Landlock). Where the kernel has Landlock ABI 6 (Linux 6.12), it may also signal only its own processes.

Usage: python3 sandbox.py FOLDER COMMAND [ARG ...]. A kernel without Landlock refuses the command rather than run it
unconfined."""

import ctypes
import os
import struct
import sys

CREATE, ADD, RESTRICT = 444, 445, 446  # the Landlock syscalls, numbered alike on every architecture
VERSION = 1  # landlock_create_ruleset flag: ask for the ABI version
PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38
EXECUTE, WRITE_FILE, READ_FILE, READ_DIR = 1 << 0, 1 << 1, 1 << 2, 1 << 3
SCOPE_ABSTRACT_UNIX_SOCKET, SCOPE_SIGNAL = 1 << 0, 1 << 1
# What the system lends a command: its programs and libraries, settings, process information, and devices such as
# /dev/null. Everything else, other conversations' folders and the runner's socket among them, stays out of reach.
SYSTEM = {"/usr": EXECUTE | READ_FILE | READ_DIR, "/etc": READ_FILE | READ_DIR, "/proc": READ_FILE | READ_DIR,
          "/dev": READ_FILE | WRITE_FILE | READ_DIR}

libc = ctypes.CDLL(None, use_errno=True)


def call(number: int, *args) -> int:
    result = libc.syscall(number, *args)
    if result < 0:
        raise OSError(ctypes.get_errno(), f"landlock: {os.strerror(ctypes.get_errno())}")
    return result


def handled(abi: int) -> int:
    """Every filesystem right this ABI knows: 13 from the first, then REFER (2), TRUNCATE (3) and IOCTL_DEV (5)."""
    return (1 << (13 + (abi >= 2) + (abi >= 3) + (abi >= 5))) - 1


def confine(folder: str) -> None:
    abi = call(CREATE, None, 0, VERSION)
    rights = handled(abi)
    attr = struct.pack("QQQ", rights, 0, SCOPE_ABSTRACT_UNIX_SOCKET | SCOPE_SIGNAL) if abi >= 6 else struct.pack("Q", rights)
    ruleset = call(CREATE, ctypes.c_char_p(attr), len(attr), 0)
    for path, allowed in [*SYSTEM.items(), (folder, rights)]:
        parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
        try:
            call(ADD, ruleset, PATH_BENEATH, ctypes.c_char_p(struct.pack("=Qi", allowed & rights, parent)), 0)
        finally:
            os.close(parent)
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "no_new_privs")
    call(RESTRICT, ruleset, 0)
    os.close(ruleset)


if __name__ == "__main__":
    folder, *command = sys.argv[1:]
    confine(folder)
    os.execvp(command[0], command)
