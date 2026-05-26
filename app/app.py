# app/app.py

from ui.main_window import MainWindow
from controllers.workflow_controller import WorkflowController


class Application:
    """
    Main application container.

    Responsible for:
    - Initializing UI
    - Initializing controllers
    - Dependency wiring
    """

    def __init__(self):
        self.main_window = None

        self.workflow_controller = None

        self._initialize()

    # =========================================================
    # Initialization
    # =========================================================

    def _initialize(self):
        """
        Initialize application components.
        """

        # Create Main Window
        self.main_window = MainWindow()

        # Create Controllers
        self.workflow_controller = WorkflowController(
            self.main_window
        )

    # =========================================================
    # Public API
    # =========================================================

    def show(self):
        """
        Show application window.
        """

        self.main_window.show()