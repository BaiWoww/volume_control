"""Tests for :mod:`volume_panel`.

Uses a fake ``AudioController`` to keep these tests independent of the real
WASAPI stack.
"""

from __future__ import annotations

from typing import Dict, List
from unittest.mock import MagicMock

import pytest

import config
import volume_panel as vp


# ---- fixtures --------------------------------------------------------------

class FakeAudioController:
    def __init__(self, master_vol=42, master_mute=False, sessions=None):
        self._master_vol = master_vol
        self._master_mute = master_mute
        self._sessions = sessions if sessions is not None else []

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


def _sess(key, name="App", pid=1, vol=50, mute=False, is_system=False):
    return {"key": key, "pid": pid if not is_system else 0,
            "display_name": name, "volume": vol, "mute": mute,
            "is_system": is_system}


@pytest.fixture
def panel(qapp):
    ac = FakeAudioController()
    p = vp.VolumePanel(ac)
    yield p
    p.hide()
    p.deleteLater()


# ---- master slider creation ------------------------------------------------

def test_master_slider_uses_default_when_volume_none(qapp):
    ac = FakeAudioController(master_vol=None, master_mute=None)
    p = vp.VolumePanel(ac)
    try:
        assert p.master_slider._last_volume == config.DEFAULT_MASTER_FALLBACK_VOLUME
    finally:
        p.deleteLater()


# ---- panel_closed emission -------------------------------------------------

def _wait(ms, qapp):
    """Pump the event loop for ``ms`` milliseconds."""
    from PyQt5.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec_()


def test_panel_closed_emitted_once_on_hide_panel(panel, qapp):
    panel.show()
    panel.show_panel_from_test = None  # placeholder attribute
    panel.show_panel(panel.pos())
    _wait(200, qapp)
    emissions = []
    panel.panel_closed.connect(lambda: emissions.append(1))
    panel.hide_panel()
    _wait(400, qapp)
    assert len(emissions) == 1


def test_panel_closed_emitted_on_external_hide(panel, qapp):
    panel.show()
    emissions = []
    panel.panel_closed.connect(lambda: emissions.append(1))
    # Force a hide that bypasses hide_panel (e.g., clicking outside the popup).
    panel.hide()
    _wait(50, qapp)
    assert len(emissions) == 1


# ---- set_volume_external handling -----------------------------------------

def test_volume_slider_set_volume_external_ignores_none(qapp):
    slider = vp.VolumeSlider("X", volume=50, mute=False, key="k")
    before = slider.slider.value()
    slider.set_volume_external(None, False)
    assert slider.slider.value() == before


def test_volume_slider_set_volume_external_skips_while_sliding(qapp):
    slider = vp.VolumeSlider("X", volume=50, mute=False, key="k")
    slider.slider.blockSignals(True)
    slider.slider.setValue(20)
    slider._sliding = True
    slider.set_volume_external(80, False)
    # Because the user is dragging, the slider value must not be overwritten.
    assert slider.slider.value() == 20


# ---- incremental update ---------------------------------------------------

def test_populate_apps_incremental_add_remove_update(panel, qapp):
    # First population: two apps
    ac = panel.audio_controller
    ac._sessions = [_sess(1, "A"), _sess(2, "B")]
    panel._populate_apps()
    assert set(panel.app_sliders.keys()) == {1, 2}

    # Second population: A removed, B kept, C added
    ac._sessions = [_sess(2, "B"), _sess(3, "C")]
    panel._populate_apps()
    assert set(panel.app_sliders.keys()) == {2, 3}

    # All sliders are VolumeSlider instances with the correct key attribute
    for key, slider in panel.app_sliders.items():
        assert isinstance(slider, vp.VolumeSlider)
        assert slider.key == key


def test_empty_state_label_appears_when_no_sessions(panel, qapp):
    ac = panel.audio_controller
    ac._sessions = []
    panel._populate_apps()
    assert panel._empty_label is not None
    assert panel._empty_label.text() == vp.i18n.EMPTY_LIST


def test_empty_state_label_removed_when_sessions_return(panel, qapp):
    ac = panel.audio_controller
    ac._sessions = []
    panel._populate_apps()
    ac._sessions = [_sess(1, "A")]
    panel._populate_apps()
    assert panel._empty_label is None
