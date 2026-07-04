"""Tests for the floating ball paint cache and visibility state machine."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import floating_ball as fb


@pytest.fixture
def ball(qapp):
    ac = MagicMock()
    ac.session_changed = MagicMock()
    ac.register_session_callback = MagicMock()
    b = fb.FloatingBall(ac)
    yield b
    try:
        b.close()
    except Exception:
        pass


def test_initial_visibility_is_visible(ball):
    assert ball.visibility == fb.BallVisibility.VISIBLE
    assert ball.is_hidden is False
    assert ball.hide_edge is None


def test_paint_event_uses_cached_pixmap(ball, qapp):
    """Two paint events should reuse the same QPixmap object."""
    pm1 = ball._ensure_pixmap()
    pm2 = ball._ensure_pixmap()
    assert pm1 is pm2
    assert not pm1.isNull()
    assert pm1.size().width() > 0


def test_paint_event_pixmap_invalidated_on_resize(ball, qapp):
    """If the cached size no longer matches the widget, the pixmap rebuilds."""
    pm1 = ball._ensure_pixmap()
    # Bypass setFixedSize so we can resize the widget for the test.
    ball.setMinimumSize(0, 0)
    ball.setMaximumSize(1000, 1000)
    ball.resize(120, 120)
    pm2 = ball._ensure_pixmap()
    assert pm2.size() != pm1.size()


def test_render_ball_to_pixmap_has_transparent_padding(ball, qapp):
    pm = ball._render_ball_to_pixmap()
    # The pixmap is larger than the widget so the shadow is not clipped.
    assert pm.width() >= ball.width()
    assert pm.height() >= ball.height()


def test_animate_scale_creates_animation(ball, qapp):
    from PyQt5.QtCore import QPropertyAnimation
    ball._animate_scale(1.5, 100)
    assert isinstance(ball._scale_anim, QPropertyAnimation)
    assert ball._scale_anim.endValue() == 1.5


def test_animate_scale_stops_previous(ball, qapp):
    ball._animate_scale(1.1, 200)
    first = ball._scale_anim
    ball._animate_scale(1.2, 200)
    # _animate_scale doesn't return the animation; the attribute is replaced.
    assert ball._scale_anim is not None
    assert ball._scale_anim is not first
    assert ball._scale_anim.endValue() == 1.2


def test_paint_event_does_not_raise(ball, qapp):
    """Smoke test: paintEvent with default scale runs without error."""
    ball.show()
    qapp.processEvents()
    ball.update()
    qapp.processEvents()


def test_paint_event_with_scale_anim(ball, qapp):
    """Paint with non-unit scale (simulating hover/press)."""
    ball._scale = 1.12
    ball.show()
    qapp.processEvents()
    ball.update()
    qapp.processEvents()
    ball._scale = 1.0


def test_set_scale_triggers_update(ball, qapp):
    """scale setter should request a repaint."""
    ball._cached_pixmap = MagicMock()  # ensure update doesn't rebuild
    ball.show()
    ball.scale = 1.5
    qapp.processEvents()
    assert ball._scale == 1.5


def test_ball_visibility_enum_values():
    """The enum must expose the three canonical states."""
    assert fb.BallVisibility.VISIBLE.value == "visible"
    assert fb.BallVisibility.HIDING.value == "hiding"
    assert fb.BallVisibility.HIDDEN.value == "hidden"


def test_legacy_module_aliases_still_exposed():
    """Backwards-compat aliases for tests/importers that referenced the
    module-level constants directly."""
    assert fb.EDGE_MARGIN > 0
    assert fb.BALL_SIZE > 0


def test_show_ball_unhides_hidden_ball(ball, qapp):
    """_show_ball brings a hidden ball back to visible state."""
    ball.is_hidden = True
    ball.visibility = fb.BallVisibility.HIDDEN
    ball._show_ball()
    assert ball.is_hidden is False
    assert ball.visibility == fb.BallVisibility.VISIBLE


def test_show_requested_signal_triggers_show(ball, qapp):
    """Emitting show_requested unhides the ball."""
    ball.is_hidden = True
    ball.visibility = fb.BallVisibility.HIDDEN
    ball.show_requested.emit()
    qapp.processEvents()
    assert ball.is_hidden is False
    assert ball.visibility == fb.BallVisibility.VISIBLE


def test_tray_icon_created_when_available(ball, qapp):
    """If the system tray is available, the ball creates a tray icon."""
    if fb.QSystemTrayIcon.isSystemTrayAvailable():
        assert ball._tray is not None
    else:
        assert ball._tray is None


def test_hotkey_activated_unhides_ball(ball, qapp):
    """The global hotkey now un-hides the ball before toggling the panel."""
    ball.is_hidden = True
    ball.visibility = fb.BallVisibility.HIDDEN
    ball._toggle_panel = MagicMock()
    ball._on_hotkey_activated()
    qapp.processEvents()
    assert ball.is_hidden is False
    ball._toggle_panel.assert_called_once()
