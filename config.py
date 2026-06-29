"""Centralized runtime configuration and constants.

All user-tunable knobs and magic numbers live here so they can be reviewed
in one place. Values can be overridden at runtime by a JSON file at
``%APPDATA%/VolumeMixer/config.json`` on Windows (or
``~/.config/VolumeMixer/config.json`` elsewhere); see :func:`load_overrides`.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Tuple

LOGGER = logging.getLogger(__name__)

APP_NAME = "VolumeMixer"
APP_DISPLAY_NAME = "音量合成器助手"
APP_ORG = "VolumeMixer"
APP_VERSION = "1.0.0"

BALL_SIZE: int = 56
EDGE_MARGIN: int = 30
SNAP_MARGIN: int = 12
DRAG_THRESHOLD: int = 5
IDLE_HIDE_MS: int = 5000
PANEL_REFRESH_MS: int = 2000
SESSION_NOTIFY_REFRESH_DELAY_MS: int = 300
PANEL_W: int = 360
PANEL_H: int = 480
AVATAR_SIZE: int = 32
SLIDER_ROW_HEIGHT: int = 46
DEFAULT_MASTER_FALLBACK_VOLUME: int = 80
DEFAULT_SESSION_FALLBACK_VOLUME: int = 80

ANIM_HOVER_SCALE: float = 1.12
ANIM_PRESS_SCALE: float = 0.92
ANIM_HOVER_MS: int = 180
ANIM_PRESS_MS: int = 100
ANIM_RELEASE_MS: int = 150
ANIM_SNAP_MS: int = 250
ANIM_HIDE_MS: int = 300
ANIM_HIDE_OPACITY_MS: int = 250
ANIM_SHOW_MS: int = 220
ANIM_SHOW_OPACITY_MS: int = 180
ANIM_HIDDEN_OPACITY: float = 0.45
ANIM_VISIBLE_OPACITY: float = 1.0

LOW_VOLUME_THRESHOLD: int = 33
HIGH_VOLUME_THRESHOLD: int = 66

PALETTE: tuple = (
    (66, 133, 244), (219, 68, 55), (244, 180, 0), (15, 157, 88),
    (171, 71, 188), (0, 172, 193), (255, 112, 67), (120, 144, 156),
    (63, 81, 181), (0, 137, 123), (233, 30, 99), (103, 58, 183),
    (239, 83, 80), (0, 150, 136), (255, 160, 0), (46, 125, 50),
)

VOLUME_COLORS: Dict[str, tuple] = {
    "muted": ("#bdbdbd", "#9e9e9e"),
    "low":   ("#22c55e", "#16a34a"),
    "mid":   ("#4a9eff", "#2563eb"),
    "high":  ("#a855f7", "#7c3aed"),
}

ACCENT_BLUE: str = "#4a9eff"
ACCENT_BLUE_DARK: str = "#1a73e8"
ACCENT_BLUE_RGB: Tuple[int, int, int] = (74, 158, 255)

SINGLE_INSTANCE_MUTEX_NAME: str = "Global\\VolumeMixerSingleton"

HOTKEY_DEFAULT_ENABLED: bool = True
HOTKEY_DEFAULT_MODIFIERS: int = 0x0003
HOTKEY_DEFAULT_VK: int = 0x56

CONFIG_DEFAULTS: Dict[str, Any] = {
    "panel_refresh_ms": PANEL_REFRESH_MS,
    "idle_hide_ms": IDLE_HIDE_MS,
    "hotkey_enabled": HOTKEY_DEFAULT_ENABLED,
}


def _config_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / APP_NAME
    else:
        base = Path.home() / ".config" / APP_NAME
    return base / "config.json"


def load_overrides() -> Dict[str, Any]:
    path = _config_path()
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            LOGGER.warning("Config root is not a JSON object: %s", path)
            return {}
        return data
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Failed to read config %s: %s", path, exc)
        return {}


def apply_overrides(overrides: Dict[str, Any]) -> None:
    """Mutate module-level constants from the supplied dict.

    Only known keys with the correct value type are applied; unknown or
    mistyped entries are logged and ignored. This intentionally writes to the
    module globals so other modules importing the constants see the
    overridden values.
    """
    global PANEL_REFRESH_MS, IDLE_HIDE_MS
    for key, value in overrides.items():
        if key == "panel_refresh_ms" and isinstance(value, int) and value >= 250:
            PANEL_REFRESH_MS = value
        elif key == "idle_hide_ms" and isinstance(value, int) and value >= 500:
            IDLE_HIDE_MS = value
        else:
            LOGGER.debug("Ignoring unknown or invalid config key %r=%r", key, value)
