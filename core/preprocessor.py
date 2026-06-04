"""
core/preprocessor.py
────────────────────
Excel 文件预处理器。
提取轻量级元数据，不加载原始数据。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import pandas as pd
from config.settings import settings


@dataclass
class SheetMeta:
    """单个 Sheet 的元数据"""
    sheet_name: str
    rows: int
    cols: int
    columns: list[str]
    dtypes: dict[str, str]
    null_counts: dict[str, int]
    head_sample: list[dict[str, Any]]
    describe: dict[str, Any]

    def to_prompt_dict(self) -> dict:
        """转换为可发送给 Dify 的格式"""
        return {
            "sheet": self.sheet_name,
            "shape": f"{self.rows} 行 × {self.cols} 列",
            "columns": self.columns,
            "dtypes": self.dtypes,
            "null_counts": self.null_counts,
            "sample": self.head_sample,
            "describe": self.describe,
        }


@dataclass
class FileMeta:
    """单个 Excel 文件的完整元数据"""
    file_path: str
    file_name: str
    file_size_kb: float
    sheet_count: int
    sheets: list[SheetMeta] = field(default_factory=list)

    def to_prompt_dict(self) -> dict:
        """转换为可发送给 Dify 的格式"""
        return {
            "file": self.file_name,
            "size_kb": round(self.file_size_kb, 1),
            "sheets": [s.to_prompt_dict() for s in self.sheets],
        }


class Preprocessor:
    """Excel 文件预处理"""
    
    def __init__(self) -> None:
        self._preview_rows = settings.PREVIEW_ROWS
        self._max_cols_describe = settings.MAX_COLS_DESCRIBE

    def process(self, file_path: str) -> FileMeta:
        """
        主入口：处理 Excel 文件并返回元数据。
        
        Args:
            file_path: Excel 文件的完整路径
            
        Returns:
            FileMeta 对象
            
        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 不支持的文件格式
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        if path.suffix.lower() not in {".xlsx", ".xls", ".xlsm"}:
            raise ValueError(f"不支持的文件格式: {path.suffix}")

        size_kb = path.stat().st_size / 1024
        xl = pd.ExcelFile(file_path)
        sheets = [self._process_sheet(xl, name) for name in xl.sheet_names]

        return FileMeta(
            file_path=str(path.resolve()),
            file_name=path.name,
            file_size_kb=size_kb,
            sheet_count=len(sheets),
            sheets=sheets,
        )

    def _process_sheet(self, xl: pd.ExcelFile, sheet_name: str) -> SheetMeta:
        """处理单个 Sheet"""
        df = xl.parse(sheet_name)

        # 数值列统计摘要
        numeric_cols = df.select_dtypes(include="number").columns
        if len(numeric_cols) > self._max_cols_describe:
            numeric_cols = numeric_cols[:self._max_cols_describe]
        
        describe_raw = (
            df[numeric_cols].describe().to_dict() 
            if len(numeric_cols) > 0 
            else {}
        )
        describe = {
            col: {k: round(v, 4) for k, v in stats.items()}
            for col, stats in describe_raw.items()
        }

        return SheetMeta(
            sheet_name=sheet_name,
            rows=len(df),
            cols=len(df.columns),
            columns=list(df.columns.astype(str)),
            dtypes={
                str(col): str(dtype) 
                for col, dtype in df.dtypes.items()
            },
            null_counts={
                str(col): int(n)
                for col, n in df.isnull().sum().items()
                if n > 0
            },
            head_sample=df.head(self._preview_rows)
            .fillna("")
            .astype(str)
            .to_dict(orient="records"),
            describe=describe,
        )