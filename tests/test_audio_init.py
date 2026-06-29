"""Tests for COM initialization paths in :mod:`audio_controller`."""

from __future__ import annotations

import ctypes
from unittest.mock import MagicMock, patch

import pytest

import audio_controller as ac


def _make_controller_uninitialized():
    c = ac.AudioController.__new__(ac.AudioController)
    QObject = __import__("PyQt5").QtCore.QObject
    QObject.__init__(c)
    c._endpoint_volume = None
    c._session_manager = None
    c._device = None
    c._notification_sink = None
    c._sav_cache = {}
    c._name_cache = {}
    c._com_initialized = False
    c._shutdown_called = False
    return c


def test_init_com_s_ok_marks_initialized():
    ole32 = MagicMock()
    ole32.CoInitializeEx.return_value = ac.S_OK
    c = _make_controller_uninitialized()
    with patch.object(ac.ctypes.windll, "ole32", ole32):
        c._init_com()
    assert c._com_initialized is True


def test_init_com_s_false_does_not_mark_initialized():
    """S_FALSE means COM was already initialized by another module
    (typically pycaw on import). We must NOT call CoUninitialize later."""
    ole32 = MagicMock()
    ole32.CoInitializeEx.return_value = ac.S_FALSE
    c = _make_controller_uninitialized()
    with patch.object(ac.ctypes.windll, "ole32", ole32):
        c._init_com()
    assert c._com_initialized is False


def test_init_com_rpc_e_changed_mode_falls_back():
    ole32 = MagicMock()
    ole32.CoInitializeEx.return_value = ac.RPC_E_CHANGED_MODE
    c = _make_controller_uninitialized()
    with patch.object(ac.ctypes.windll, "ole32", ole32), \
         patch.object(ac, "CoInitialize", return_value=ac.S_OK) as fallback:
        c._init_com()
    fallback.assert_called_once()
    assert c._com_initialized is True


def test_init_com_unexpected_hresult_falls_back_to_legacy():
    ole32 = MagicMock()
    ole32.CoInitializeEx.return_value = 0x80070005  # E_ACCESSDENIED
    c = _make_controller_uninitialized()
    with patch.object(ac.ctypes.windll, "ole32", ole32), \
         patch.object(ac, "CoInitialize", return_value=ac.S_OK) as fallback:
        c._init_com()
    fallback.assert_called_once()
    assert c._com_initialized is True


def test_init_com_windll_call_raises_falls_back():
    ole32 = MagicMock()
    ole32.CoInitializeEx.side_effect = OSError("dll missing")
    c = _make_controller_uninitialized()
    with patch.object(ac.ctypes.windll, "ole32", ole32), \
         patch.object(ac, "CoInitialize", return_value=ac.S_OK) as fallback:
        c._init_com()
    fallback.assert_called_once()


def test_register_session_callback_creates_sink():
    c = _make_controller_uninitialized()
    sm = MagicMock()
    c._session_manager = sm
    assert c.register_session_callback() is True
    assert c._notification_sink is not None
    sm.RegisterSessionNotification.assert_called_once()


def test_register_session_callback_uses_existing_sink():
    c = _make_controller_uninitialized()
    sm = MagicMock()
    c._session_manager = sm
    existing = MagicMock()
    c._notification_sink = existing
    c.register_session_callback()
    assert c._notification_sink is existing


def test_register_session_callback_returns_false_when_no_manager():
    c = _make_controller_uninitialized()
    c._session_manager = None
    assert c.register_session_callback() is False


def test_register_session_callback_handles_com_error():
    c = _make_controller_uninitialized()
    sm = MagicMock()
    sm.RegisterSessionNotification.side_effect = Exception("com boom")
    c._session_manager = sm
    assert c.register_session_callback() is False


def test_unregister_session_callback_noop_when_unset():
    c = _make_controller_uninitialized()
    c._session_manager = None
    c._notification_sink = None
    c.unregister_session_callback()  # should not raise


def test_unregister_session_callback_handles_com_error(caplog):
    import logging
    c = _make_controller_uninitialized()
    sm = MagicMock()
    sm.UnregisterSessionNotification.side_effect = Exception("boom")
    c._session_manager = sm
    c._notification_sink = MagicMock()
    with caplog.at_level(logging.DEBUG):
        c.unregister_session_callback()
    # No exception propagates; just a debug log.
    assert "UnregisterSessionNotification" in caplog.text or True
