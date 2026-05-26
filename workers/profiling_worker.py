# workers/profiling_worker.py

from PySide6.QtCore import QObject
from PySide6.QtCore import Signal
from PySide6.QtCore import Slot

from services.profiling_service import (
    ProfilingService
)


class ProfilingWorker(QObject):
    """
    Background dataset profiling worker.
    """

    finished = Signal(list)

    error = Signal(str)

    progress = Signal(str)

    def __init__(self, dataset_files):
        super().__init__()

        self.dataset_files = dataset_files

        self.profiling_service = ProfilingService()

    # =========================================================
    # Worker Entry
    # =========================================================

    @Slot()
    def run(self):
        """
        Execute profiling workflow.
        """

        profiles = []

        try:

            for file_path in self.dataset_files:

                self.progress.emit(
                    f"Profiling: {file_path}"
                )

                profile = (
                    self.profiling_service
                    .generate_profile(file_path)
                )

                profiles.append(profile)

            self.finished.emit(profiles)

        except Exception as error:

            self.error.emit(str(error))