"""Tests for :mod:`audio_controller` with the WASAPI stack mocked out.

These tests verify the control-flow logic (sorting, deduplication, system
session handling, error recovery, cache invalidation) without depending on
the real pycaw / WASAPI stack.
"""

from __future__ import annotations

import logging
from typing import List
from unittest.mock import MagicMock, patch

import pytest

import audio_controller as ac
import config


# ---- helpers ---------------------------------------------------------------

def _make_sav(volume: int = 50, mute: bool = False) -> MagicMock:
    sav = MagicMock()
    sav.GetMasterVolume.return_value = volume / 100.0
    sav.GetMute.return_value = mute
    return sav


def _make_session(pid: int, *, state: int = 0, is_system: bool = False,
                  name: str = "demo", volume: int = 50,
                  mute: bool = False) -> MagicMock:
    s = MagicMock()
    s.State = state
    s.ProcessId = pid
    s._ctl.IsSystemSoundsSession.return_value = 0 if is_system else 1
    s.SimpleAudioVolume = _make_sav(volume, mute)
    s.DisplayName = "" if is_system else name
    if not is_system:
        s.Process = MagicMock()
        s.Process.name.return_value = name + ".exe"
        s.Process.exe.return_value = ""
    return s


# ---- _resolve_indirect_string ---------------------------------------------

def test_resolve_indirect_string_plain_passthrough():
    assert ac._resolve_indirect_string("Chrome") == "Chrome"
    assert ac._resolve_indirect_string("") is None or ac._resolve_indirect_string("") == ""


# ---- _volume_tier in audio_controller via get_all_sessions -----------------

def _build_controller(sessions: List[MagicMock] = None, master: int = 42,
                      master_mute: bool = False) -> ac.AudioController:
    """Construct a controller without hitting COM, and return it for inspection.

    The constructor no longer performs the WASAPI bootstrap (that lives in
    :meth:`AudioController.init`); we just instantiate it and then drive the
    internal caches directly.

    The ``sessions`` parameter is accepted for readability but is unused;
    callers supply their own list to ``AudioUtilities.GetAllSessions``.
    """
    _ = sessions  # intentionally unused
    c = ac.AudioController()
    ep = MagicMock()
    ep.GetMasterVolumeLevelScalar.return_value = master / 100.0
    ep.GetMute.return_value = master_mute
    c._endpoint_volume = ep
    c._device = MagicMock()
    c._session_manager = MagicMock()
    c._notification_sink = MagicMock()
    return c


def test_get_all_sessions_sorts_system_first():
    c = _build_controller([])
    system = _make_session(0, is_system=True, volume=100)
    app1 = _make_session(100, name="alpha", volume=40)
    app2 = _make_session(200, name="bravo", volume=70)
    with patch.object(ac.AudioUtilities, "GetAllSessions",
                      return_value=[app1, system, app2]):
        sessions = c.get_all_sessions()

    # system is always first; the rest sort by display_name (case-insensitive).
    assert [s["key"] for s in sessions] == ["system", 100, 200]
    assert [s["display_name"] for s in sessions[1:]] == ["alpha", "bravo"]


def test_get_all_sessions_dedupes_same_pid():
    c = _build_controller([])
    a = _make_session(42, name="chrome")
    b = _make_session(42, name="chrome")
    with patch.object(ac.AudioUtilities, "GetAllSessions", return_value=[a, b]):
        sessions = c.get_all_sessions()
    assert len(sessions) == 1
    assert sessions[0]["pid"] == 42


def test_get_all_sessions_skips_expired():
    c = _build_controller([])
    a = _make_session(1, name="alive", state=0)
    b = _make_session(2, name="dead", state=ac.AudioSessionState.Expired)
    with patch.object(ac.AudioUtilities, "GetAllSessions", return_value=[a, b]):
        sessions = c.get_all_sessions()
    assert [s["pid"] for s in sessions] == [1]


def test_get_all_sessions_populates_sav_cache():
    c = _build_controller([])
    sys_sess = _make_session(0, is_system=True, volume=80)
    app_sess = _make_session(99, name="app", volume=33)
    with patch.object(ac.AudioUtilities, "GetAllSessions",
                      return_value=[sys_sess, app_sess]):
        c.get_all_sessions()
    assert "system" in c._sav_cache
    assert 99 in c._sav_cache
    # Both entries are the SimpleAudioVolume attribute
    assert c._sav_cache["system"] is sys_sess.SimpleAudioVolume
    assert c._sav_cache[99] is app_sess.SimpleAudioVolume


def test_get_all_sessions_no_session_field_in_return():
    """The UI must not be handed raw COM objects; verify the cleanup."""
    c = _build_controller([])
    with patch.object(ac.AudioUtilities, "GetAllSessions",
                      return_value=[_make_session(1, name="x")]):
        sessions = c.get_all_sessions()
    for s in sessions:
        assert "_session" not in s


def test_get_all_sessions_handles_getall_failure(caplog):
    c = _build_controller([])
    with patch.object(ac.AudioUtilities, "GetAllSessions",
                      side_effect=Exception("boom")):
        with caplog.at_level(logging.WARNING):
            sessions = c.get_all_sessions()
    assert sessions == []


def test_set_master_volume_clamps_and_returns_true():
    c = _build_controller(master=50)
    assert c.set_master_volume(150) is True
    c._endpoint_volume.SetMasterVolumeLevelScalar.assert_called_with(1.0, None)
    assert c.set_master_volume(-10) is True
    c._endpoint_volume.SetMasterVolumeLevelScalar.assert_called_with(0.0, None)


def test_set_master_volume_failure_invalidates_endpoint():
    c = _build_controller(master=50)
    c._endpoint_volume.SetMasterVolumeLevelScalar.side_effect = Exception("x")
    assert c.set_master_volume(50) is False
    assert c._endpoint_volume is None


def test_shutdown_is_idempotent():
    c = _build_controller(master=50)
    c._com_initialized = True
    ole32 = MagicMock()
    with patch.object(ac.ctypes.windll, "ole32", ole32):
        c.shutdown()
        c.shutdown()
    assert ole32.CoUninitialize.call_count == 1
    assert c._shutdown_called is True


def test_shutdown_does_not_uninit_if_we_did_not_init():
    """If COM was already initialized by pycaw (S_FALSE), we must NOT uninit."""
    c = _build_controller(master=50)
    c._com_initialized = False
    ole32 = MagicMock()
    with patch.object(ac.ctypes.windll, "ole32", ole32):
        c.shutdown()
    ole32.CoUninitialize.assert_not_called()


def test_set_volume_by_key_dispatches_correctly():
    c = _build_controller(master=50)
    c._sav_cache["system"] = _make_sav(50)
    c._sav_cache[123] = _make_sav(50)

    # master
    assert c.set_volume_by_key("master", 30) is True
    c._endpoint_volume.SetMasterVolumeLevelScalar.assert_called_with(0.3, None)

    # system
    assert c.set_volume_by_key("system", 40) is True
    c._sav_cache["system"].SetMasterVolume.assert_called_with(0.4, None)

    # pid
    assert c.set_volume_by_key(123, 60) is True
    c._sav_cache[123].SetMasterVolume.assert_called_with(0.6, None)


def test_set_volume_by_key_invalid_key_returns_false():
    c = _build_controller(master=50)
    assert c.set_volume_by_key("not-a-valid-key", 50) is False
    assert c.set_volume_by_key("master", "not-a-number") is False
