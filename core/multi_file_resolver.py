"""
core/multi_file_resolver.py
──────────────────────────
检测多个 Excel 文件间的潜在关联。
识别可能的 JOIN 键。

Sprint 2 🔵
"""

from __future__ import annotations
from core.preprocessor import FileMeta


class MultiFileResolver:
    """多文件关联解析器"""

    def resolve(self, files: list[FileMeta]) -> dict:
        """
        分析多个文件的列名，检测潜在的 JOIN 键。
        
        场景：用户上传了 sales.xlsx 和 customers.xlsx
        如果两个文件都有 "customer_id" 列，就可以 JOIN。
        
        Args:
            files: FileMeta 列表
            
        Returns:
            包含潜在 JOIN 关系的字典
            
        Example:
            {
              "potential_joins": [
                {
                  "files": ["sales.xlsx", "customers.xlsx"],
                  "key": "customer_id"
                }
              ]
            }
        """
        if len(files) < 2:
            return {"potential_joins": []}

        # 构建 {列名: [出现该列的文件列表]}
        all_columns: dict[str, list[str]] = {}

        for fm in files:
            for sheet in fm.sheets:
                for col in sheet.columns:
                    # 标准化列名（小写、去空格）
                    normalized_col = col.lower().strip()
                    all_columns.setdefault(normalized_col, []).append(
                        fm.file_name
                    )

        # 找出在多个文件中出现的列
        joins = []
        for col, file_list in all_columns.items():
            unique_files = list(set(file_list))
            # 如果列在 2 个或以上文件中出现，可能是 JOIN 键
            if len(unique_files) >= 2:
                joins.append({
                    "files": sorted(unique_files),
                    "key": col,
                })

        return {"potential_joins": joins}

    def get_join_suggestion(self, files: list[FileMeta]) -> str:
        """
        生成用户友好的 JOIN 建议文本。
        
        Args:
            files: FileMeta 列表
            
        Returns:
            建议文本
        """
        result = self.resolve(files)
        joins = result.get("potential_joins", [])

        if not joins:
            return ""

        lines = ["💡 检测到潜在的多文件关联："]
        for join in joins:
            files_str = " + ".join(join["files"])
            lines.append(f"  • {files_str} (通过 '{join['key']}')")

        return "\n".join(lines)