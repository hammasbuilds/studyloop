"""Measure the peak memory growth of a callable, in MB, with a sampling thread."""

import ctypes
import os
import threading
import time
from ctypes import wintypes


def _rss_mb() -> float:
    if os.name != "nt":
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6

    class PMC(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize / 1e6


def run_and_measure(fn) -> float:
    base, peak, stop = _rss_mb(), [0.0], threading.Event()

    def sample():
        while not stop.is_set():
            peak[0] = max(peak[0], _rss_mb())
            time.sleep(0.02)

    t = threading.Thread(target=sample, daemon=True)
    t.start()
    try:
        fn()
    finally:
        stop.set()
        t.join()
    return max(0.0, peak[0] - base)
