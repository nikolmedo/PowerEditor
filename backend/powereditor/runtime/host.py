"""The machine's real CPU architecture.

An x64 process emulated on Windows ARM64 (the packaged app) sees an x64 machine through
most APIs; `IsWow64Process2` reports the native machine either way.
"""

import platform
import sys
from collections.abc import Callable
from functools import cache

NATIVE_MACHINES = {0xAA64: "arm64", 0x8664: "x64"}
"""`IMAGE_FILE_MACHINE_*` values of the architectures with runtime downloads."""
_ARCH_NAMES = {"amd64": "x64", "x86_64": "x64", "x64": "x64", "arm64": "arm64", "aarch64": "arm64"}

NativeMachine = Callable[[], int | None]


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    def native_machine() -> int | None:
        """The native `IMAGE_FILE_MACHINE_*` value, or None before Windows 10 1709."""
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        query = getattr(kernel32, "IsWow64Process2", None)
        if query is None:
            return None
        query.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.USHORT),
            ctypes.POINTER(wintypes.USHORT),
        ]
        query.restype = wintypes.BOOL
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        process_machine, native = wintypes.USHORT(), wintypes.USHORT()
        if not query(
            kernel32.GetCurrentProcess(), ctypes.byref(process_machine), ctypes.byref(native)
        ):
            return None
        return int(native.value)

else:

    def native_machine() -> int | None:
        return None


def detect_host_arch(
    native: NativeMachine = native_machine, machine: Callable[[], str] = platform.machine
) -> str:
    """`arm64`, `x64` or the lowercased machine name for anything else."""
    code = native()
    if code is not None and code in NATIVE_MACHINES:
        return NATIVE_MACHINES[code]
    reported = machine().lower()
    return _ARCH_NAMES.get(reported, reported)


@cache
def host_arch() -> str:
    return detect_host_arch()
