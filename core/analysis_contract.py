"""Strict planning and generated-code contracts for reliable analysis."""

from __future__ import annotations

import ast
import re
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
        user_query: str = "",
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
            combines = requirement.get("combines") or []
            if len(sources) > 1 and not joins and not combines:
                issues.append(
                    f"{requirement_id or index} uses multiple sources but has "
                    "no explicit join/alignment or append/union rule"
                )
            for join in joins:
                self._validate_join(join, datasets, issues, requirement_id)
            for combine in combines:
                self._validate_combine(
                    combine,
                    datasets,
                    issues,
                    requirement_id,
                )

            if len(sources) > 1 and not str(
                requirement.get("grain") or ""
            ).strip():
                issues.append(
                    f"{requirement_id or index} uses multiple sources but has "
                    "no result grain"
                )

        if not issues and user_query:
            coverage = IntentCoverageValidator().validate(
                user_query,
                plan,
                files_meta,
            )
            issues.extend(coverage.issues)

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
        sheet = AnalysisPlanValidator._sheet_by_id(file_meta, sheet_id)
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
            sheet = AnalysisPlanValidator._sheet_by_id(file_meta, sheet_id)
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

    @staticmethod
    def _validate_combine(
        combine: Any,
        datasets: dict[str, FileMeta],
        issues: list[str],
        requirement_id: str,
    ) -> None:
        if not isinstance(combine, dict):
            issues.append(f"{requirement_id}: combine must be an object")
            return
        combine_type = str(combine.get("type") or "")
        if combine_type not in {"union_all", "append"}:
            issues.append(
                f"{requirement_id}: combine type must be union_all or append"
            )
            return
        dataset_id = str(combine.get("dataset_id") or "")
        file_meta = datasets.get(dataset_id)
        if file_meta is None:
            issues.append(
                f"{requirement_id}: combine references unknown dataset "
                f"{dataset_id!r}"
            )
            return
        group_id = str(combine.get("group_id") or "")
        sheet_ids = [
            str(sheet_id)
            for sheet_id in (combine.get("sheet_ids") or [])
        ]
        columns = [
            str(column)
            for column in (combine.get("columns") or [])
        ]
        sheets = []
        if group_id:
            group = AnalysisPlanValidator._sheet_group_by_id(file_meta, group_id)
            if group is None:
                issues.append(
                    f"{requirement_id}: unknown sheet group {group_id!r} "
                    f"for {dataset_id}"
                )
                return
            group_sheet_ids = [str(sheet_id) for sheet_id in group.sheet_ids]
            if sheet_ids:
                outside_group = sorted(set(sheet_ids) - set(group_sheet_ids))
                if outside_group:
                    issues.append(
                        f"{requirement_id}: combine sheet_ids are outside "
                        f"group {group_id}: {outside_group}"
                    )
                    return
            sheet_ids = sheet_ids or group_sheet_ids
            missing_columns = [
                column
                for column in columns
                if column not in group.columns
            ]
            if missing_columns:
                issues.append(
                    f"{requirement_id}: combine columns missing from "
                    f"group {group_id}: {missing_columns}"
                )
        if not sheet_ids:
            issues.append(
                f"{requirement_id}: combine requires group_id or sheet_ids"
            )
            return
        for sheet_id in sheet_ids:
            sheet = AnalysisPlanValidator._sheet_by_id(file_meta, sheet_id)
            if sheet is None:
                issues.append(
                    f"{requirement_id}: combine references unknown sheet "
                    f"{sheet_id!r} for {dataset_id}"
                )
                continue
            missing_columns = [
                column
                for column in columns
                if column not in sheet.columns
            ]
            if missing_columns:
                issues.append(
                    f"{requirement_id}: combine columns missing from "
                    f"{dataset_id}/{sheet_id}: {missing_columns}"
                )
            sheets.append(sheet)
        if len(sheets) < 2:
            return
        first_columns = sheets[0].columns
        inconsistent = [
            sheet.sheet_id or sheet.sheet_name
            for sheet in sheets[1:]
            if sheet.columns != first_columns
        ]
        if inconsistent:
            issues.append(
                f"{requirement_id}: combine sheets do not share the same "
                f"column order: {inconsistent}"
            )

    @staticmethod
    def _sheet_by_id(file_meta: FileMeta, sheet_id: str) -> Any | None:
        return next(
            (
                item
                for item in file_meta.sheets
                if (item.sheet_id or item.sheet_name) == sheet_id
            ),
            None,
        )

    @staticmethod
    def _sheet_group_by_id(file_meta: FileMeta, group_id: str) -> Any | None:
        return next(
            (
                item
                for item in file_meta.sheet_groups
                if item.group_id == group_id
            ),
            None,
        )


class IntentCoverageValidator:
    """Conservative local checks that the plan covers explicit user intent."""

    _ACTION_SYNONYMS = {
        "sum": (
            "sum",
            "total",
            "合计",
            "总计",
            "汇总",
            "求和",
        ),
        "average": (
            "average",
            "avg",
            "mean",
            "平均",
            "均值",
        ),
        "compare": (
            "compare",
            "comparison",
            "vs",
            "versus",
            "对比",
            "比较",
        ),
        "trend": (
            "trend",
            "change",
            "movement",
            "趋势",
            "变化",
            "波动",
        ),
        "anomaly": (
            "anomaly",
            "exception",
            "outlier",
            "unusual",
            "异常",
            "例外",
            "波动",
        ),
        "rank": (
            "top",
            "rank",
            "largest",
            "highest",
            "排名",
            "前",
            "最大",
            "最高",
        ),
        "count": (
            "count",
            "number of",
            "数量",
            "笔数",
            "次数",
            "计数",
        ),
    }

    _ANALYTIC_HINTS = tuple(
        sorted(
            {
                synonym
                for synonyms in _ACTION_SYNONYMS.values()
                for synonym in synonyms
            },
            key=len,
            reverse=True,
        )
    )

    def validate(
        self,
        user_query: str,
        plan: dict[str, Any],
        files_meta: list[FileMeta],
    ) -> ContractValidation:
        issues: list[str] = []
        requirements = [
            item
            for item in plan.get("requirements", []) or []
            if isinstance(item, dict)
        ]
        checklist = self._checklist_items(user_query)
        explicit_items = [
            item
            for item in checklist
            if item.get("explicit")
        ]
        actionable_explicit = [
            item
            for item in explicit_items
            if self._item_has_action_or_column(str(item["text"]), files_meta)
        ]
        if (
            len(actionable_explicit) >= 2
            and len(requirements) < len(actionable_explicit)
        ):
            issues.append(
                "intent coverage: user request has "
                f"{len(actionable_explicit)} explicit analysis item(s), but "
                f"the plan has {len(requirements)} requirement(s)"
            )

        plan_text = self._plan_text(plan)
        for item in checklist:
            text = str(item["text"])
            missing_columns = [
                column
                for column in self._mentioned_columns(text, files_meta)
                if self._normalize(column) not in plan_text
            ]
            if missing_columns:
                issues.append(
                    "intent coverage: plan does not reference column(s) "
                    f"mentioned by the user: {missing_columns}"
                )
            if item.get("explicit"):
                action = self._dominant_action(text)
                if action and not self._plan_mentions_action(action, plan_text):
                    issues.append(
                        "intent coverage: plan may omit requested action "
                        f"{action!r} from item {text!r}"
                    )

        return ContractValidation(not issues, issues)

    @classmethod
    def _checklist_items(cls, user_query: str) -> list[dict[str, Any]]:
        query = str(user_query or "").strip()
        if not query:
            return []
        explicit: list[str] = []
        for line in query.splitlines():
            match = re.match(
                r"\s*(?:\d+[\.\)、\)]|[-*•])\s*(.+?)\s*$",
                line,
            )
            if match:
                explicit.append(match.group(1))
        if explicit:
            return [
                {"text": item.strip(), "explicit": True}
                for item in explicit
                if item.strip()
            ]
        parts = [
            part.strip()
            for part in re.split(r"[;\n；。]+", query)
            if part.strip()
        ]
        if len(parts) <= 1:
            return [{"text": query, "explicit": False}]
        return [
            {"text": part, "explicit": False}
            for part in parts
            if cls._contains_analytic_hint(part)
        ]

    @classmethod
    def _item_has_action_or_column(
        cls,
        text: str,
        files_meta: list[FileMeta],
    ) -> bool:
        return bool(cls._dominant_action(text) or cls._mentioned_columns(text, files_meta))

    @classmethod
    def _dominant_action(cls, text: str) -> str:
        normalized = cls._normalize(text)
        for action, synonyms in cls._ACTION_SYNONYMS.items():
            if any(cls._normalize(synonym) in normalized for synonym in synonyms):
                return action
        return ""

    @classmethod
    def _contains_analytic_hint(cls, text: str) -> bool:
        normalized = cls._normalize(text)
        return any(
            cls._normalize(hint) in normalized
            for hint in cls._ANALYTIC_HINTS
        )

    @classmethod
    def _plan_mentions_action(cls, action: str, plan_text: str) -> bool:
        return any(
            cls._normalize(synonym) in plan_text
            for synonym in cls._ACTION_SYNONYMS.get(action, ())
        )

    @classmethod
    def _mentioned_columns(
        cls,
        text: str,
        files_meta: list[FileMeta],
    ) -> list[str]:
        normalized_text = cls._normalize(text)
        mentioned: list[str] = []
        for file_meta in files_meta:
            for sheet in file_meta.sheets:
                for column in sheet.columns:
                    normalized_column = cls._normalize(column)
                    if not normalized_column or len(normalized_column) < 2:
                        continue
                    if normalized_column in normalized_text and column not in mentioned:
                        mentioned.append(column)
        return mentioned

    @classmethod
    def _plan_text(cls, plan: dict[str, Any]) -> str:
        fragments: list[str] = []
        fragments.append(str(plan.get("task_summary") or ""))
        for requirement in plan.get("requirements", []) or []:
            if not isinstance(requirement, dict):
                continue
            for key in (
                "id",
                "objective",
                "grain",
                "formula",
                "output_type",
            ):
                fragments.append(str(requirement.get(key) or ""))
            for source in requirement.get("sources", []) or []:
                if isinstance(source, dict):
                    fragments.extend(str(item) for item in source.get("columns", []) or [])
            for combine in requirement.get("combines", []) or []:
                if isinstance(combine, dict):
                    fragments.append(str(combine.get("reason") or ""))
                    fragments.extend(str(item) for item in combine.get("columns", []) or [])
        return cls._normalize(" ".join(fragments))

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[\s_\-（）()、，,。.;；:：/]+", "", str(value).lower())


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
        # ANALYSIS_SPEC and result.add_answer(...) improve UI presentation, but
        # they are not safety requirements. Missing answer cards are filled
        # after successful execution from the analysis plan and summary.

        referenced = self._dataset_references(tree)
        unknown = sorted(referenced - datasets)
        if unknown:
            issues.append(f"Generated code references unknown datasets: {unknown}")

        issues.extend(self._unsafe_large_accesses(tree, large_datasets))

        alignment_required = any(
            len(item.get("sources") or []) > 1
            for item in (plan or {}).get("requirements", [])
            if isinstance(item, dict)
        )
        if alignment_required and not self._uses_audited_alignment(tree):
            issues.append(
                "Cross-source analysis must use data.merge(...), data.sql(...), "
                "or data.union_sheets(...) so alignment/append is explicit and auditable"
            )

        return ContractValidation(not issues, issues)

    @staticmethod
    def _dataset_references(tree: ast.AST) -> set[str]:
        references: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "data"
                    and node.func.attr in {"get", "union_sheets"}
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
                and node.func.attr in {"merge", "sql", "union_sheets"}
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
                and node.func.attr in {"get", "union_sheets"}
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
                accessor = node.func.attr
                issues.append(
                    f"Large dataset {dataset_id!r} must use data.{accessor}(..., columns=[...])"
                )
        return issues
