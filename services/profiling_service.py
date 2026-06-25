"""Compatibility profiling service backed by the current preprocessor."""

from core.preprocessor import Preprocessor


class ProfilingService:
    """
    Dataset profiling service.

    Responsible for:
    - Managing dataset profiling workflow
    - Calling profiler engine
    """

    def __init__(self):
        self.preprocessor = Preprocessor()

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

        file_meta = self.preprocessor.process(file_path)
        return file_meta.to_prompt_dict()
