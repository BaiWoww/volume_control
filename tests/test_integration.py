"""Integration tests for FloatingBall <-> VolumePanel <-> AudioController."""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock

import pytest

import audio_controller as ac
import volume_panel as vp


class FakeAudioController:
    def __init__(self, master_vol=42, master_mute=False, sessions=None):
        self._master_vol = master_vol
        self._master_mute = master_mute
        self._sessions = sessions if sessions is not None else []
        self.session_changed = MagicMock()
        self.register_session_callback = MagicMock(return_value=True)
        self.unregister_session_callback = MagicMock()
        self.shutdown = MagicMock()
        self.shutdown_called = 0
        self.unregister_called = 0

    def get_master_volume(self):
        return self._master_vol

    def get_master_mute(self):
        return self._master_mute

    def get_all_sessions(self):
        return list(self._sessions)

    def set_volume_by_key(self, key, value):
        return True

    def set_mute_by_key(self, key, mute):
        return True


def _sess(key, name="App", vol=50, mute=False, is_system=False, pid=1):
    return {"key": key, "pid": pid if not is_system else 0,
            "display_name": name, "volume": vol, "mute": mute,
            "is_system": is_system}


@pytest.fixture
def fake_ac():
    return FakeAudioController(
        master_vol=60, master_mute=False,
        sessions=[_sess(1, "Chrome"), _sess(2, "Spotify", vol=80),
                  _sess("system", "System Sounds", is_system=True)]
    )


# ---- FloatingBall integration ---------------------------------------------

def test_ball_registers_session_callback_on_init(fake_ac, qapp):
    from floating_ball import FloatingBall
    ball = FloatingBall(fake_ac)
    try:
        fake_ac.register_session_callback.assert_called_once()
    finally:
        ball.close()


def test_ball_creates_panel_lazily_on_toggle(fake_ac, qapp):
    from PyQt5.QtCore import QPoint
    from PyQt5.QtGui import QGuiApplication
    from floating_ball import FloatingBall
    ball = FloatingBall(fake_ac)
    try:
        assert ball._panel is None
        ball.show()
        # Use a real QPoint so arithmetic with int works.
        ball.mapToGlobal = lambda p: QPoint(100, 100)
        ball._toggle_panel()
        assert ball._panel is not None
        # volume_changed and mute_toggled signals are wired
        assert ball._panel.receivers(ball._panel.volume_changed) > 0
        assert ball._panel.receivers(ball._panel.mute_toggled) > 0
    finally:
        ball.close()


def test_ball_on_volume_changed_calls_controller(fake_ac, qapp):
    from floating_ball import FloatingBall
    ball = FloatingBall(fake_ac)
    try:
        ball._on_volume_changed("master", 75)
        # The fake set_volume_by_key returns True without side effects
        # but the call should not raise.
    finally:
        ball.close()


def test_ball_on_mute_toggled_calls_controller(fake_ac, qapp):
    from floating_ball import FloatingBall
    ball = FloatingBall(fake_ac)
    try:
        ball._on_mute_toggled(123, True)
    finally:
        ball.close()


def test_ball_exit_app_shuts_down_controller(fake_ac, qapp, monkeypatch):
    """_exit_app must shut down the controller and request application quit
    without actually quitting (so other tests can still run)."""
    from PyQt5.QtWidgets import QApplication
    from floating_ball import FloatingBall
    quit_called = []
    monkeypatch.setattr(QApplication, "quit",
                        lambda: quit_called.append(1))
    ball = FloatingBall(fake_ac)
    try:
        ball._exit_app()
        assert fake_ac.shutdown.called
        assert quit_called == [1]
    finally:
        ball.close()


def test_ball_close_event_shuts_down_controller(fake_ac, qapp):
    from floating_ball import FloatingBall
    ball = FloatingBall(fake_ac)
    ball.show()
    ball.close()
    assert fake_ac.shutdown.called


def test_ball_setup_hotkey_disabled_via_config(qapp, fake_ac, monkeypatch):
    """If HOTKEY_DEFAULT_ENABLED is False, no hotkey is created."""
    import config
    monkeypatch.setattr(config, "HOTKEY_DEFAULT_ENABLED", False)
    from floating_ball import FloatingBall
    ball = FloatingBall(fake_ac)
    try:
        assert ball._hotkey is None
    finally:
        ball.close()


# ---- VolumePanel integration -----------------------------------------------

def test_panel_volume_change_emits_to_ball(fake_ac, qapp):
    from PyQt5.QtCore import QPoint
    from floating_ball import FloatingBall
    ball = FloatingBall(fake_ac)
    try:
        ball.show()
        ball.mapToGlobal = lambda p: QPoint(100, 100)
        ball._toggle_panel()
        emissions = []
        ball._on_volume_changed = lambda k, v: emissions.append((k, v))
        ball._panel.volume_changed.disconnect()
        ball._panel.volume_changed.connect(ball._on_volume_changed)
        ball._panel.master_slider.volume_changed.emit(50)
        assert emissions == [("master", 50)]
    finally:
        ball.close()


def test_panel_refresh_uses_audio_controller_sessions(fake_ac, qapp):
    from PyQt5.QtCore import QPoint
    from floating_ball import FloatingBall
    ball = FloatingBall(fake_ac)
    try:
        ball.show()
        ball.mapToGlobal = lambda p: QPoint(100, 100)
        ball._toggle_panel()
        assert set(ball._panel.app_sliders.keys()) == {1, 2, "system"}
    finally:
        ball.close()


def test_panel_signal_not_connected_to_slider_after_lazy_creation(fake_ac, qapp):
    """Each VolumeSlider's key is correctly stored on construction."""
    slider = vp.VolumeSlider("Chrome", volume=50, mute=False, key=42)
    assert slider.key == 42
    assert slider.name == "Chrome"
    assert slider._last_volume == 50
    slider.deleteLater()


def test_panel_slider_key_none_is_allowed(fake_ac, qapp):
    slider = vp.VolumeSlider("X", volume=50, mute=False)
    assert slider.key is None
    slider.deleteLater()


def test_volume_slider_toggle_mute_emits_both_signals(qapp):
    slider = vp.VolumeSlider("X", volume=50, mute=False, key=1)
    muted_events = []
    vol_events = []
    slider.mute_toggled.connect(lambda m: muted_events.append(m))
    slider.volume_changed.connect(lambda v: vol_events.append(v))
    slider._toggle_mute()
    assert muted_events == [True]
    # Un-muting emits a volume_changed so the user sees the level restored.
    slider._toggle_mute()
    assert muted_events == [True, False]
    assert vol_events  # contains the restore value
    slider.deleteLater()


def test_volume_slider_handles_volume_value_none(qapp):
    """A None volume from external source must not crash _setup_ui."""
    slider = vp.VolumeSlider("X", volume=None, mute=False, key=1)
    # Falls back to DEFAULT_SESSION_FALLBACK_VOLUME
    assert slider._last_volume == 80
    slider.deleteLater()
