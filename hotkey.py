"""Global hotkey registration for Windows.

Uses the Win32 ``RegisterHotKey`` API on a hidden QWidget. On non-Windows
platforms the class is a no-op stub that never fires.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Optional

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtWidgets import QWidget

LOGGER = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000


class GlobalHotkey(QWidget):
    """Hidden widget that registers a system-wide hotkey and emits a signal.

    The widget is sized to 1x1 and never shown; it exists only to receive
    ``WM_HOTKEY`` messages delivered to its HWND by the OS.
    """

    activated = pyqtSignal()

    def __init__(self, modifiers: int, virtual_key: int,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._modifiers = int(modifiers) | MOD_NOREPEAT
        self._virtual_key = int(virtual_key)
        self._registered_id = 0x9C5A  # arbitrary stable id
        self._registered = False
        self.setWindowFlags(Qt.Tool)
        self.setFixedSize(QSize(1, 1))

    def start(self) -> bool:
        if not sys.platform.startswith("win"):
            LOGGER.info("Global hotkey is Windows-only; ignoring on %s", sys.platform)
            return False
        if self._registered:
            return True
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        try:
            ok = user32.RegisterHotKey(
                int(self.winId()),
                self._registered_id,
                self._modifiers,
                self._virtual_key,
            )
        except Exception:
            LOGGER.exception("RegisterHotKey raised")
            return False
        if not ok:
            err = kernel32.GetLastError()
            LOGGER.warning("RegisterHotKey returned 0 (GetLastError=%d)", err)
            return False
        self._registered = True
        LOGGER.info("Registered hotkey mod=0x%X vk=0x%X",
                    self._modifiers, self._virtual_key)
        return True

    def stop(self) -> None:
        if not self._registered:
            return
        try:
            ctypes.windll.user32.UnregisterHotKey(
                int(self.winId()),
                self._registered_id,
            )
        except Exception:
            LOGGER.exception("UnregisterHotKey raised")
        self._registered = False

    def nativeEvent(self, eventType, message):
        try:
            if eventType in (b"windows_generic_MSG", "windows_generic_MSG"):
                import ctypes.wintypes
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == self._registered_id:
                    self.activated.emit()
                    return True, 0
        except Exception:
            LOGGER.exception("nativeEvent handling failed")
        return super().nativeEvent(eventType, message)

    def hide(self) -> None:
        # Never visible; suppress accidental show().
        return None

    def closeEvent(self, event) -> None:
        self.stop()
        super().closeEvent(event)
