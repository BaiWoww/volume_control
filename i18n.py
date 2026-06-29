"""Centralized user-facing strings.

Keeps all UI text in one place so future translations via ``QTranslator`` can
swap the dictionary out without combing through the widgets. The current
language is Simplified Chinese.
"""

from __future__ import annotations

# Panel title and buttons
PANEL_TITLE = "\U0001F50A \u97F3\u91CF\u5408\u6210\u5668"  # "🔊 音量合成器"
REFRESH_BUTTON = "\u5237\u65B0"  # "刷新"
SECTION_APPLICATIONS = "\u5E94\u7528\u7A0B\u5E8F"  # "应用程序"

# Slider labels
MASTER_VOLUME_NAME = "\u7CFB\u7EDF\u4E3B\u97F3\u91CF"  # "系统主音量"
SYSTEM_SOUNDS_NAME = "\u7CFB\u7EDF\u58F0\u97F3"  # "系统声音"
MUTED_LABEL = "\u5DF2\u9759\u97F3"  # "已静音"
UNKNOWN_PROCESS_PREFIX = "\u8FDB\u7A0B "  # "进程 "

# Volume tier names (also used for tests)
TIER_MUTED = "muted"
TIER_LOW = "low"
TIER_MID = "mid"
TIER_HIGH = "high"

# Empty state
EMPTY_LIST = "\u6682\u65E0\u6B63\u5728\u64AD\u653E\u58F0\u97F3\u7684\u5E94\u7528"  # "暂无正在播放声音的应用"

# Context menu
MENU_PIN = "\u7F6E\u9876"  # "置顶"
MENU_UNPIN = "\u53D6\u6D88\u7F6E\u9876"  # "取消置顶"
MENU_EXIT = "\u9000\u51FA"  # "退出"

# Single-instance message (when a second instance is launched)
SINGLE_INSTANCE_MSG = "VolumeMixer \u5DF2\u5728\u8FD0\u884C\u3002"  # "VolumeMixer 已在运行。"

# Errors
ERROR_NO_PYTHON = "Error: Python not found. Please install Python 3.7 or later."  # (English; surfaced from a batch script to a terminal)
