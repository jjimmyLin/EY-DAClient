"""Compatibility application container for callers using ``app.app``."""

from ui.main_window import MainWindow


class Application:
    """
    Main application container.

    The current ``MainWindow`` owns its workflow workers and signal wiring.
    This small wrapper remains for compatibility with older launchers.
    """

    def __init__(self):
        self.main_window = None

        self._initialize()

    # =========================================================
    # Initialization
    # =========================================================

    def _initialize(self):
        """
        Initialize application components.
        """

        self.main_window = MainWindow()

    # =========================================================
    # Public API
    # =========================================================

    def show(self):
        """
        Show application window.
        """

        self.main_window.show()
