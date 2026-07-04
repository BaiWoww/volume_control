"""Floating control ball widget.

A frameless, always-on-top circular widget that lives in the screen corner,
owns the volume mixer panel, and provides drag, edge-snap, auto-hide, and
context-menu interactions. The ball is painted into a cached QPixmap and
only re-rendered when the widget is resized; the scale animation uses
SmoothPixmapTransform to stay cheap.
"""

from __future__ import annotations

import enum
import logging
from typing import Optional

from PyQt5.QtWidgets import QWidget, QMenu, QAction, QApplication, QSystemTrayIcon
from PyQt5.QtCore import (Qt, QTimer, QPoint, QRectF, QSize, pyqtSignal, pyqtProperty,
                          QEasingCurve, QPropertyAnimation, QEvent)
from PyQt5.QtGui import (QPainter, QColor, QBrush, QPen, QRadialGradient, QPainterPath,
                         QMouseEvent, QCloseEvent, QPixmap, QResizeEvent)

import config
import i18n
from hotkey import GlobalHotkey
from volume_panel import VolumePanel, SessionKey

LOGGER = logging.getLogger(__name__)

# Backwards-compat aliases for tests/importers.
EDGE_MARGIN = config.EDGE_MARGIN
BALL_SIZE = config.BALL_SIZE


class BallVisibility(enum.Enum):
    VISIBLE = "visible"
    HIDING = "hiding"
    HIDDEN = "hidden"


class FloatingBall(QWidget):
    exit_requested = pyqtSignal()
    show_requested = pyqtSignal()

    def __init__(self, audio_controller):
        super().__init__()
        self.audio_controller = audio_controller
        self.audio_controller.session_changed.connect(self._on_session_notification)
        self.audio_controller.register_session_callback()

        self.is_always_on_top: bool = True
        self.is_hidden: bool = False
        self.dragging: bool = False
        self.drag_offset: QPoint = QPoint()
        self.drag_start_pos: QPoint = QPoint()
        self.hide_edge: Optional[str] = None
        self._idle_timer: Optional[QTimer] = None
        self._panel: Optional[VolumePanel] = None
        self._scale: float = 1.0
        self._pos_anim: Optional[QPropertyAnimation] = None
        self._opacity_anim: Optional[QPropertyAnimation] = None
        self._scale_anim: Optional[QPropertyAnimation] = None
        self._cached_pixmap: Optional[QPixmap] = None
        self._cached_widget_size: Optional[QSize] = None
        self.visibility: BallVisibility = BallVisibility.VISIBLE
        self._hotkey: Optional[GlobalHotkey] = None
        self._tray: Optional[QSystemTrayIcon] = None

        self._setup_window()
        self._setup_idle_timer()
        self._setup_hotkey()
        self._setup_tray()
        self._move_to_initial_position()

        self.show_requested.connect(self._show_ball)

    def _setup_window(self) -> None:
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(BALL_SIZE, BALL_SIZE)
        self.setMouseTracking(True)
        self.setWindowOpacity(config.ANIM_VISIBLE_OPACITY)

    @pyqtProperty(float)
    def scale(self) -> float:
        return self._scale

    @scale.setter  # type: ignore[no-redef]
    def scale(self, v: float) -> None:
        self._scale = v
        self.update()

    def _setup_idle_timer(self) -> None:
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(config.IDLE_HIDE_MS)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._start_hide_animation)
        self._idle_timer.start()

    def _setup_hotkey(self) -> None:
        if not config.HOTKEY_DEFAULT_ENABLED:
            return
        self._hotkey = GlobalHotkey(config.HOTKEY_DEFAULT_MODIFIERS,
                                     config.HOTKEY_DEFAULT_VK,
                                     parent=self)
        self._hotkey.activated.connect(self._on_hotkey_activated)
        self._hotkey.start()

    def _setup_tray(self) -> None:
        """Create a system-tray icon so the app stays reachable after the
        ball auto-hides. Silently skipped on systems without a tray."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            LOGGER.info("System tray not available; skipping tray icon")
            return
        self._tray = QSystemTrayIcon(self.windowIcon(), self)
        self._tray.setToolTip(config.APP_DISPLAY_NAME)
        self._tray.activated.connect(self._on_tray_activated)

        menu = QMenu()
        show_action = QAction(i18n.TRAY_SHOW, self)
        show_action.triggered.connect(self._show_ball)
        menu.addAction(show_action)
        menu.addSeparator()
        exit_action = QAction(i18n.MENU_EXIT, self)
        exit_action.triggered.connect(self._exit_app)
        menu.addAction(exit_action)
        self._tray.setContextMenu(menu)
        self._tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_ball()

    def _show_ball(self) -> None:
        """Bring the floating ball back on screen from a hidden state."""
        self._start_show_animation()
        self.raise_()
        self.activateWindow()
        self.reset_idle_timer()

    def _on_hotkey_activated(self) -> None:
        LOGGER.info("Hotkey activated")
        self._show_ball()
        self._toggle_panel()

    def _move_to_initial_position(self) -> None:
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = geo.width() - 90
        y = geo.height() // 2 - BALL_SIZE // 2
        self.move(x, y)

    def reset_idle_timer(self) -> None:
        if self._idle_timer:
            self._idle_timer.stop()
            self._idle_timer.start()
        if self.is_hidden:
            self._start_show_animation()

    def _stop_pos_anim(self) -> None:
        if self._pos_anim is not None:
            self._pos_anim.stop()
            self._pos_anim = None
        if self._opacity_anim is not None:
            self._opacity_anim.stop()
            self._opacity_anim = None

    def _animate_pos(self, target_pos: QPoint, duration: int = 280,
                     easing: QEasingCurve.Type = QEasingCurve.OutCubic) -> QPropertyAnimation:
        self._stop_pos_anim()
        pos_anim = QPropertyAnimation(self, b"pos", self)
        pos_anim.setDuration(duration)
        pos_anim.setEasingCurve(easing)
        pos_anim.setStartValue(self.pos())
        pos_anim.setEndValue(QPoint(int(target_pos.x()), int(target_pos.y())))
        self._pos_anim = pos_anim
        pos_anim.start()
        return pos_anim

    def _animate_opacity(self, target_opacity: float, duration: int = 200,
                         easing: QEasingCurve.Type = QEasingCurve.OutCubic) -> QPropertyAnimation:
        op_anim = QPropertyAnimation(self, b"windowOpacity", self)
        op_anim.setDuration(duration)
        op_anim.setEasingCurve(easing)
        op_anim.setStartValue(self.windowOpacity())
        op_anim.setEndValue(target_opacity)
        self._opacity_anim = op_anim
        op_anim.start()
        return op_anim

    def _start_hide_animation(self) -> None:
        if self.dragging:
            self.reset_idle_timer()
            return
        if self._panel and self._panel.isVisible():
            self.reset_idle_timer()
            return
        if self.is_hidden:
            return

        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        pos = self.pos()
        cx = pos.x() + self.width() / 2
        cy = pos.y() + self.height() / 2

        dists = {
            'left': cx,
            'right': geo.width() - cx,
            'top': cy,
            'bottom': geo.height() - cy,
        }
        edge = min(dists, key=lambda k: dists[k])

        if edge == 'left':
            self.hide_edge = 'left'
            new_x = -self.width() + EDGE_MARGIN
            new_y = pos.y()
        elif edge == 'right':
            self.hide_edge = 'right'
            new_x = geo.width() - EDGE_MARGIN
            new_y = pos.y()
        elif edge == 'top':
            self.hide_edge = 'top'
            new_x = pos.x()
            new_y = -self.height() + EDGE_MARGIN
        else:
            self.hide_edge = 'bottom'
            new_x = pos.x()
            new_y = geo.height() - EDGE_MARGIN

        new_y = max(0, min(new_y, geo.height() - self.height()))
        new_x = max(-self.width() + EDGE_MARGIN, min(new_x, geo.width() - EDGE_MARGIN))

        self.is_hidden = True
        self.visibility = BallVisibility.HIDING
        self._animate_pos(QPoint(new_x, new_y), duration=config.ANIM_HIDE_MS)
        self._animate_opacity(config.ANIM_HIDDEN_OPACITY, duration=config.ANIM_HIDE_OPACITY_MS)

    def _start_show_animation(self) -> None:
        if not self.is_hidden:
            if self.windowOpacity() < config.ANIM_VISIBLE_OPACITY:
                self._animate_opacity(config.ANIM_VISIBLE_OPACITY, duration=150)
            return

        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        pos = self.pos()

        if self.hide_edge == 'left':
            new_x = 0
            new_y = pos.y()
        elif self.hide_edge == 'right':
            new_x = geo.width() - self.width()
            new_y = pos.y()
        elif self.hide_edge == 'top':
            new_x = pos.x()
            new_y = 0
        else:
            new_x = pos.x()
            new_y = geo.height() - self.height()

        new_y = max(0, min(new_y, geo.height() - self.height()))
        new_x = max(0, min(new_x, geo.width() - self.width()))

        self.is_hidden = False
        self.hide_edge = None
        self.visibility = BallVisibility.VISIBLE
        self._animate_pos(QPoint(new_x, new_y),
                          duration=config.ANIM_SHOW_MS,
                          easing=QEasingCurve.OutBack)
        self._animate_opacity(config.ANIM_VISIBLE_OPACITY, duration=config.ANIM_SHOW_OPACITY_MS)

    def _render_ball_to_pixmap(self) -> QPixmap:
        """Render the ball at scale=1.0 into a cached QPixmap.

        The pixmap is built slightly larger than the widget so the shadow
        (which extends past the ball) is not clipped when the hover/press
        animation grows the ball up to 1.12x.
        """
        pad = int(self.width() * 0.25)
        pm = QPixmap(self.width() + pad * 2, self.height() + pad * 2)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            cx = pm.width() / 2
            cy = pm.height() / 2
            r = (self.width() / 2) - 6
            center = QPoint(int(cx), int(cy))

            shadow = QRadialGradient(center, r + 12)
            shadow.setColorAt(0, QColor(74, 158, 255, 50))
            shadow.setColorAt(0.5, QColor(74, 158, 255, 25))
            shadow.setColorAt(1, QColor(74, 158, 255, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(shadow))
            p.drawEllipse(center, int(r + 10), int(r + 10))

            bg = QRadialGradient(center, r)
            bg.setColorAt(0, QColor(255, 255, 255))
            bg.setColorAt(0.85, QColor(240, 246, 255))
            bg.setColorAt(1, QColor(210, 228, 255))
            p.setBrush(QBrush(bg))
            p.setPen(QPen(QColor(180, 210, 245), 1.0))
            p.drawEllipse(center, int(r), int(r))

            hl = QRadialGradient(QPoint(int(cx - r * 0.35), int(cy - r * 0.4)), r * 0.8)
            hl.setColorAt(0, QColor(255, 255, 255, 200))
            hl.setColorAt(1, QColor(255, 255, 255, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(hl))
            p.drawEllipse(QPoint(int(cx - r * 0.2), int(cy - r * 0.25)), int(r * 0.55), int(r * 0.4))

            icon_r = r * 0.42
            accent = QColor(*config.ACCENT_BLUE_RGB)
            p.setBrush(QBrush(accent))
            p.setPen(Qt.NoPen)
            path = QPainterPath()
            icx = cx - icon_r * 0.1
            icy = cy
            spk_w = icon_r * 0.52
            spk_h = icon_r * 0.78
            path.moveTo(icx - spk_w * 0.5, icy - spk_h * 0.2)
            path.lineTo(icx - spk_w * 0.12, icy - spk_h * 0.2)
            path.lineTo(icx + spk_w * 0.32, icy - spk_h * 0.78)
            path.lineTo(icx + spk_w * 0.32, icy + spk_h * 0.78)
            path.lineTo(icx - spk_w * 0.12, icy + spk_h * 0.2)
            path.lineTo(icx - spk_w * 0.5, icy + spk_h * 0.2)
            path.closeSubpath()
            p.drawPath(path)
            pen = QPen(accent, max(1.8, icon_r * 0.22), Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            for off in (0.2, 0.55):
                arc_r = icon_r * (0.75 + off * 0.55)
                p.drawArc(QRectF(cx + icon_r * 0.02, cy - arc_r, arc_r, arc_r * 2), -18 * 16, 36 * 16)
        finally:
            p.end()
        return pm

    def _ensure_pixmap(self) -> QPixmap:
        current_size = QSize(self.width(), self.height())
        if self._cached_pixmap is None or self._cached_widget_size != current_size:
            self._cached_pixmap = self._render_ball_to_pixmap()
            self._cached_widget_size = current_size
        return self._cached_pixmap

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._cached_pixmap = None
        super().resizeEvent(event)

    def paintEvent(self, event: QEvent) -> None:
        pm = self._ensure_pixmap()
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            scale = self._scale
            target_w = pm.width() * scale
            target_h = pm.height() * scale
            x = (self.width() - target_w) / 2
            y = (self.height() - target_h) / 2
            painter.drawPixmap(int(x), int(y), int(target_w), int(target_h), pm)
        finally:
            painter.end()

    def _animate_scale(self, target: float, duration: int,
                      easing: QEasingCurve.Type = QEasingCurve.OutCubic) -> None:
        if self._scale_anim is not None:
            self._scale_anim.stop()
        anim = QPropertyAnimation(self, b"scale", self)
        anim.setDuration(duration)
        anim.setEasingCurve(easing)
        anim.setStartValue(self._scale)
        anim.setEndValue(target)
        self._scale_anim = anim
        anim.start()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.drag_start_pos = event.globalPos()
            self.drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            if not self.is_hidden:
                self._animate_scale(config.ANIM_PRESS_SCALE, config.ANIM_PRESS_MS)
            self._start_show_animation()
            self.reset_idle_timer()
            event.accept()
        elif event.button() == Qt.RightButton:
            self._show_context_menu(event.globalPos())
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.LeftButton:
            if (event.globalPos() - self.drag_start_pos).manhattanLength() > config.DRAG_THRESHOLD:
                self.dragging = True
                self._animate_scale(1.0, 120)
            if self.dragging:
                self._stop_pos_anim()
                new_pos = event.globalPos() - self.drag_offset
                screen = QApplication.primaryScreen()
                geo = screen.availableGeometry()
                new_x = max(-self.width() + EDGE_MARGIN, min(new_pos.x(), geo.width() - EDGE_MARGIN))
                new_y = max(-self.height() + EDGE_MARGIN, min(new_pos.y(), geo.height() - EDGE_MARGIN))
                self.move(new_x, new_y)
                self.is_hidden = False
                self.hide_edge = None
                self.visibility = BallVisibility.VISIBLE
                self.setWindowOpacity(config.ANIM_VISIBLE_OPACITY)
                self.reset_idle_timer()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._animate_scale(1.0, config.ANIM_RELEASE_MS, QEasingCurve.OutBack)
            if not self.dragging:
                self._toggle_panel()
            else:
                self._snap_to_edge_animated()
            self.dragging = False
            self.reset_idle_timer()
            event.accept()

    def _snap_to_edge_animated(self) -> None:
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        pos = self.pos()
        cx = pos.x() + self.width() / 2
        cy = pos.y() + self.height() / 2

        margin = config.SNAP_MARGIN
        new_x, new_y = pos.x(), pos.y()

        if cx < margin:
            new_x = 0
        elif cx > geo.width() - margin:
            new_x = geo.width() - self.width()
        if cy < margin:
            new_y = 0
        elif cy > geo.height() - margin:
            new_y = geo.height() - self.height()

        if new_x != pos.x() or new_y != pos.y():
            self._animate_pos(QPoint(new_x, new_y), duration=config.ANIM_SNAP_MS)

    def enterEvent(self, event: QEvent) -> None:
        self._animate_scale(config.ANIM_HOVER_SCALE, config.ANIM_HOVER_MS, QEasingCurve.OutBack)
        self._start_show_animation()
        self.reset_idle_timer()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._animate_scale(1.0, 150)
        self.reset_idle_timer()
        super().leaveEvent(event)

    def _toggle_panel(self) -> None:
        if self._panel is None:
            self._panel = VolumePanel(self.audio_controller)
            self._panel.volume_changed.connect(self._on_volume_changed)
            self._panel.mute_toggled.connect(self._on_mute_toggled)

        if self._panel.isVisible():
            self._panel.hide_panel()
            self.reset_idle_timer()
        else:
            screen = QApplication.primaryScreen()
            geo = screen.availableGeometry()
            panel_pos = self.mapToGlobal(QPoint(0, 0))

            panel_w = config.PANEL_W
            panel_h = config.PANEL_H
            panel_x = panel_pos.x() + self.width() + 8
            panel_y = panel_pos.y() - (panel_h - self.height()) // 2

            if panel_x + panel_w > geo.width() - 4:
                panel_x = panel_pos.x() - panel_w - 8
            if panel_y + panel_h > geo.height() - 4:
                panel_y = geo.height() - panel_h - 4
            panel_y = max(4, panel_y)

            self._panel.show_panel(QPoint(panel_x, panel_y))
            self.reset_idle_timer()

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #d0e3ff;
                border-radius: 10px;
                padding: 8px 6px;
                color: #1a1a1a;
                font-size: 13px;
            }
            QMenu::item {
                padding: 8px 28px 8px 18px;
                border-radius: 6px;
                margin: 2px 4px;
            }
            QMenu::item:selected {
                background: rgba(74, 158, 255, 35);
                color: #1a73e8;
            }
            QMenu::separator {
                height: 1px;
                background: #e5eaf2;
                margin: 4px 10px;
            }
            QMenu::indicator {
                width: 0px;
                height: 0px;
            }
        """)

        toggle_top_action = QAction((i18n.MENU_UNPIN if self.is_always_on_top else i18n.MENU_PIN), self)
        toggle_top_action.triggered.connect(self._toggle_always_on_top)
        menu.addAction(toggle_top_action)
        menu.addSeparator()
        exit_action = QAction(i18n.MENU_EXIT, self)
        exit_action.triggered.connect(self._exit_app)
        menu.addAction(exit_action)

        menu.exec_(global_pos)
        self.reset_idle_timer()

    def _toggle_always_on_top(self) -> None:
        self.is_always_on_top = not self.is_always_on_top
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.is_always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self.reset_idle_timer()

    def _exit_app(self) -> None:
        try:
            self.audio_controller.shutdown()
        except Exception:
            LOGGER.exception("audio_controller.shutdown() failed")
        if self._tray is not None:
            self._tray.hide()
        QApplication.quit()

    def _on_volume_changed(self, key: SessionKey, value: int) -> None:
        self.audio_controller.set_volume_by_key(key, value)
        self.reset_idle_timer()

    def _on_mute_toggled(self, key: SessionKey, muted: bool) -> None:
        self.audio_controller.set_mute_by_key(key, muted)
        self.reset_idle_timer()

    def _on_session_notification(self) -> None:
        if self._panel and self._panel.isVisible():
            QTimer.singleShot(config.SESSION_NOTIFY_REFRESH_DELAY_MS, self._refresh_panel)

    def _refresh_panel(self) -> None:
        if self._panel and self._panel.isVisible():
            self._panel.refresh_sessions()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._hotkey is not None:
            try:
                self._hotkey.stop()
            except Exception:
                LOGGER.exception("hotkey.stop() failed in closeEvent")
        if self._tray is not None:
            self._tray.hide()
        try:
            self.audio_controller.shutdown()
        except Exception:
            LOGGER.exception("audio_controller.shutdown() failed in closeEvent")
        super().closeEvent(event)
