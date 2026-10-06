"""How many browser tabs Remotion renders with, from the cores, the free memory and the length.

Each tab is a Chrome renderer that holds decoded video frames; too many of them on a machine
short of memory swap or crash, which is slower than rendering with fewer. The count is

    min(cores - 2, 50 % of available RAM / per-browser budget, frames / 30, 8)

and never below 1. A `renderMaxConcurrency` setting above 0 replaces it (capped at the cores).
"""

import ctypes
import os
import sys
from pathlib import Path

PER_BROWSER_BUDGET_MB = 1536
MAX_CONCURRENCY = 8
RESERVED_CORES = 2
RAM_SHARE = 0.5
FRAMES_PER_WORKER = 30
"""A tab costs a page load and font loading; below this many frames it is not worth one."""

_MEMINFO = Path("/proc/meminfo")


def choose_concurrency(
    cpu_count: int,
    available_mb: int | None,
    frames: int,
    *,
    budget_mb: int = PER_BROWSER_BUDGET_MB,
    override: int = 0,
) -> int:
    """Render tabs for a `frames` long timeline; `available_mb` None means unknown."""
    cores = max(1, cpu_count)
    if override > 0:
        return min(override, cores)
    limits = [cores - RESERVED_CORES, frames // FRAMES_PER_WORKER, MAX_CONCURRENCY]
    if available_mb is not None:
        limits.append(int(available_mb * RAM_SHARE // budget_mb))
    return max(1, min(limits))


def parse_meminfo_available_mb(meminfo: str) -> int | None:
    """`MemAvailable` of a Linux `/proc/meminfo`, in MB."""
    for line in meminfo.splitlines():
        name, _, value = line.partition(":")
        if name == "MemAvailable":
            return int(value.split()[0]) // 1024
    return None


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def available_memory_mb() -> int | None:
    """Physical memory free for new processes, in MB; None where it cannot be read."""
    if sys.platform == "win32":
        status = _MemoryStatusEx()
        # The call fails unless the structure states its own size.
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.ullAvailPhys // (1024 * 1024))
    try:
        return parse_meminfo_available_mb(_MEMINFO.read_text(encoding="ascii"))
    except (OSError, ValueError):
        return None


def render_concurrency(frames: int, override: int = 0) -> int:
    """`choose_concurrency` for this machine, now."""
    return choose_concurrency(os.cpu_count() or 1, available_memory_mb(), frames, override=override)
