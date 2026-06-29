"""Volume mixer panel.

A frameless popup with the master volume slider at the top, a scrollable
list of per-application sliders below, and a refresh button. Sessions are
enumerated every ``config.PANEL_REFRESH_MS`` while visible and the list is
updated incrementally so the panel never flickers.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple, Union

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QSlider, QPushButton, QScrollArea, QFrame)
from PyQt5.QtCore import (Qt, pyqtSignal, QTimer, QEasingCurve, QPropertyAnimation,
                          QPoint, QEvent)
from PyQt5.QtGui import (QPainter, QColor, QBrush, QPen, QFont, QRadialGradient,
                         QShowEvent, QHideEvent, QPaintEvent)

import config
import i18n

LOGGER = logging.getLogger(__name__)

# Backwards-compat aliases; canonical values live in :mod:`config`.
PANEL_W = config.PANEL_W
PANEL_H = config.PANEL_H
PALETTE = config.PALETTE
VOLUME_COLORS = config.VOLUME_COLORS
LOW_VOLUME_THRESHOLD = config.LOW_VOLUME_THRESHOLD
HIGH_VOLUME_THRESHOLD = config.HIGH_VOLUME_THRESHOLD


def _color_for_name(name: str) -> Tuple[int, int, int]:
    s = name.strip().lower()
    if not s:
        return PALETTE[0]
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return PALETTE[h % len(PALETTE)]


class AppAvatar(QWidget):
    def __init__(self, name: str, is_system: bool = False,
                 is_master: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.is_system = is_system
        self.is_master = is_master
        self.name = name
        self._letter: str = self._pick_letter(name)
        self.r, self.g, self.b = self._pick_color()
        self.setFixedSize(config.AVATAR_SIZE, config.AVATAR_SIZE)

    def _pick_letter(self, name: str) -> str:
        if self.is_system:
            return "!"
        if self.is_master:
            return "V"
        s = name.strip()
        for ch in s:
            if ch.isalnum() and ord(ch) < 0x4e00:
                return ch.upper()
        for ch in s:
            if ch.isalnum():
                return ch.upper()
        return "M"

    def _pick_color(self) -> Tuple[int, int, int]:
        if self.is_system:
            return (255, 183, 77)
        if self.is_master:
            return (config.ACCENT_BLUE_RGB if hasattr(config, "ACCENT_BLUE_RGB") else (74, 158, 255))
        return _color_for_name(self.name)

    def paintEvent(self, e: QPaintEvent) -> None:  # noqa: D401 - Qt override
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        r = 16

        grad = QRadialGradient(cx - 3, cy - 4, r * 1.2)
        grad.setColorAt(0, QColor(min(255, self.r + 40), min(255, self.g + 40), min(255, self.b + 40)))
        grad.setColorAt(1, QColor(self.r, self.g, self.b))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPoint(int(cx), int(cy)), int(r), int(r))

        hi = QRadialGradient(cx - 5, cy - 6, r * 0.9)
        hi.setColorAt(0, QColor(255, 255, 255, 100))
        hi.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(hi))
        p.drawEllipse(QPoint(int(cx - 2), int(cy - 3)), int(r * 0.7), int(r * 0.55))

        p.setPen(QPen(QColor(255, 255, 255, 220)))
        f = QFont()
        f.setPixelSize(14)
        f.setBold(True)
        p.setFont(f)
        if self.is_system:
            p.drawText(self.rect(), Qt.AlignCenter, "\U0001F514")
        elif self.is_master:
            p.drawText(self.rect(), Qt.AlignCenter, "\U0001F50A")
        else:
            p.drawText(self.rect(), Qt.AlignCenter, self._letter)


def _volume_tier(vol: int, muted: bool) -> str:
    if muted:
        return "muted"
    if vol <= config.LOW_VOLUME_THRESHOLD:
        return "low"
    if vol <= config.HIGH_VOLUME_THRESHOLD:
        return "mid"
    return "high"


def _slider_stylesheet(tier: str) -> str:
    c1, c2 = VOLUME_COLORS[tier]
    return f"""
        QSlider::groove:horizontal {{
            height: 6px;
            background: #e8ecf2;
            border-radius: 3px;
        }}
        QSlider::handle:horizontal {{
            background: {c1};
            width: 14px;
            height: 14px;
            margin: -5px 0;
            border-radius: 7px;
            border: 2px solid white;
        }}
        QSlider::handle:horizontal:hover {{
            background: {c2};
        }}
        QSlider::sub-page:horizontal {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {c1}, stop:1 {c2});
            border-radius: 3px;
        }}
    """


SessionKey = Union[str, int]


class VolumeSlider(QFrame):
    volume_changed = pyqtSignal(int)
    mute_toggled = pyqtSignal(bool)

    def __init__(self, name: str, volume: int, mute: bool,
                 is_system: bool = False, is_master: bool = False,
                 key: Optional[SessionKey] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.name = name
        self.is_muted = mute
        self.is_system = is_system
        self.is_master = is_master
        self.key: Optional[SessionKey] = key
        fallback = config.DEFAULT_MASTER_FALLBACK_VOLUME if is_master else config.DEFAULT_SESSION_FALLBACK_VOLUME
        if volume is None:
            safe_volume = fallback
        else:
            safe_volume = volume
        self._last_volume: int = safe_volume if not mute else max(safe_volume, fallback)
        self._tier: str = _volume_tier(safe_volume, mute)
        self._sliding: bool = False
        self._setup_ui(name, safe_volume, mute)

    def _setup_ui(self, name: str, volume: int, mute: bool) -> None:
        self.setFixedHeight(config.SLIDER_ROW_HEIGHT)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("VolumeSlider:hover { background: rgba(74, 158, 255, 22); border-radius: 8px; }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 10, 4)
        layout.setSpacing(10)

        self.avatar = AppAvatar(name, is_system=self.is_system, is_master=self.is_master)

        self.mute_btn = QPushButton()
        self.mute_btn.setFixedSize(26, 26)
        self.mute_btn.setCursor(Qt.PointingHandCursor)

        name_layout = QVBoxLayout()
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(0)

        self.label = QLabel(name)
        if self.is_system:
            self.label.setStyleSheet("color: #b8860b; font-size: 12px; font-weight: bold; background: transparent;")
        elif self.is_master:
            self.label.setStyleSheet("color: #1a73e8; font-size: 12px; font-weight: bold; background: transparent;")
        else:
            self.label.setStyleSheet("color: #1a1a1a; font-size: 12px; background: transparent;")

        self.value_label = QLabel()
        self.value_label.setStyleSheet("color: #888; font-size: 10px; background: transparent;")
        self.value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        name_layout.addWidget(self.label)
        name_layout.addWidget(self.value_label)
        name_w = QWidget()
        name_w.setStyleSheet("background: transparent;")
        name_w.setLayout(name_layout)
        name_w.setFixedWidth(110)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setMinimumWidth(100)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.setStyleSheet("background: transparent;")

        self.mute_btn.setFixedWidth(26)
        self.mute_btn.setStyleSheet("background: transparent;")
        layout.addWidget(self.avatar)
        layout.addWidget(name_w)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.mute_btn)

        self.slider.valueChanged.connect(self._on_volume_changed)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.mute_btn.clicked.connect(self._toggle_mute)
        self._update_visuals(0 if mute else volume, mute, initial=True)

    def _update_visuals(self, vol: int, muted: bool, initial: bool = False) -> None:
        new_tier = _volume_tier(vol, muted)
        if new_tier != self._tier or initial:
            self._tier = new_tier
            self.slider.setStyleSheet(_slider_stylesheet(new_tier))
        if not self._sliding:
            self.slider.blockSignals(True)
            self.slider.setValue(0 if muted else vol)
            self.slider.blockSignals(False)

        self.is_muted = muted
        if muted:
            self.mute_btn.setText("🔇")
            self.mute_btn.setStyleSheet("""
                QPushButton {
                    background: #fde8e8;
                    color: #dc2626;
                    border-radius: 13px;
                    border: none;
                    font-size: 13px;
                }
                QPushButton:hover { background: #f87171; color: white; }
            """)
            self.value_label.setText(i18n.MUTED_LABEL)
            self.value_label.setStyleSheet("color: #dc2626; font-size: 10px; background: transparent;")
        else:
            self.mute_btn.setText("🔊")
            self.mute_btn.setStyleSheet("""
                QPushButton {
                    background: #e8f2ff;
                    color: #1a73e8;
                    border-radius: 13px;
                    border: none;
                    font-size: 13px;
                }
                QPushButton:hover { background: #4a9eff; color: white; }
            """)
            self.value_label.setText(f"{vol}%")
            self.value_label.setStyleSheet("color: #888; font-size: 10px; background: transparent;")

    def _on_slider_pressed(self) -> None:
        self._sliding = True

    def _on_slider_released(self) -> None:
        self._sliding = False

    def _toggle_mute(self) -> None:
        new_mute = not self.is_muted
        self._update_visuals(0 if new_mute else self._last_volume, new_mute)
        self.mute_toggled.emit(new_mute)
        if not new_mute:
            restore = self._last_volume if self._last_volume > 0 else config.DEFAULT_MASTER_FALLBACK_VOLUME
            self.volume_changed.emit(restore)

    def _on_volume_changed(self, value: int) -> None:
        if self.is_muted and value > 0:
            self._update_visuals(value, False)
        else:
            new_tier = _volume_tier(value, False)
            if new_tier != self._tier:
                self._tier = new_tier
                self.slider.setStyleSheet(_slider_stylesheet(new_tier))
            self.value_label.setText(f"{value}%")
        if not self.is_muted:
            self._last_volume = value
        self.volume_changed.emit(value)

    def set_volume_external(self, volume: Optional[int], mute: bool) -> None:
        if self._sliding or volume is None:
            return
        self._update_visuals(volume, mute)
        if not mute:
            self._last_volume = volume


class VolumePanel(QWidget):
    volume_changed = pyqtSignal(object, int)
    mute_toggled = pyqtSignal(object, bool)
    panel_closed = pyqtSignal()

    def __init__(self, audio_controller, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.audio_controller = audio_controller
        self.app_sliders: Dict[SessionKey, "VolumeSlider"] = {}
        self._empty_label: Optional[QLabel] = None
        self._show_anim: Optional[QPropertyAnimation] = None
        self._hide_anim: Optional[QPropertyAnimation] = None
        self._closing: bool = False
        self._hide_in_progress: bool = False
        self._first_populate: bool = True
        self.master_key: SessionKey = "master"

        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(0)
        self._setup_ui()
        self._setup_refresh_timer()

    def _setup_ui(self) -> None:
        self.setFixedSize(PANEL_W, PANEL_H)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        self.container = QWidget(self)
        self.container.setObjectName("panelContainer")
        self.container.setStyleSheet("""
            QWidget#panelContainer {
                background: rgba(252, 253, 255, 248);
                border-radius: 16px;
                border: 1px solid #d0e3ff;
            }
            QLabel#titleLabel {
                color: #1a73e8;
                font-size: 15px;
                font-weight: bold;
                background: transparent;
            }
            QLabel#sectionLabel {
                color: #6b7280;
                font-size: 11px;
                padding: 6px 4px 4px 4px;
                font-weight: 600;
                letter-spacing: 0.5px;
                background: transparent;
            }
            QPushButton#refreshBtn {
                background: white;
                color: #1a73e8;
                border: 1px solid #b3d4ff;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton#refreshBtn:hover {
                background: #e8f2ff;
                border-color: #4a9eff;
            }
            QFrame#separator {
                background: #e5eaf2;
                max-height: 1px;
                min-height: 1px;
                border: none;
            }
        """)
        outer.addWidget(self.container)

        cl = QVBoxLayout(self.container)
        cl.setContentsMargins(14, 14, 14, 14)
        cl.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel(i18n.PANEL_TITLE)
        title.setObjectName("titleLabel")

        self.refresh_btn = QPushButton(i18n.REFRESH_BUTTON)
        self.refresh_btn.setObjectName("refreshBtn")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh_sessions)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.refresh_btn)
        cl.addLayout(header)

        sep1 = QFrame()
        sep1.setObjectName("separator")
        sep1.setFrameShape(QFrame.HLine)
        cl.addWidget(sep1)

        self.master_key = "master"
        master_vol = self.audio_controller.get_master_volume()
        master_mute = self.audio_controller.get_master_mute()
        if master_vol is None:
            master_vol = config.DEFAULT_MASTER_FALLBACK_VOLUME
        if master_mute is None:
            master_mute = False
        self.master_slider = VolumeSlider(
            i18n.MASTER_VOLUME_NAME,
            master_vol,
            master_mute,
            is_system=False,
            is_master=True,
            key=self.master_key,
        )
        self.master_slider.volume_changed.connect(lambda v: self.volume_changed.emit(self.master_key, v))
        self.master_slider.mute_toggled.connect(lambda m: self.mute_toggled.emit(self.master_key, m))
        cl.addWidget(self.master_slider)

        sep2 = QFrame()
        sep2.setObjectName("separator")
        sep2.setFrameShape(QFrame.HLine)
        cl.addWidget(sep2)

        app_label = QLabel(i18n.SECTION_APPLICATIONS)
        app_label.setObjectName("sectionLabel")
        cl.addWidget(app_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                border-radius: 4px;
                margin: 4px 0;
            }
            QScrollBar::handle:vertical {
                background: #c0d4f0;
                border-radius: 4px;
                min-height: 24px;
                margin: 0 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4a9eff;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)

        self.apps_container = QWidget()
        self.apps_container.setStyleSheet("background: transparent;")
        self.apps_layout = QVBoxLayout(self.apps_container)
        self.apps_layout.setContentsMargins(0, 0, 0, 0)
        self.apps_layout.setSpacing(2)
        self.apps_layout.addStretch()

        scroll.setWidget(self.apps_container)
        cl.addWidget(scroll, 1)

    def _setup_refresh_timer(self) -> None:
        self.timer = QTimer(self)
        self.timer.setInterval(config.PANEL_REFRESH_MS)
        self.timer.timeout.connect(self.refresh_sessions)

    def refresh_sessions(self) -> None:
        if not self.isVisible() or self._closing:
            return
        try:
            master_vol = self.audio_controller.get_master_volume()
            master_mute = self.audio_controller.get_master_mute()
            self.master_slider.set_volume_external(master_vol, master_mute)
            self._populate_apps()
        except Exception:
            LOGGER.exception("refresh_sessions failed")

    def showEvent(self, event: QShowEvent) -> None:
        self.timer.start()
        self.refresh_sessions()
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:
        self.timer.stop()
        if not self._closing and not self._hide_in_progress:
            self.panel_closed.emit()
        super().hideEvent(event)

    def _populate_apps(self) -> None:
        sessions = self.audio_controller.get_all_sessions()
        new_keys = {s["key"]: s for s in sessions}

        for key in list(self.app_sliders.keys()):
            if key not in new_keys:
                w = self.app_sliders.pop(key)
                w.deleteLater()
            else:
                s = new_keys[key]
                self.app_sliders[key].set_volume_external(s["volume"], s["mute"])

        for sess in sessions:
            if sess["key"] in self.app_sliders:
                continue
            slider = VolumeSlider(
                sess["display_name"],
                sess["volume"],
                sess["mute"],
                is_system=sess["is_system"],
                key=sess["key"],
            )
            k = sess["key"]
            slider.volume_changed.connect(lambda v, key=k: self.volume_changed.emit(key, v))
            slider.mute_toggled.connect(lambda m, key=k: self.mute_toggled.emit(key, m))
            self.app_sliders[k] = slider
            self.apps_layout.insertWidget(self.apps_layout.count() - 1, slider)

        has_apps = len(sessions) > 0
        if has_apps and self._empty_label is not None:
            self._empty_label.deleteLater()
            self._empty_label = None
        elif not has_apps and self._empty_label is None:
            self._empty_label = QLabel(i18n.EMPTY_LIST)
            self._empty_label.setAlignment(Qt.AlignCenter)
            self._empty_label.setStyleSheet("color: #b0b8c4; font-size: 12px; padding: 30px 10px; background: transparent;")
            self.apps_layout.insertWidget(self.apps_layout.count() - 1, self._empty_label)

    def show_panel(self, pos: QPoint) -> None:
        self._closing = False
        self._hide_in_progress = False
        if self._hide_anim is not None:
            try:
                self._hide_anim.stop()
            except Exception:
                LOGGER.exception("Failed to stop hide animation in show_panel")
        self.setWindowOpacity(0)
        self.move(pos)
        self.show()
        opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        opacity_anim.setDuration(180)
        opacity_anim.setStartValue(0)
        opacity_anim.setEndValue(1)
        opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._show_anim = opacity_anim
        opacity_anim.start()

    def hide_panel(self) -> None:
        if not self.isVisible() or self._closing or self._hide_in_progress:
            return
        self._closing = True
        self._hide_in_progress = True
        if self._show_anim is not None:
            self._show_anim.stop()
        opacity_anim = QPropertyAnimation(self, b"windowOpacity", self)
        opacity_anim.setDuration(150)
        opacity_anim.setStartValue(self.windowOpacity())
        opacity_anim.setEndValue(0)
        opacity_anim.setEasingCurve(QEasingCurve.InQuad)

        def _on_done() -> None:
            self._hide_in_progress = False
            self.hide()
            self._closing = False
            self.panel_closed.emit()
        opacity_anim.finished.connect(_on_done)
        self._hide_anim = opacity_anim
        opacity_anim.start()
