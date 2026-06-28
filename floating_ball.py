from PyQt5.QtWidgets import QWidget, QMenu, QAction, QApplication
from PyQt5.QtCore import Qt, QTimer, QPoint, QRectF, pyqtSignal, pyqtProperty, QEasingCurve, QPropertyAnimation
from PyQt5.QtGui import QPainter, QColor, QBrush, QPen, QRadialGradient, QPainterPath

from volume_panel import VolumePanel

EDGE_MARGIN = 30
BALL_SIZE = 56


class FloatingBall(QWidget):
    exit_requested = pyqtSignal()

    def __init__(self, audio_controller):
        super().__init__()
        self.audio_controller = audio_controller
        self.audio_controller.session_changed.connect(self._on_session_notification)
        self.audio_controller.register_session_callback()
        
        self.is_always_on_top = True
        self.is_hidden = False
        self.dragging = False
        self.drag_offset = QPoint()
        self.drag_start_pos = QPoint()
        self.hide_edge = None
        self._idle_timer = None
        self._panel = None
        self._scale = 1.0
        self._pos_anim = None
        self._opacity_anim = None
        self._scale_anim = None

        self._setup_window()
        self._setup_idle_timer()
        self._move_to_initial_position()

    def _setup_window(self):
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(BALL_SIZE, BALL_SIZE)
        self.setMouseTracking(True)
        self.setWindowOpacity(1.0)

    @pyqtProperty(float)
    def scale(self):
        return self._scale

    @scale.setter
    def scale(self, v):
        self._scale = v
        self.update()

    def _setup_idle_timer(self):
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(5000)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._start_hide_animation)
        self._idle_timer.start()

    def _move_to_initial_position(self):
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = geo.width() - 90
        y = geo.height() // 2 - BALL_SIZE // 2
        self.move(x, y)

    def reset_idle_timer(self):
        if self._idle_timer:
            self._idle_timer.stop()
            self._idle_timer.start()
        if self.is_hidden:
            self._start_show_animation()

    def _stop_pos_anim(self):
        if self._pos_anim is not None:
            self._pos_anim.stop()
            self._pos_anim = None
        if self._opacity_anim is not None:
            self._opacity_anim.stop()
            self._opacity_anim = None

    def _animate_pos(self, target_pos, duration=280, easing=QEasingCurve.OutCubic):
        self._stop_pos_anim()
        pos_anim = QPropertyAnimation(self, b"pos", self)
        pos_anim.setDuration(duration)
        pos_anim.setEasingCurve(easing)
        pos_anim.setStartValue(self.pos())
        pos_anim.setEndValue(QPoint(int(target_pos.x()), int(target_pos.y())))
        self._pos_anim = pos_anim
        pos_anim.start()
        return pos_anim

    def _animate_opacity(self, target_opacity, duration=200, easing=QEasingCurve.OutCubic):
        op_anim = QPropertyAnimation(self, b"windowOpacity", self)
        op_anim.setDuration(duration)
        op_anim.setEasingCurve(easing)
        op_anim.setStartValue(self.windowOpacity())
        op_anim.setEndValue(target_opacity)
        self._opacity_anim = op_anim
        op_anim.start()
        return op_anim

    def _start_hide_animation(self):
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
        edge = min(dists, key=dists.get)

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
        self._animate_pos(QPoint(new_x, new_y), duration=300)
        self._animate_opacity(0.45, duration=250)

    def _start_show_animation(self):
        if not self.is_hidden:
            if self.windowOpacity() < 1.0:
                self._animate_opacity(1.0, duration=150)
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
        self._animate_pos(QPoint(new_x, new_y), duration=220, easing=QEasingCurve.OutBack)
        self._animate_opacity(1.0, duration=180)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        scale = self._scale
        cx = self.width() / 2
        cy = self.height() / 2
        r = (self.width() / 2 - 6) * scale
        center = QPoint(int(cx), int(cy))

        shadow_gradient = QRadialGradient(center, r + 12)
        shadow_gradient.setColorAt(0, QColor(74, 158, 255, 50))
        shadow_gradient.setColorAt(0.5, QColor(74, 158, 255, 25))
        shadow_gradient.setColorAt(1, QColor(74, 158, 255, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(shadow_gradient))
        painter.drawEllipse(center, int(r + 10), int(r + 10))

        bg_grad = QRadialGradient(center, r)
        bg_grad.setColorAt(0, QColor(255, 255, 255))
        bg_grad.setColorAt(0.85, QColor(240, 246, 255))
        bg_grad.setColorAt(1, QColor(210, 228, 255))
        painter.setBrush(QBrush(bg_grad))
        painter.setPen(QPen(QColor(180, 210, 245), 1.0))
        painter.drawEllipse(center, int(r), int(r))

        hl_grad = QRadialGradient(QPoint(int(cx - r * 0.35), int(cy - r * 0.4)), r * 0.8)
        hl_grad.setColorAt(0, QColor(255, 255, 255, 200))
        hl_grad.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(hl_grad))
        painter.drawEllipse(QPoint(int(cx - r * 0.2), int(cy - r * 0.25)), int(r * 0.55), int(r * 0.4))

        icon_r = r * 0.42
        painter.setBrush(QBrush(QColor(74, 158, 255)))
        painter.setPen(Qt.NoPen)
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
        painter.drawPath(path)
        pen = QPen(QColor(74, 158, 255), max(1.8, icon_r * 0.22), Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        for off in [0.2, 0.55]:
            arc_r = icon_r * (0.75 + off * 0.55)
            painter.drawArc(QRectF(cx + icon_r * 0.02, cy - arc_r, arc_r * 1.0, arc_r * 2), -18 * 16, 36 * 16)

    def _animate_scale(self, target, duration, easing=QEasingCurve.OutCubic):
        if self._scale_anim is not None:
            self._scale_anim.stop()
        anim = QPropertyAnimation(self, b"scale", self)
        anim.setDuration(duration)
        anim.setEasingCurve(easing)
        anim.setStartValue(self._scale)
        anim.setEndValue(target)
        self._scale_anim = anim
        anim.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.drag_start_pos = event.globalPos()
            self.drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            if not self.is_hidden:
                self._animate_scale(0.92, 100)
            self._start_show_animation()
            self.reset_idle_timer()
            event.accept()
        elif event.button() == Qt.RightButton:
            self._show_context_menu(event.globalPos())
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            if (event.globalPos() - self.drag_start_pos).manhattanLength() > 5:
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
                self.setWindowOpacity(1.0)
                self.reset_idle_timer()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._animate_scale(1.0, 150, QEasingCurve.OutBack)
            if not self.dragging:
                self._toggle_panel()
            else:
                self._snap_to_edge_animated()
            self.dragging = False
            self.reset_idle_timer()
            event.accept()

    def _snap_to_edge_animated(self):
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        pos = self.pos()
        cx = pos.x() + self.width() / 2
        cy = pos.y() + self.height() / 2

        margin = 12
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
            self._animate_pos(QPoint(new_x, new_y), duration=250)

    def enterEvent(self, event):
        self._animate_scale(1.12, 180, QEasingCurve.OutBack)
        self._start_show_animation()
        self.reset_idle_timer()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_scale(1.0, 150)
        self.reset_idle_timer()
        super().leaveEvent(event)

    def _toggle_panel(self):
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

            panel_w = 360
            panel_h = 480
            panel_x = panel_pos.x() + self.width() + 8
            panel_y = panel_pos.y() - (panel_h - self.height()) // 2

            if panel_x + panel_w > geo.width() - 4:
                panel_x = panel_pos.x() - panel_w - 8
            if panel_y + panel_h > geo.height() - 4:
                panel_y = geo.height() - panel_h - 4
            panel_y = max(4, panel_y)

            self._panel.show_panel(QPoint(panel_x, panel_y))
            self.reset_idle_timer()

    def _show_context_menu(self, global_pos):
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

        toggle_top_action = QAction(("取消置顶" if self.is_always_on_top else "置顶"), self)
        toggle_top_action.triggered.connect(self._toggle_always_on_top)
        menu.addAction(toggle_top_action)
        menu.addSeparator()
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self._exit_app)
        menu.addAction(exit_action)

        menu.exec_(global_pos)
        self.reset_idle_timer()

    def _toggle_always_on_top(self):
        self.is_always_on_top = not self.is_always_on_top
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.is_always_on_top:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self.reset_idle_timer()

    def _exit_app(self):
        try:
            self.audio_controller.unregister_session_callback()
        except Exception:
            pass
        QApplication.quit()

    def _on_volume_changed(self, key, value):
        self.audio_controller.set_volume_by_key(key, value)
        self.reset_idle_timer()

    def _on_mute_toggled(self, key, muted):
        self.audio_controller.set_mute_by_key(key, muted)
        self.reset_idle_timer()

    def _on_session_notification(self):
        if self._panel and self._panel.isVisible():
            QTimer.singleShot(300, self._refresh_panel)

    def _refresh_panel(self):
        if self._panel and self._panel.isVisible():
            self._panel.refresh_sessions()

    def closeEvent(self, event):
        try:
            self.audio_controller.unregister_session_callback()
        except Exception:
            pass
        super().closeEvent(event)
