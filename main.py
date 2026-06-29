import ctypes
import logging
import sys
from ctypes import wintypes

from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QRadialGradient, QPixmap
from PyQt5.QtWidgets import QApplication

import config
import logging_setup
import i18n
from audio_controller import AudioController
from floating_ball import FloatingBall


def _build_app_icon() -> QIcon:
    """Generate the application icon procedurally so no image asset is needed.

    The icon mirrors the floating ball's look-and-feel (blue glossy ball with a
    speaker glyph) at sizes 16, 32, 48, 64 and 256.
    """
    icon = QIcon()
    for size in (16, 32, 48, 64, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            cx = cy = size / 2
            r = (size / 2) - 1

            grad = QRadialGradient(cx, cy, r)
            grad.setColorAt(0, QColor(255, 255, 255))
            grad.setColorAt(0.85, QColor(240, 246, 255))
            grad.setColorAt(1, QColor(210, 228, 255))
            p.setPen(QPen(QColor(180, 210, 245), max(1.0, size / 64)))
            p.setBrush(QBrush(grad))
            p.drawEllipse(QPoint(int(cx), int(cy)), int(r), int(r))

            accent = QColor(*config.ACCENT_BLUE_RGB)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(accent))
            path = QPainterPath()
            icx = cx
            icy = cy
            scale = size / 64.0
            spk_w = 6 * scale
            spk_h = 9 * scale
            path.moveTo(icx - spk_w * 0.5, icy - spk_h * 0.2)
            path.lineTo(icx - spk_w * 0.12, icy - spk_h * 0.2)
            path.lineTo(icx + spk_w * 0.32, icy - spk_h * 0.78)
            path.lineTo(icx + spk_w * 0.32, icy + spk_h * 0.78)
            path.lineTo(icx - spk_w * 0.12, icy + spk_h * 0.2)
            path.lineTo(icx - spk_w * 0.5, icy + spk_h * 0.2)
            path.closeSubpath()
            p.drawPath(path)
        finally:
            p.end()
        icon.addPixmap(pm)
    return icon


def _acquire_single_instance() -> bool:
    """Try to acquire the named mutex for single-instance enforcement.

    Returns True if this is the only running instance, False if another
    instance is already running. The mutex handle is stored on the
    :mod:`config` module to keep it alive for the process lifetime.
    """
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        ERROR_ALREADY_EXISTS = 183
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.GetLastError.argtypes = []
        kernel32.GetLastError.restype = wintypes.DWORD
        handle = kernel32.CreateMutexW(None, False, config.SINGLE_INSTANCE_MUTEX_NAME)
        if not handle:
            logging.getLogger(__name__).warning("CreateMutexW returned NULL; "
                                                "proceeding without single-instance guard")
            return True
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        config._SINGLE_INSTANCE_HANDLE = handle  # type: ignore[attr-defined]
        return True
    except Exception:
        logging.getLogger(__name__).exception("Single-instance check failed; "
                                              "proceeding without guard")
        return True


def main():
    logging_setup.setup()
    config.apply_overrides(config.load_overrides())
    logging_setup.install_excepthook()

    if not _acquire_single_instance():
        logger = logging.getLogger(__name__)
        logger.info("Another instance is already running; exiting")
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
    app.setWindowIcon(_build_app_icon())

    audio_controller = AudioController()
    ball = FloatingBall(audio_controller)
    ball.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
