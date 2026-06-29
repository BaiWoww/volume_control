"""Stress and concurrency tests."""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock, patch

import pytest

import audio_controller as ac
import volume_panel as vp


# ---- session enumeration stress -------------------------------------------

def test_stress_many_sessions_kept_in_sav_cache():
    """100 sessions should all end up in _sav_cache after a single enumeration."""
    c = ac.AudioController.__new__(ac.AudioController)
    __import__("PyQt5").QtCore.QObject.__init__(c)
    c._sav_cache = {}
    c._name_cache = {}
    c._endpoint_volume = None
    c._session_manager = None

    sessions = []
    for i in range(100):
        s = MagicMock()
        s.State = 0
        s.ProcessId = i + 1
        s._ctl.IsSystemSoundsSession.return_value = 1
        s.SimpleAudioVolume = MagicMock()
        s.SimpleAudioVolume.GetMasterVolume.return_value = 0.5
        s.SimpleAudioVolume.GetMute.return_value = False
        s.DisplayName = ""
        s.Process = MagicMock()
        s.Process.name.return_value = f"app{i}.exe"
        s.Process.exe.return_value = ""
        sessions.append(s)

    with patch.object(ac.AudioUtilities, "GetAllSessions", return_value=sessions):
        result = c.get_all_sessions()

    assert len(result) == 100
    assert len(c._sav_cache) == 100
    for i in range(1, 101):
        assert i in c._sav_cache


def test_stress_rapid_show_hide_no_emit_during_hide_anim(qapp):
    """Rapid toggling must not double-emit panel_closed."""
    from PyQt5.QtCore import QEventLoop, QTimer

    class FastAC:
        def get_master_volume(self): return 50
        def get_master_mute(self): return False
        def get_all_sessions(self): return []
        def set_volume_by_key(self, *a): return True
        def set_mute_by_key(self, *a): return True

    panel = vp.VolumePanel(FastAC())
    emissions = []
    panel.panel_closed.connect(lambda: emissions.append(1))
    panel.show()
    panel.show_panel(panel.pos())

    # Pump events for a few ms to let the show animation start.
    loop = QEventLoop()
    QTimer.singleShot(50, loop.quit)
    loop.exec_()

    # Hide and re-show rapidly
    panel.hide_panel()
    panel.show_panel(panel.pos())
    panel.hide_panel()
    panel.show_panel(panel.pos())
    panel.hide_panel()

    # Drain events
    loop2 = QEventLoop()
    QTimer.singleShot(300, loop2.quit)
    loop2.exec_()

    # Each successful hide should emit exactly once. The show_panel calls
    # should NOT emit panel_closed (the _hide_in_progress guard).
    assert len(emissions) <= 3
    panel.deleteLater()


def test_rapid_set_volume_clamps_correctly():
    """set_volume_by_key with values at and beyond the limits."""
    c = ac.AudioController.__new__(ac.AudioController)
    __import__("PyQt5").QtCore.QObject.__init__(c)
    c._sav_cache = {"system": MagicMock(), 1: MagicMock()}
    c._name_cache = {}
    c._endpoint_volume = MagicMock()
    c._device = MagicMock()  # required by _ensure_endpoint
    c._session_manager = None

    # Above max
    c.set_volume_by_key("master", 999)
    c._endpoint_volume.SetMasterVolumeLevelScalar.assert_called_with(1.0, None)
    # Below min
    c.set_volume_by_key("master", -50)
    c._endpoint_volume.SetMasterVolumeLevelScalar.assert_called_with(0.0, None)
    # In range
    c.set_volume_by_key("master", 42)
    c._endpoint_volume.SetMasterVolumeLevelScalar.assert_called_with(0.42, None)
    # System key
    c.set_volume_by_key("system", 50)
    c._sav_cache["system"].SetMasterVolume.assert_called_with(0.5, None)
    # PID key
    c.set_volume_by_key(1, 50)
    c._sav_cache[1].SetMasterVolume.assert_called_with(0.5, None)
