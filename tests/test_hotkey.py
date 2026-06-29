"""Tests for the global hotkey module."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

import hotkey as hk


@pytest.fixture
def with_qapp(qapp):
    return qapp


def test_modifier_constants_distinct():
    assert len({hk.MOD_ALT, hk.MOD_CONTROL, hk.MOD_SHIFT, hk.MOD_WIN, hk.MOD_NOREPEAT}) == 5


def test_wm_hotkey_value():
    assert hk.WM_HOTKEY == 0x0312


def test_constructor_sets_flags_and_size(with_qapp):
    g = hk.GlobalHotkey(hk.MOD_CONTROL | hk.MOD_ALT, 0x56)
    assert g._modifiers & hk.MOD_NOREPEAT
    assert g._virtual_key == 0x56
    assert g.size().width() == 1
    assert g.size().height() == 1
    assert g.windowFlags() & hk.Qt.Tool


def test_start_returns_false_on_non_windows():
    g = hk.GlobalHotkey(0, 0x56)
    with patch.object(hk.sys, "platform", "linux"):
        assert g.start() is False
    assert g._registered is False


def test_start_succeeds_when_registerhotkey_returns_nonzero():
    g = hk.GlobalHotkey(0, 0x56)
    g.show()  # so winId() returns a real value
    user32 = MagicMock()
    user32.RegisterHotKey.return_value = 1
    kernel32 = MagicMock()
    with patch.object(hk.ctypes.windll, "user32", user32), \
         patch.object(hk.ctypes.windll, "kernel32", kernel32):
        ok = g.start()
    assert ok is True
    assert g._registered is True
    user32.RegisterHotKey.assert_called_once()


def test_start_records_last_error_on_failure():
    g = hk.GlobalHotkey(0, 0x56)
    g.show()
    user32 = MagicMock()
    user32.RegisterHotKey.return_value = 0
    kernel32 = MagicMock()
    kernel32.GetLastError.return_value = 1400  # ERROR_INVALID_WINDOW_HANDLE
    with patch.object(hk.ctypes.windll, "user32", user32), \
         patch.object(hk.ctypes.windll, "kernel32", kernel32):
        assert g.start() is False
    assert g._registered is False


def test_start_handles_exception():
    g = hk.GlobalHotkey(0, 0x56)
    g.show()
    user32 = MagicMock()
    user32.RegisterHotKey.side_effect = OSError("dll missing")
    with patch.object(hk.ctypes.windll, "user32", user32):
        assert g.start() is False


def test_start_is_idempotent():
    g = hk.GlobalHotkey(0, 0x56)
    g.show()
    user32 = MagicMock()
    user32.RegisterHotKey.return_value = 1
    with patch.object(hk.ctypes.windll, "user32", user32), \
         patch.object(hk.ctypes.windll, "kernel32", MagicMock()):
        assert g.start() is True
        user32.RegisterHotKey.reset_mock()
        assert g.start() is True
    # No new registration call on the second start.
    user32.RegisterHotKey.assert_not_called()


def test_stop_noop_when_not_registered():
    g = hk.GlobalHotkey(0, 0x56)
    g.stop()  # must not raise
    assert g._registered is False


def test_stop_calls_unregister(with_qapp):
    g = hk.GlobalHotkey(0, 0x56)
    g.show()
    user32 = MagicMock()
    user32.RegisterHotKey.return_value = 1
    with patch.object(hk.ctypes.windll, "user32", user32), \
         patch.object(hk.ctypes.windll, "kernel32", MagicMock()):
        g.start()
        user32.UnregisterHotKey = MagicMock()
        g.stop()
    user32.UnregisterHotKey.assert_called_once()
    assert g._registered is False


def test_stop_handles_unregister_exception():
    g = hk.GlobalHotkey(0, 0x56)
    g.show()
    user32 = MagicMock()
    user32.RegisterHotKey.return_value = 1
    user32.UnregisterHotKey = MagicMock(side_effect=Exception("x"))
    with patch.object(hk.ctypes.windll, "user32", user32), \
         patch.object(hk.ctypes.windll, "kernel32", MagicMock()):
        g.start()
        g.stop()  # must not propagate
    assert g._registered is False


def test_native_event_emits_activated_on_match(with_qapp):
    g = hk.GlobalHotkey(0, 0x56)
    g.show()
    emissions = []
    g.activated.connect(lambda: emissions.append(1))
    # Build a fake MSG
    import ctypes.wintypes
    msg = ctypes.wintypes.MSG()
    msg.message = hk.WM_HOTKEY
    msg.wParam = g._registered_id
    g._registered = True  # bypass the real registration
    addr = ctypes.addressof(msg)
    handled, ret = g.nativeEvent(b"windows_generic_MSG", addr)
    assert handled is True
    assert ret == 0
    assert emissions == [1]


def test_native_event_ignores_other_messages(with_qapp):
    g = hk.GlobalHotkey(0, 0x56)
    emissions = []
    g.activated.connect(lambda: emissions.append(1))
    import ctypes.wintypes
    msg = ctypes.wintypes.MSG()
    msg.message = 0x0001  # WM_CREATE, not WM_HOTKEY
    msg.wParam = 0
    handled, ret = g.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))
    assert handled is False
    assert emissions == []


def test_native_event_ignores_other_ids(with_qapp):
    g = hk.GlobalHotkey(0, 0x56)
    emissions = []
    g.activated.connect(lambda: emissions.append(1))
    import ctypes.wintypes
    msg = ctypes.wintypes.MSG()
    msg.message = hk.WM_HOTKEY
    msg.wParam = g._registered_id + 1  # different id
    handled, ret = g.nativeEvent(b"windows_generic_MSG", ctypes.addressof(msg))
    assert handled is False
    assert emissions == []


def test_hide_does_nothing(with_qapp):
    g = hk.GlobalHotkey(0, 0x56)
    assert g.hide() is None  # does not call super().hide()


def test_close_event_stops_hotkey(with_qapp):
    g = hk.GlobalHotkey(0, 0x56)
    g.show()
    user32 = MagicMock()
    user32.RegisterHotKey.return_value = 1
    user32.UnregisterHotKey = MagicMock()
    with patch.object(hk.ctypes.windll, "user32", user32), \
         patch.object(hk.ctypes.windll, "kernel32", MagicMock()):
        g.start()
        g.close()
    user32.UnregisterHotKey.assert_called_once()
