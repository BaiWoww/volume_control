"""Shared pytest configuration and fixtures."""

from __future__ import annotations

import os
import sys

import pytest

# Ensure the project root is on sys.path so ``import config`` etc. works
# regardless of where pytest is launched.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Force the offscreen platform so the test suite never opens a real window.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """Provide a single QApplication for the whole test session."""
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    return app
