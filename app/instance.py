"""Instance unique : un seul ANTAI PV ouvert par session Windows.

Évite deux fenêtres sur la même base et, surtout, qu'une mise à jour remplace AntaiPV.exe pendant qu'une autre
copie est en train de démarrer (elle mélangerait alors deux versions et planterait).
"""
import ctypes
import os
from ctypes import wintypes

MUTEX_NAME = "Local\\AntaiPV-instance-unique"
WAIT_OBJECT_0, WAIT_ABANDONED = 0x0, 0x80
TITLE_PREFIX = "ANTAI PV"

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_u32 = ctypes.WinDLL("user32", use_last_error=True)
_k32.CreateMutexW.restype = wintypes.HANDLE
_k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.WaitForSingleObject.restype = wintypes.DWORD
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                            ctypes.POINTER(wintypes.DWORD)]

_handle = None  # gardé pendant toute la vie du processus


def acquire(wait_ms: int = 0) -> bool:
    """Prend le verrou d'instance unique (en attendant au plus `wait_ms`). False si une autre instance tourne."""
    global _handle
    h = _k32.CreateMutexW(None, False, MUTEX_NAME)
    if not h:
        return True  # en cas d'échec du système, ne pas bloquer le démarrage
    if _k32.WaitForSingleObject(h, wait_ms) in (WAIT_OBJECT_0, WAIT_ABANDONED):
        _handle = h
        return True
    _k32.CloseHandle(h)
    return False


def activate_existing() -> None:
    """Ramène au premier plan la fenêtre de l'instance déjà ouverte."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum(hwnd, _):
        n = _u32.GetWindowTextLengthW(hwnd)
        if n and _u32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(n + 1)
            _u32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.startswith(TITLE_PREFIX):
                found.append(hwnd)
                return False
        return True

    _u32.EnumWindows(enum, 0)
    if found:
        _u32.ShowWindow(found[0], 9)  # SW_RESTORE
        _u32.SetForegroundWindow(found[0])


def other_processes(exe_path: str, exclude: set[int]) -> list[int]:
    """PID des autres processus lancés depuis le même exécutable (y compris une copie en cours de démarrage)."""
    psapi = ctypes.WinDLL("psapi")
    arr = (wintypes.DWORD * 4096)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
        return []
    target = os.path.normcase(os.path.abspath(exe_path))
    out = []
    for pid in arr[:needed.value // ctypes.sizeof(wintypes.DWORD)]:
        if not pid or pid in exclude:
            continue
        h = _k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                if os.path.normcase(buf.value) == target:
                    out.append(pid)
        finally:
            _k32.CloseHandle(h)
    return out
