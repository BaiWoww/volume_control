"""Sanity tests for the :mod:`i18n` text catalogue."""

from __future__ import annotations

import i18n


def test_panel_title_non_empty():
    assert i18n.PANEL_TITLE and len(i18n.PANEL_TITLE) > 0


def test_menu_pin_unpin_differ():
    assert i18n.MENU_PIN != i18n.MENU_UNPIN


def test_all_constants_are_strings():
    for name in dir(i18n):
        if name.startswith("_"):
            continue
        value = getattr(i18n, name)
        if isinstance(value, str):
            assert value, f"{name} is empty"
