"""Tests for :mod:`audio_controller` helpers that require richer mocks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import audio_controller as ac
import config


# ---- SessionNotificationSink ------------------------------------------------

def test_session_notification_sink_emits_via_qtimer():
    """The COM callback must hand off to the Qt main thread via QTimer."""
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QTimer

    app = QApplication.instance() or QApplication([])

    ctl = MagicMock()
    ctl._on_session_created_sta = MagicMock()
    sink = ac.SessionNotificationSink(ctl)

    single_shot_calls = []
    original_single_shot = QTimer.singleShot
    QTimer.singleShot = staticmethod(lambda *a, **kw: single_shot_calls.append((a, kw)))
    try:
        sink.IAudioSessionNotification_OnSessionCreated(None, None)
    finally:
        QTimer.singleShot = original_single_shot

    assert len(single_shot_calls) == 1
    assert single_shot_calls[0][0][0] == 0
    assert single_shot_calls[0][0][1] == ctl._on_session_created_sta
    # Direct call should not have been made
    ctl._on_session_created_sta.assert_not_called()


def test_session_notification_sink_logs_on_dispatch_failure():
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QTimer

    QApplication.instance() or QApplication([])

    ctl = MagicMock()
    sink = ac.SessionNotificationSink(ctl)
    # Make singleShot itself raise to force the except branch
    with patch.object(QTimer, "singleShot", side_effect=Exception("boom")):
        result = sink.IAudioSessionNotification_OnSessionCreated(None, None)
    assert result == 0


def test_session_notification_sink_handles_no_controller():
    """A sink constructed with None controller must not crash."""
    sink = ac.SessionNotificationSink(None)
    # Should not raise
    assert sink.IAudioSessionNotification_OnSessionCreated(None, None) == 0


# ---- _resolve_indirect_string ---------------------------------------------

def test_resolve_indirect_string_at_prefix():
    """Strings starting with @ go through SHLoadIndirectString."""
    with patch.object(ac.shlwapi, "SHLoadIndirectString",
                      return_value=0) as sli:
        sli.return_value = 0  # success
        # The function uses create_unicode_buffer; stub it to bypass
        with patch("ctypes.create_unicode_buffer",
                   return_value=MagicMock(value="decoded")):
            result = ac._resolve_indirect_string("@dll,-1")
    # When SHLoadIndirectString returns 0, the function uses the buffer value
    assert result == "decoded"


def test_resolve_indirect_string_at_prefix_failure_returns_input():
    """When SHLoadIndirectString fails, the original string is returned."""
    with patch.object(ac.shlwapi, "SHLoadIndirectString", return_value=1):
        # non-zero return code means failure
        with patch("ctypes.create_unicode_buffer",
                   return_value=MagicMock(value="")):
            result = ac._resolve_indirect_string("@dll,-1")
    assert result == "@dll,-1"


def test_resolve_indirect_string_handles_oserror():
    with patch.object(ac.shlwapi, "SHLoadIndirectString",
                      side_effect=OSError("dll")):
        result = ac._resolve_indirect_string("@dll,-1")
    assert result == "@dll,-1"


# ---- get_all_sessions with system session --------------------------------

def test_get_all_sessions_system_session_friendly_name_fallback():
    """When SHLoadIndirectString returns empty, the system name is used."""
    c = ac.AudioController.__new__(ac.AudioController)
    __import__("PyQt5").QtCore.QObject.__init__(c)
    c._sav_cache = {}
    c._name_cache = {}
    c._endpoint_volume = None
    c._session_manager = None

    sys_sess = MagicMock()
    sys_sess.State = 0
    sys_sess.ProcessId = 0
    sys_sess._ctl.IsSystemSoundsSession.return_value = 0
    sys_sess.DisplayName = "@dll,-202"  # indirect, but resolution yields empty
    sys_sess.SimpleAudioVolume = MagicMock()
    sys_sess.SimpleAudioVolume.GetMasterVolume.return_value = 0.5
    sys_sess.SimpleAudioVolume.GetMute.return_value = False

    with patch.object(ac.AudioUtilities, "GetAllSessions",
                      return_value=[sys_sess]), \
         patch.object(ac, "_resolve_indirect_string", return_value=""):
        sessions = c.get_all_sessions()
    # The system name should fall back to i18n.SYSTEM_SOUNDS_NAME
    assert sessions[0]["display_name"] == ac.i18n.SYSTEM_SOUNDS_NAME


def test_get_all_sessions_handles_session_state_access_failure():
    """If accessing State throws, the session is skipped."""
    c = ac.AudioController.__new__(ac.AudioController)
    __import__("PyQt5").QtCore.QObject.__init__(c)
    c._sav_cache = {}
    c._name_cache = {}
    c._endpoint_volume = None
    c._session_manager = None

    bad = MagicMock()
    type(bad).State = property(lambda self: (_ for _ in ()).throw(ac.comtypes.COMError("boom")))

    good = MagicMock()
    good.State = 0
    good.ProcessId = 1
    good._ctl.IsSystemSoundsSession.return_value = 1
    good.SimpleAudioVolume = MagicMock()
    good.SimpleAudioVolume.GetMasterVolume.return_value = 0.5
    good.SimpleAudioVolume.GetMute.return_value = False
    good.DisplayName = ""
    good.Process = MagicMock()
    good.Process.name.return_value = "x.exe"
    good.Process.exe.return_value = ""

    with patch.object(ac.AudioUtilities, "GetAllSessions",
                      return_value=[bad, good]):
        sessions = c.get_all_sessions()
    # bad is skipped, good is included
    assert len(sessions) == 1
    assert sessions[0]["pid"] == 1


def test_get_all_sessions_handles_volume_read_failure():
    """A session that throws on GetMasterVolume gets volume=None."""
    c = ac.AudioController.__new__(ac.AudioController)
    __import__("PyQt5").QtCore.QObject.__init__(c)
    c._sav_cache = {}
    c._name_cache = {}
    c._endpoint_volume = None
    c._session_manager = None

    s = MagicMock()
    s.State = 0
    s.ProcessId = 1
    s._ctl.IsSystemSoundsSession.return_value = 1
    s.SimpleAudioVolume = MagicMock()
    s.SimpleAudioVolume.GetMasterVolume.side_effect = ac.comtypes.COMError(0x80070005, 1, 0)
    s.SimpleAudioVolume.GetMute.return_value = False
    s.DisplayName = ""
    s.Process = MagicMock()
    s.Process.name.return_value = "x.exe"
    s.Process.exe.return_value = ""

    with patch.object(ac.AudioUtilities, "GetAllSessions", return_value=[s]):
        sessions = c.get_all_sessions()
    assert sessions[0]["volume"] is None
    assert sessions[0]["mute"] is False


# ---- get_master_volume / get_master_mute -------------------------------

def test_get_master_mute_invalidates_endpoint_on_com_error():
    c = ac.AudioController.__new__(ac.AudioController)
    __import__("PyQt5").QtCore.QObject.__init__(c)
    c._sav_cache = {}
    c._name_cache = {}
    c._endpoint_volume = MagicMock()
    c._endpoint_volume.GetMute.side_effect = Exception("boom")
    c._device = MagicMock()
    c._session_manager = None
    result = c.get_master_mute()
    assert result is None
    assert c._endpoint_volume is None


def test_set_master_mute_invalidates_endpoint_on_com_error():
    c = ac.AudioController.__new__(ac.AudioController)
    __import__("PyQt5").QtCore.QObject.__init__(c)
    c._sav_cache = {}
    c._name_cache = {}
    c._endpoint_volume = MagicMock()
    c._endpoint_volume.SetMute.side_effect = ac.comtypes.COMError(0x80070005, 1, 0)
    c._device = MagicMock()
    c._session_manager = None
    result = c.set_master_mute(True)
    assert result is False
    assert c._endpoint_volume is None


def test_set_mute_by_key_dispatches_to_correct_branch():
    c = ac.AudioController.__new__(ac.AudioController)
    __import__("PyQt5").QtCore.QObject.__init__(c)
    c._sav_cache = {"system": MagicMock(), 1: MagicMock()}
    c._name_cache = {}
    c._endpoint_volume = MagicMock()
    c._device = MagicMock()
    c._session_manager = None
    assert c.set_mute_by_key("master", True) is True
    assert c.set_mute_by_key("system", True) is True
    assert c.set_mute_by_key(1, True) is True
    assert c.set_mute_by_key("not-a-key", True) is False


# ---- _get_sav_for_key fallback path --------------------------------------

def test_get_sav_for_key_falls_back_to_fresh_enumeration():
    """When the cache is empty, _get_sav_for_key enumerates sessions."""
    c = ac.AudioController.__new__(ac.AudioController)
    __import__("PyQt5").QtCore.QObject.__init__(c)
    c._sav_cache = {}
    c._name_cache = {}
    c._endpoint_volume = None
    c._session_manager = None

    s = MagicMock()
    s.State = 0
    s.ProcessId = 42
    s._ctl.IsSystemSoundsSession.return_value = 1
    sav = MagicMock()
    s.SimpleAudioVolume = sav

    with patch.object(ac.AudioUtilities, "GetAllSessions", return_value=[s]):
        result = c._get_sav_for_key(42)
    assert result is sav
    # And it was cached
    assert c._get_sav_for_key(42) is sav


def test_get_sav_for_key_handles_enumeration_failure():
    c = ac.AudioController.__new__(ac.AudioController)
    __import__("PyQt5").QtCore.QObject.__init__(c)
    c._sav_cache = {}
    c._name_cache = {}
    c._endpoint_volume = None
    c._session_manager = None
    with patch.object(ac.AudioUtilities, "GetAllSessions",
                      side_effect=Exception("boom")):
        assert c._get_sav_for_key(42) is None


def test_get_sav_for_key_handles_com_error_on_enumeration():
    c = ac.AudioController.__new__(ac.AudioController)
    __import__("PyQt5").QtCore.QObject.__init__(c)
    c._sav_cache = {}
    c._name_cache = {}
    c._endpoint_volume = None
    c._session_manager = None
    with patch.object(ac.AudioUtilities, "GetAllSessions",
                      side_effect=ac.comtypes.COMError(0x80070005, 1, 0)):
        assert c._get_sav_for_key(42) is None


def test_get_sav_for_key_cache_miss_during_iteration_failure():
    c = ac.AudioController.__new__(ac.AudioController)
    __import__("PyQt5").QtCore.QObject.__init__(c)
    c._sav_cache = {}
    c._name_cache = {}
    c._endpoint_volume = None
    c._session_manager = None

    bad = MagicMock()
    type(bad).State = property(lambda self: (_ for _ in ()).throw(Exception("x")))

    with patch.object(ac.AudioUtilities, "GetAllSessions", return_value=[bad]):
        assert c._get_sav_for_key(42) is None
