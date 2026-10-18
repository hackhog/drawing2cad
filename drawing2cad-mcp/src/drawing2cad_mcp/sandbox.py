"""Linux worker restrictions. Refuse execution when a required mechanism is absent."""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
from pathlib import Path
import platform
import sys


WORKER_TASKS = 64


class SandboxError(RuntimeError):
    """A required worker restriction could not be applied."""


def user_task_count(proc: Path = Path("/proc")) -> int:
    """Count the tasks (processes and threads) of the real user ID, as RLIMIT_NPROC counts them."""
    uid = str(os.getuid())
    count = 0
    for entry in os.scandir(proc):
        if not entry.name.isdigit():
            continue
        try:
            with open(os.path.join(entry.path, "status"), encoding="ascii", errors="replace") as stream:
                fields = dict(line.split(":", 1) for line in stream if ":" in line)
        except OSError:
            continue  # The process ended.
        if fields.get("Uid", "").split()[:1] == [uid]:
            count += int(fields.get("Threads", "1").strip() or 1)
    return count


def task_limit(concurrent_workers: int = 1) -> int:
    """Return the RLIMIT_NPROC value that permits WORKER_TASKS more tasks for each concurrent worker.

    RLIMIT_NPROC applies to all tasks of the real user ID, including the threads of the service and of
    the other workers. A fixed value lets a busy service prevent thread creation in its workers.
    The margin is WORKER_TASKS multiplied by the number of workers that can run at the same time.
    The user task count at the start of this worker includes the tasks of the workers that run now.
    If each worker uses at most WORKER_TASKS tasks, the other workers cannot use the margin of this
    worker. One worker can add at most the complete margin.
    In a PID namespace, /proc does not show tasks of the same user ID in other namespaces, so the
    margin can be smaller than calculated.
    """
    import resource

    if type(concurrent_workers) is not int or concurrent_workers < 1:
        raise SandboxError("The number of concurrent workers must be a positive integer.")
    _, hard = resource.getrlimit(resource.RLIMIT_NPROC)
    try:
        tasks = user_task_count()
    except (OSError, ValueError) as error:
        raise SandboxError("Cannot count the tasks of the worker user in /proc.") from error
    limit = tasks + WORKER_TASKS * concurrent_workers
    if hard != resource.RLIM_INFINITY and hard < limit:
        # A smaller margin lets the CAD kernel hang at thread creation until the wall-clock limit.
        raise SandboxError(
            f"The hard RLIMIT_NPROC limit {hard} is too small: the worker user has {tasks} tasks, and "
            f"{concurrent_workers} concurrent workers need {WORKER_TASKS * concurrent_workers} more. "
            "Increase the hard process limit of the service user or decrease cad.concurrency.")
    return limit


def available() -> dict:
    """Inspect mechanisms without weakening the current process."""
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "aarch64"}:
        return {"available": False, "reason": "CAD workers require Linux x86_64 or aarch64 with Landlock ABI 3 and libseccomp."}
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, 0, 0, 1)
    library = ctypes.util.find_library("seccomp")
    return {"available": abi >= 3 and bool(library), "landlock_abi": abi,
            "seccomp_library": library, "profile": "linux-landlock-seccomp-v1",
            "reason": None if abi >= 3 and library else "Landlock ABI 3 or libseccomp is unavailable."}


def restrict(work_dir: Path, *, memory_mb: int, cpu_seconds: int, concurrent_workers: int = 1) -> dict:
    """Restrict only a disposable worker, before importing the CAD kernel."""
    capability = available()
    if not capability["available"]:
        raise SandboxError(capability["reason"])
    import resource

    work_dir = work_dir.resolve(strict=True)
    os.chdir(work_dir)
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    limit = task_limit(concurrent_workers)
    resource.setrlimit(resource.RLIMIT_NPROC, (limit, limit))

    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise SandboxError("Cannot set no_new_privs.")

    class Ruleset(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class PathRule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int)]

    # ABI 3 handles all filesystem access bits through TRUNCATE.
    handled = (1 << 15) - 1
    read_directory = (1 << 0) | (1 << 2) | (1 << 3)
    read_file = (1 << 0) | (1 << 2)
    writable = read_directory | (1 << 1) | (1 << 4) | (1 << 5) | (1 << 7) | (1 << 8) | (1 << 12) | (1 << 13) | (1 << 14)
    attributes = Ruleset(handled)
    ruleset = libc.syscall(444, ctypes.byref(attributes), ctypes.sizeof(attributes), 0)
    if ruleset < 0:
        raise SandboxError(f"Cannot create Landlock ruleset: errno {ctypes.get_errno()}.")
    try:
        runtime = {Path("/usr"), Path("/lib"), Path("/lib64"), Path(sys.prefix),
                   Path(__file__).resolve().parent, Path("/etc/ld.so.cache"),
                   Path("/etc/localtime"), Path("/etc/fonts"), Path("/dev/urandom")}
        paths = {p.resolve(): read_directory if p.is_dir() else read_file for p in runtime if p.exists()}
        paths[work_dir] = writable
        for path, access in paths.items():
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(access, fd)
                if libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0) != 0:
                    raise SandboxError(f"Cannot add Landlock path: {path}; errno {ctypes.get_errno()}.")
            finally:
                os.close(fd)
        if libc.syscall(446, ruleset, 0) != 0:
            raise SandboxError(f"Cannot enforce Landlock: errno {ctypes.get_errno()}.")
    finally:
        os.close(ruleset)

    seccomp = ctypes.CDLL(capability["seccomp_library"], use_errno=True)
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int
    seccomp.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    context = seccomp.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise SandboxError("Cannot create seccomp filter.")
    denied = (
        "socket", "socketpair", "connect", "bind", "listen", "accept", "accept4",
        "sendto", "sendmsg", "sendmmsg", "recvfrom", "recvmsg", "recvmmsg",
        "ptrace", "process_vm_readv", "process_vm_writev", "pidfd_getfd", "pidfd_send_signal",
        "kill", "tkill", "tgkill", "prlimit64", "setrlimit", "bpf", "perf_event_open",
        "mount", "umount2", "pivot_root", "setns", "unshare", "reboot", "kexec_load",
        "chmod", "fchmod", "fchmodat", "fchmodat2", "chown", "fchown", "lchown", "fchownat",
        "setxattr", "lsetxattr", "fsetxattr", "removexattr", "lremovexattr", "fremovexattr",
        "utime", "utimes", "futimesat", "utimensat", "io_uring_setup", "io_uring_enter", "io_uring_register",
        "fork", "vfork", "setsid", "setpgid",
    )
    try:
        for name in denied:
            number = seccomp.seccomp_syscall_resolve_name(name.encode("ascii"))
            if number >= 0 and seccomp.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0) != 0:
                raise SandboxError("Cannot deny system call: " + name)
        # clone3 has an indirect flag pointer. Return ENOSYS so libc can use
        # clone for threads. Reject clone calls without CLONE_THREAD.
        clone3 = seccomp.seccomp_syscall_resolve_name(b"clone3")
        if clone3 >= 0 and seccomp.seccomp_rule_add(context, 0x00050000 | errno.ENOSYS, clone3, 0) != 0:
            raise SandboxError("Cannot deny clone3.")
        class ArgCompare(ctypes.Structure):
            _fields_ = [("arg", ctypes.c_uint), ("op", ctypes.c_int),
                        ("datum_a", ctypes.c_uint64), ("datum_b", ctypes.c_uint64)]
        seccomp.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                                 ctypes.c_uint, ctypes.POINTER(ArgCompare)]
        clone = seccomp.seccomp_syscall_resolve_name(b"clone")
        comparison = ArgCompare(0, 7, 0x00010000, 0)  # SCMP_CMP_MASKED_EQ
        if clone >= 0 and seccomp.seccomp_rule_add_array(context, 0x00050000 | errno.EPERM, clone, 1, ctypes.byref(comparison)) != 0:
            raise SandboxError("Cannot restrict clone to threads.")
        if seccomp.seccomp_load(context) != 0:
            raise SandboxError("Cannot enforce seccomp filter.")
    finally:
        seccomp.seccomp_release(context)
    return {**capability, "filesystem": "runtime_read_only_job_directory_read_write",
            "network": "socket_syscalls_denied", "process_creation": "threads_only",
            "memory_mb": memory_mb, "cpu_seconds": cpu_seconds}
