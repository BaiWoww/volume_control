"""Tests for pure helper functions (no Qt / no COM)."""

from __future__ import annotations

import pytest

import i18n
from volume_panel import _color_for_name, _volume_tier
import config


# ---- _volume_tier -----------------------------------------------------------

@pytest.mark.parametrize("vol,muted,expected", [
    (0,   False, i18n.TIER_LOW),
    (33,  False, i18n.TIER_LOW),
    (34,  False, i18n.TIER_MID),
    (50,  False, i18n.TIER_MID),
    (66,  False, i18n.TIER_MID),
    (67,  False, i18n.TIER_HIGH),
    (100, False, i18n.TIER_HIGH),
    (0,   True,  i18n.TIER_MUTED),
    (100, True,  i18n.TIER_MUTED),
])
def test_volume_tier_boundaries(vol, muted, expected):
    assert _volume_tier(vol, muted) == expected


def test_volume_tier_low_threshold_respects_config():
    """Adjusting LOW_VOLUME_THRESHOLD changes the tier boundary."""
    original = config.LOW_VOLUME_THRESHOLD
    try:
        config.LOW_VOLUME_THRESHOLD = 10
        assert _volume_tier(10, False) == "low"   # boundary is inclusive
        assert _volume_tier(11, False) == "mid"
        assert _volume_tier(9,  False) == "low"
    finally:
        config.LOW_VOLUME_THRESHOLD = original


# ---- _color_for_name --------------------------------------------------------

def test_color_for_name_empty_returns_first():
    assert _color_for_name("") == config.PALETTE[0]


def test_color_for_name_whitespace_returns_first():
    assert _color_for_name("   ") == config.PALETTE[0]


def test_color_for_name_deterministic():
    """Same input must always produce the same RGB triple."""
    assert _color_for_name("chrome") == _color_for_name("chrome")
    assert _color_for_name("chrome") == _color_for_name("Chrome")
    assert _color_for_name("chrome") == _color_for_name("  CHROME  ")


def test_color_for_name_in_palette():
    color = _color_for_name("Microsoft Outlook")
    assert color in config.PALETTE


def test_color_for_name_distinct_inputs_likely_different():
    """Different names should not all hash to the same color (probabilistic)."""
    seen = {_color_for_name(name) for name in
            ["chrome", "firefox", "edge", "spotify", "discord",
             "steam", "telegram", "wechat", "code", "powershell"]}
    # Allow at most a few collisions in a 16-colour palette.
    assert len(seen) >= 7
