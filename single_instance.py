"""Single-instance enforcement and cross-process wake-up for Windows.

The first instance acquires a named mutex (single-instance guard) and
starts a named-pipe server that listens for wake-up messages from
subsequent launches. A second instance fails to acquire the mutex, sends
a ``show`` message to the pipe of the running instance, and exits; the
running instance reacts by bringing its floating ball back on screen.

On non-Windows platforms the mutex acquisition always succeeds and the
pipe server/notify are no-ops, so the module is safe to import anywhere.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from ctypes import wintypes
from typing import Callable, Optional

import config

LOGGER = logging.getLogger(__name__)

_SHOW_MESSAGE = b"show"

# Win32 pipe / file constants.
_PIPE_ACCESS_INBOUND = 0x00000001
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_WAIT = 0x00000000
_NMPWAIT_USE_DEFAULT_WAIT = 0x00000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value  # 0xFFFFFFFF


def _is_windows() -> bool:
    return sys.platform == "win32"


def acquire_mutex(name: str) -> bool:
    """Try to acquire the named mutex for single-instance enforcement.

    Returns True if this is the only running instance, False if another
    instance already holds the mutex. The mutex handle is stored on the
    :mod:`config` module (``config._SINGLE_INSTANCE_HANDLE``) to keep it
    alive for the process lifetime. On non-Windows platforms always
    returns True.
    """
    if not _is_windows():
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        ERROR_ALREADY_EXISTS = 183
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.GetLastError.argtypes = []
        kernel32.GetLastError.restype = wintypes.DWORD
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            LOGGER.warning("CreateMutexW returned NULL; proceeding without single-instance guard")
            return True
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        config._SINGLE_INSTANCE_HANDLE = handle  # type: ignore[attr-defined]
        return True
    except Exception:
        LOGGER.exception("Single-instance mutex acquisition failed; proceeding without guard")
        return True


class PipeServer:
    """Daemon-thread named-pipe server that calls a callback on wake-up.

    Listens on a named pipe; when a client writes the wake-up message the
    ``on_show`` callback is invoked (from the server thread). Qt signal
    ``emit`` is thread-safe and queued to the receiver's thread, so
    passing ``ball.show_requested.emit`` is safe. On non-Windows the
    server is a no-op.
    """

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._pipe_handle: int = 0
        self._pipe_name: Optional[str] = None

    def start(self, pipe_name: str, on_show: Callable[[], None]) -> bool:
        """Start the server thread. Returns False on non-Windows or if
        the pipe cannot be created (logged, non-fatal)."""
        if not _is_windows():
            LOGGER.info("Named-pipe server is Windows-only; ignoring")
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._pipe_name = pipe_name
        self._running = True
        self._thread = threading.Thread(
            target=self._serve, args=(pipe_name, on_show),
            name="VolumeMixerPipeServer", daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Signal the server thread to stop.

        A blocking ``ConnectNamedPipe`` cannot be interrupted by closing
        the handle from another thread (undefined behaviour).  Instead we
        connect to the pipe as a client, which unblocks the call cleanly;
        the server thread then closes its own handle and exits.
        """
        self._running = False
        pipe_name = self._pipe_name
        if pipe_name and _is_windows():
            try:
                kernel32 = ctypes.windll.kernel32
                kernel32.CreateFileW.argtypes = [
                    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                    wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
                ]
                kernel32.CreateFileW.restype = wintypes.HANDLE
                kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel32.CloseHandle.restype = wintypes.BOOL
                client = kernel32.CreateFileW(
                    pipe_name, _GENERIC_WRITE, 0, None, _OPEN_EXISTING, 0, None,
                )
                if client != _INVALID_HANDLE_VALUE and client != 0:
                    kernel32.CloseHandle(client)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _serve(self, pipe_name: str, on_show: Callable[[], None]) -> None:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateNamedPipeW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        ]
        kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
        kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        kernel32.ConnectNamedPipe.restype = wintypes.BOOL
        kernel32.ReadFile.argtypes = [
            wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
        ]
        kernel32.ReadFile.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        buf = ctypes.create_string_buffer(64)
        while self._running:
            handle = kernel32.CreateNamedPipeW(
                pipe_name,
                _PIPE_ACCESS_INBOUND,
                _PIPE_TYPE_BYTE | _PIPE_WAIT,
                1, 0, 0, _NMPWAIT_USE_DEFAULT_WAIT, None,
            )
            if handle == _INVALID_HANDLE_VALUE or handle == 0:
                err = kernel32.GetLastError()
                LOGGER.warning("CreateNamedPipeW failed (GetLastError=%d); retrying in 1s", err)
                if self._running:
                    threading.Event().wait(1.0)
                continue
            self._pipe_handle = handle

            connected = kernel32.ConnectNamedPipe(handle, None)
            if not connected:
                err = kernel32.GetLastError()
                # ERROR_PIPE_CONNECTED (535): a client connected between
                # CreateNamedPipe and ConnectNamedPipe — treat as success.
                if err != 535:
                    if not self._running:
                        kernel32.CloseHandle(handle)
                        self._pipe_handle = 0
                        break
                    LOGGER.warning("ConnectNamedPipe failed (GetLastError=%d)", err)
                    kernel32.CloseHandle(handle)
                    self._pipe_handle = 0
                    continue

            bytes_read = wintypes.DWORD(0)
            ok = kernel32.ReadFile(handle, buf, ctypes.sizeof(buf), ctypes.byref(bytes_read), None)
            kernel32.CloseHandle(handle)
            self._pipe_handle = 0

            if not ok:
                # Client connected without writing (e.g. stop() unblock).
                continue
            data = bytes(buf.raw[:bytes_read.value])
            if _SHOW_MESSAGE in data:
                try:
                    on_show()
                except Exception:
                    LOGGER.exception("on_show callback raised")


def notify_running_instance(pipe_name: str) -> bool:
    """Send a wake-up message to the running instance's pipe server.

    Returns True on success, False if the pipe is unavailable or the
    write fails (no running instance or it is not listening). On
    non-Windows always returns False.
    """
    if not _is_windows():
        return False
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.WriteFile.argtypes = [
            wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
        ]
        kernel32.WriteFile.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateFileW(
            pipe_name, _GENERIC_WRITE, 0, None, _OPEN_EXISTING, 0, None,
        )
        if handle == _INVALID_HANDLE_VALUE or handle == 0:
            return False
        try:
            written = wintypes.DWORD(0)
            msg = _SHOW_MESSAGE
            ok = kernel32.WriteFile(handle, msg, len(msg), ctypes.byref(written), None)
            return bool(ok)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        LOGGER.exception("notify_running_instance failed")
        return False
