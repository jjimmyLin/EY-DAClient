# app/main.py

import sys

from PySide6.QtWidgets import QApplication

from app.app import Application

def main():
    """
    Application entry point.
    """

    app = QApplication(sys.argv)

    application = Application()
    application.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()