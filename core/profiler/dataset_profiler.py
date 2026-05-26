# core/profiler/dataset_profiler.py

from pathlib import Path

import pandas as pd


class DatasetProfiler:
    """
    Dataset profiling engine.

    Responsible for:
    - Reading datasets
    - Extracting metadata
    - Generating compact dataset profile
    """

    SAMPLE_ROWS = 5

    def profile(self, file_path):
        """
        Generate dataset profile.

        Parameters
        ----------
        file_path : str

        Returns
        -------
        dict
        """

        path = Path(file_path)

        dataframe = self._load_dataframe(path)

        profile = {
            "file_name": path.name,
            "file_size_mb": round(
                path.stat().st_size / (1024 * 1024),
                2
            ),
            "row_count": int(dataframe.shape[0]),
            "column_count": int(dataframe.shape[1]),
            "columns": dataframe.columns.tolist(),
            "dtypes": {
                column: str(dtype)
                for column, dtype in dataframe.dtypes.items()
            },
            "null_ratio": {
                column: round(
                    float(dataframe[column].isnull().mean()),
                    4
                )
                for column in dataframe.columns
            },
            "sample_rows": dataframe.head(
                self.SAMPLE_ROWS
            ).to_dict(orient="records")
        }

        return profile

    # =========================================================
    # Internal
    # =========================================================

    def _load_dataframe(self, path):
        """
        Load dataframe from file.
        """

        suffix = path.suffix.lower()

        if suffix == ".csv":
            return pd.read_csv(path)

        if suffix in [".xlsx", ".xls"]:
            return pd.read_excel(path)

        raise ValueError(
            f"Unsupported file format: {suffix}"
        )