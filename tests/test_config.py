"""Tests for :mod:`config`."""

from __future__ import annotations

import config


def test_apply_overrides_accepts_known_keys():
    original = config.PANEL_REFRESH_MS
    try:
        config.apply_overrides({"panel_refresh_ms": 5000})
        assert config.PANEL_REFRESH_MS == 5000
    finally:
        config.PANEL_REFRESH_MS = original


def test_apply_overrides_rejects_too_small_panel_refresh():
    original = config.PANEL_REFRESH_MS
    try:
        config.apply_overrides({"panel_refresh_ms": 10})  # below 250ms minimum
        assert config.PANEL_REFRESH_MS == original
    finally:
        config.PANEL_REFRESH_MS = original


def test_apply_overrides_ignores_unknown_keys():
    original_idle = config.IDLE_HIDE_MS
    try:
        config.apply_overrides({"totally_made_up_key": 12345})
        assert config.IDLE_HIDE_MS == original_idle
    finally:
        config.IDLE_HIDE_MS = original_idle


def test_apply_overrides_ignores_wrong_types():
    original = config.PANEL_REFRESH_MS
    try:
        config.apply_overrides({"panel_refresh_ms": "not a number"})
        assert config.PANEL_REFRESH_MS == original
    finally:
        config.PANEL_REFRESH_MS = original
