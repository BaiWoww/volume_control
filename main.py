"""Application entry point.

Configures logging, enforces single-instance, sets up the QApplication
metadata and Fusion style, loads the bundled application icon, and hands
off to :class:`floating_ball.FloatingBall`.
"""

import logging
import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication

import config
import i18n
import logging_setup
import single_instance
from audio_controller import AudioController
from floating_ball import FloatingBall

_ICON_FILE = "icon.ico"


def _assets_dir() -> Path:
    """Return the directory that contains bundled asset files.

    When running from source the assets live next to ``main.py``. When the
    app is frozen by PyInstaller, the bundle is unpacked into
    ``sys._MEIPASS`` and the assets are placed there as well.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "assets"
    return Path(__file__).resolve().parent / "assets"


def _load_app_icon() -> QIcon:
    """Load the application icon from ``assets/icon.ico``.

    Returns an empty :class:`QIcon` if the file is missing so the caller
    can still set it on the QApplication without special-casing.
    """
    ico = _assets_dir() / _ICON_FILE
    return QIcon(str(ico))


def main():
    logging_setup.setup()
    config.apply_overrides(config.load_overrides())
    logging_setup.install_excepthook()

    logger = logging.getLogger(__name__)

    if not single_instance.acquire_mutex(config.SINGLE_INSTANCE_MUTEX_NAME):
        logger.info("Another instance is already running; notifying it to show")
        single_instance.notify_running_instance(config.PIPE_NAME)
        print(i18n.SINGLE_INSTANCE_MSG, file=sys.stderr)
        sys.exit(0)

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(config.APP_NAME)
    app.setApplicationDisplayName(config.APP_DISPLAY_NAME)
    app.setApplicationVersion(config.APP_VERSION)
    app.setOrganizationName(config.APP_ORG)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(_load_app_icon())

    audio_controller = AudioController()
    ball = FloatingBall(audio_controller)
    ball.show()

    pipe_server = single_instance.PipeServer()
    pipe_server.start(config.PIPE_NAME, ball.show_requested.emit)

    exit_code = app.exec_()
    pipe_server.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
