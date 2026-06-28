import sys
import traceback

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from audio_controller import AudioController
from floating_ball import FloatingBall


def exception_hook(exctype, value, tb):
    traceback.print_exception(exctype, value, tb)
    sys.__excepthook__(exctype, value, tb)


def main():
    sys.excepthook = exception_hook

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    audio_controller = AudioController()
    ball = FloatingBall(audio_controller)
    ball.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
