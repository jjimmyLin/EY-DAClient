"""Strict planning and generated-code contracts for reliable analysis."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

from config.settings import settings
from core.preprocessor import FileMeta


@dataclass
class ContractValidation:
    is_valid: bool
    issues: list[str] = field(default_factory=list)

    def raise_if_invalid(self) -> None:
        if not self.is_valid:
            raise AnalysisContractError("\n".join(self.issues))


class AnalysisContractError(Exception):
    pass


class AnalysisPlanValidator:
    """Validate that Dify produced an executable, unambiguous data plan."""

    def validate(
        self,
        plan: dict[str, Any] | None,
        files_meta: list[FileMeta],
    ) -> ContractValidation:
        plan = plan or {}
        issues: list[str] = []
        if bool(plan.get("clarification_required")):
            question = str(plan.get("clarification_question") or "").strip()
            if not question:
                issues.append(
                    "clarification_required is true but no question was provided"
                )
            return ContractValidation(not issues, issues)

        requirements = plan.get("requirements")
        if not isinstance(requirements, list) or not requirements:
            issues.append("analysis_plan.requirements must contain at least one item")
            return ContractValidation(False, issues)

        datasets = {
            file_meta.runtime_key: file_meta
            for file_meta in files_meta
        }
        requirement_ids: set[str] = set()
        for index, requirement in enumerate(requirements, start=1):
            if not isinstance(requirement, dict):
                issues.append(f"Requirement {index} must be an object")
                continue
            requirement_id = str(requirement.get("id") or "").strip()
            if not requirement_id:
                issues.append(f"Requirement {index} has no id")
            elif requirement_id in requirement_ids:
                issues.append(f"Duplicate requirement id: {requirement_id}")
            requirement_ids.add(requirement_id)

            sources = requirement.get("sources")
            if not isinstance(sources, list) or not sources:
                issues.append(f"{requirement_id or index} has no explicit sources")
                continue
            for source in sources:
                self._validate_source(source, datasets, issues, requirement_id)

            joins = requirement.get("joins") or []
            if len(sources) > 1 and not joins:
                issues.append(
                    f"{requirement_id or index} uses multiple datasets but has "
                    "no explicit join/alignment rule"
                )
            for join in joins:
                self._validate_join(join, datasets, issues, requirement_id)

            if len(sources) > 1 and not str(
                requirement.get("grain") or ""
            ).strip():
                issues.append(
                    f"{requirement_id or index} uses multiple datasets but has "
                    "no result grain"
                )

        return ContractValidation(not issues, issues)

    @staticmethod
    def _validate_source(
        source: Any,
        datasets: dict[str, FileMeta],
        issues: list[str],
        requirement_id: str,
    ) -> None:
        if not isinstance(source, dict):
            issues.append(f"{requirement_id}: source must be an object")
            return
        dataset_id = str(source.get("dataset_id") or "")
        sheet_id = str(source.get("sheet_id") or "")
        columns = source.get("columns") or []
        file_meta = datasets.get(dataset_id)
        if file_meta is None:
            issues.append(f"{requirement_id}: unknown dataset_id {dataset_id!r}")
            return
        sheet = next(
            (
                item
                for item in file_meta.sheets
                if (item.sheet_id or item.sheet_name) == sheet_id
            ),
            None,
        )
        if sheet is None:
            issues.append(
                f"{requirement_id}: unknown sheet_id {sheet_id!r} "
                f"for {dataset_id}"
            )
            return
        missing = [
            str(column)
            for column in columns
            if str(column) not in sheet.columns
        ]
        if missing:
            issues.append(
                f"{requirement_id}: columns missing from "
                f"{dataset_id}/{sheet_id}: {missing}"
            )

    @staticmethod
    def _validate_join(
        join: Any,
        datasets: dict[str, FileMeta],
        issues: list[str],
        requirement_id: str,
    ) -> None:
        if not isinstance(join, dict):
            issues.append(f"{requirement_id}: join must be an object")
            return
        left = join.get("left") or {}
        right = join.get("right") or {}
        for side_name, side in (("left", left), ("right", right)):
            if not isinstance(side, dict):
                issues.append(f"{requirement_id}: join {side_name} is invalid")
                continue
            dataset_id = str(side.get("dataset_id") or "")
            file_meta = datasets.get(dataset_id)
            if file_meta is None:
                issues.append(
                    f"{requirement_id}: join references unknown dataset "
                    f"{dataset_id!r}"
                )
                continue
            sheet_id = str(side.get("sheet_id") or "")
            sheet = next(
                (
                    item
                    for item in file_meta.sheets
                    if (item.sheet_id or item.sheet_name) == sheet_id
                ),
                None,
            )
            if sheet is None:
                issues.append(
                    f"{requirement_id}: join references unknown sheet "
                    f"{sheet_id!r} for {dataset_id}"
                )
                continue
            column = str(side.get("column") or "")
            if not column:
                issues.append(
                    f"{requirement_id}: join {side_name} column is missing"
                )
            elif column not in sheet.columns:
                issues.append(
                    f"{requirement_id}: join column {column!r} is missing "
                    f"from {dataset_id}/{sheet_id}"
                )
        relationship = str(join.get("expected_relationship") or "")
        if relationship not in {
            "one_to_one",
            "one_to_many",
            "many_to_one",
            "many_to_many",
        }:
            issues.append(
                f"{requirement_id}: join expected_relationship is missing"
            )
        if relationship == "many_to_many" and not bool(
            join.get("many_to_many_confirmed")
        ):
            issues.append(
                f"{requirement_id}: many-to-many join requires confirmation"
            )


class GeneratedCodeContractValidator:
    """Check references and required execution patterns before running code."""

    def validate(
        self,
        code: str,
        files_meta: list[FileMeta],
        plan: dict[str, Any] | None,
    ) -> ContractValidation:
        issues: list[str] = []
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return ContractValidation(False, [f"Python syntax error: {exc}"])

        datasets = {file_meta.runtime_key for file_meta in files_meta}
        large_datasets = {
            file_meta.runtime_key
            for file_meta in files_meta
            if file_meta.file_size_kb >= settings.BACKGROUND_ANALYSIS_MB * 1024
            or sum(sheet.rows for sheet in file_meta.sheets) >= settings.BACKGROUND_ANALYSIS_ROWS
        }
        file_name_counts: dict[str, int] = {}
        for file_meta in files_meta:
            file_name_counts[file_meta.file_name] = (
                file_name_counts.get(file_meta.file_name, 0) + 1
            )
        datasets.update(
            file_meta.file_name
            for file_meta in files_meta
            if file_name_counts[file_meta.file_name] == 1
        )
        requirements = [
            str(item.get("id"))
            for item in (plan or {}).get("requirements", [])
            if isinstance(item, dict) and item.get("id")
        ]
        spec = self._analysis_spec(tree)
        if requirements:
            if spec is None:
                issues.append("Generated code must define ANALYSIS_SPEC")
            else:
                implemented = {
                    str(item)
                    for item in spec.get("requirements", [])
                }
                missing = sorted(set(requirements) - implemented)
                if missing:
                    issues.append(
                        f"ANALYSIS_SPEC omits requirements: {missing}"
                    )

        referenced = self._dataset_references(tree)
        unknown = sorted(referenced - datasets)
        if unknown:
            issues.append(f"Generated code references unknown datasets: {unknown}")

        issues.extend(self._unsafe_large_accesses(tree, large_datasets))

        joins_required = any(
            len(item.get("sources") or []) > 1
            for item in (plan or {}).get("requirements", [])
            if isinstance(item, dict)
        )
        if joins_required and not self._uses_audited_alignment(tree):
            issues.append(
                "Cross-dataset analysis must use data.merge(...) or "
                "data.sql(...) so alignment is explicit and auditable"
            )
        if large_datasets and joins_required and not self._uses_sql(tree):
            issues.append(
                "Large cross-dataset analysis must use data.sql(...) so DuckDB can "
                "push joins and aggregation down to Parquet."
            )

        return ContractValidation(not issues, issues)

    @staticmethod
    def _analysis_spec(tree: ast.AST) -> dict[str, Any] | None:
        for node in getattr(tree, "body", []):
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name)
                and target.id == "ANALYSIS_SPEC"
                for target in node.targets
            ):
                continue
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                return None
            return value if isinstance(value, dict) else None
        return None

    @staticmethod
    def _dataset_references(tree: ast.AST) -> set[str]:
        references: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "data"
                    and node.func.attr == "get"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    references.add(str(node.args[0].value))
            if isinstance(node, ast.Subscript):
                root = node.value
                if (
                    isinstance(root, ast.Name)
                    and root.id == "dfs"
                    and isinstance(node.slice, ast.Constant)
                ):
                    references.add(str(node.slice.value))
        return references

    @staticmethod
    def _uses_audited_alignment(tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func,
                ast.Attribute,
            ):
                continue
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "data"
                and node.func.attr in {"merge", "sql"}
            ):
                return True
        return False

    @staticmethod
    def _uses_sql(tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "data"
                and node.func.attr == "sql"
            ):
                return True
        return False

    @staticmethod
    def _unsafe_large_accesses(tree: ast.AST, large_datasets: set[str]) -> list[str]:
        if not large_datasets:
            return []
        issues: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript):
                root = node.value
                if (
                    isinstance(root, ast.Name)
                    and root.id == "dfs"
                    and isinstance(node.slice, ast.Constant)
                    and str(node.slice.value) in large_datasets
                ):
                    issues.append(
                        f"Large dataset {node.slice.value!r} cannot be accessed through dfs[...]"
                    )
            if not isinstance(node, ast.Call):
                continue
            if not (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "data"
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                continue
            dataset_id = str(node.args[0].value)
            if dataset_id not in large_datasets:
                continue
            has_columns = any(
                keyword.arg == "columns"
                and not (
                    isinstance(keyword.value, (ast.List, ast.Tuple))
                    and len(keyword.value.elts) == 0
                )
                for keyword in node.keywords
            )
            if not has_columns:
                issues.append(
                    f"Large dataset {dataset_id!r} must use data.get(..., columns=[...])"
                )
        return issues
