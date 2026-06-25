from pathlib import Path
import tempfile

import duckdb
import pandas as pd
import pyarrow

from core.data_access import LocalDataCatalog


with tempfile.TemporaryDirectory() as temp_dir:
    parquet_path = Path(temp_dir) / "smoke.parquet"
    pd.DataFrame({"id": [1, 2], "value": [10, 20]}).to_parquet(
        parquet_path,
        index=False,
    )
    manifest = [
        {
            "dataset_id": "ds_smoke",
            "aliases": [],
            "sheets": [
                {
                    "sheet_id": "sh_smoke",
                    "name": "Data",
                    "cache_path": str(parquet_path),
                    "sample_cache_path": str(parquet_path),
                }
            ],
        }
    ]
    catalog = LocalDataCatalog(manifest)
    frame = catalog.get("ds_smoke", "sh_smoke", columns=["value"])
    result = catalog.sql(
        "SELECT SUM(value) AS total FROM source",
        sources={"source": ("ds_smoke", "sh_smoke")},
    )
    assert frame["value"].sum() == 30
    assert result.iloc[0]["total"] == 30
    assert duckdb.sql("SELECT 1").fetchone()[0] == 1
    assert pyarrow.__version__
