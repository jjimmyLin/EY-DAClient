# services/profiling_service.py

from core.profiler.dataset_profiler import (
    DatasetProfiler
)


class ProfilingService:
    """
    Dataset profiling service.

    Responsible for:
    - Managing dataset profiling workflow
    - Calling profiler engine
    """

    def __init__(self):
        self.profiler = DatasetProfiler()

    # =========================================================
    # Public API
    # =========================================================

    def generate_profile(self, file_path):
        """
        Generate dataset profile.

        Parameters
        ----------
        file_path : str

        Returns
        -------
        dict
        """

        profile = self.profiler.profile(file_path)

        return profile