"""Execute Dify-generated Python against cached local datasets."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

from config.settings import settings
from core.analysis_result import AnalysisResult, AnswerResult, InsightResult
from core.preprocessor import FileMeta
from llm.cancellation import CancellationToken, RequestCancelled


logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    success: bool
    stdout: str
    stderr: str
    elapsed_sec: float
    timed_out: bool = False
    chart_paths: list[str] = field(default_factory=list)
    analysis_result: AnalysisResult = field(default_factory=AnalysisResult)
    preflight_only: bool = False
    peak_memory_mb: float = 0.0

    @property
    def output(self) -> str:
        return self.stdout if self.success else self.stderr


class Executor:
    """Run generated code in a child process with lazy cached data access."""

    def run(
        self,
        code: str,
        files_meta: list[FileMeta],
        *,
        sample: bool = False,
        analysis_plan: dict[str, Any] | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> ExecutionResult:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "analysis.py"
            result_path = Path(temp_dir) / "analysis_result.json"
            manifest = self._build_manifest(files_meta)
            script_path.write_text(
                self._build_bootstrap(
                    code,
                    manifest,
                    result_path,
                    sample=sample,
                ),
                encoding="utf-8",
            )

            timeout = self._execution_timeout(files_meta, sample)
            memory_limit = self._execution_memory_limit(files_meta, sample)
            logger.info(
                "Starting execution sample=%s timeout=%ss memory_limit_mb=%s datasets=%s",
                sample,
                timeout,
                memory_limit,
                [file_meta.runtime_key for file_meta in files_meta],
            )
            execution = self._run_subprocess(
                str(script_path),
                timeout,
                memory_limit,
                cancellation_token=cancellation_token,
            )
            execution.preflight_only = sample
            execution.analysis_result = self._load_analysis_result(
                result_path,
                execution.stdout,
            )
            execution.analysis_result.audit.append(
                {
                    "kind": "runtime",
                    "elapsed_sec": execution.elapsed_sec,
                    "peak_memory_mb": execution.peak_memory_mb,
                    "sampled": sample,
                }
            )
            semantic_error = self._semantic_audit(
                execution.analysis_result,
                analysis_plan or {},
            )
            if execution.success and semantic_error:
                execution.success = False
                execution.stderr = semantic_error
            elif execution.success:
                self._ensure_fallback_answers(
                    execution.analysis_result,
                    analysis_plan or {},
                )
            logger.info(
                "Execution finished success=%s sample=%s elapsed=%.2fs peak_memory_mb=%.2f",
                execution.success,
                sample,
                execution.elapsed_sec,
                execution.peak_memory_mb,
            )
            return execution

    @staticmethod
    def _build_manifest(files_meta: list[FileMeta]) -> list[dict[str, Any]]:
        name_counts: dict[str, int] = {}
        for file_meta in files_meta:
            name_counts[file_meta.file_name] = (
                name_counts.get(file_meta.file_name, 0) + 1
            )

        manifest: list[dict[str, Any]] = []
        for file_meta in files_meta:
            dataset_id = file_meta.runtime_key
            aliases: list[str] = []
            if name_counts[file_meta.file_name] == 1:
                aliases.append(file_meta.file_name)
            display_name = file_meta.display_name or file_meta.file_name
            if display_name != file_meta.file_name:
                aliases.append(display_name)
            manifest.append(
                {
                    "dataset_id": dataset_id,
                    "display_name": display_name,
                    "aliases": aliases,
                    "sheet_groups": [
                        group.to_prompt_dict()
                        for group in file_meta.sheet_groups
                    ],
                    "sheets": [
                        {
                            "sheet_id": sheet.sheet_id or sheet.sheet_name,
                            "name": sheet.sheet_name,
                            "cache_path": sheet.cache_path,
                            "sample_cache_path": sheet.sample_cache_path,
                            "rows": sheet.rows,
                            "columns": sheet.columns,
                        }
                        for sheet in file_meta.sheets
                    ],
                }
            )
        return manifest

    def _build_bootstrap(
        self,
        code: str,
        manifest: list[dict[str, Any]],
        result_path: Path,
        *,
        sample: bool,
    ) -> str:
        sample_rows = settings.SAMPLE_ROWS_PER_SHEET if sample else None
        user_code = textwrap.indent(code, "    ")
        return "\n".join(
            [
                "import sys as _bootstrap_sys",
                f"_bootstrap_sys.path.insert(0, {str(settings.PROJECT_ROOT)!r})",
                "_bootstrap_sys.stdout.reconfigure(encoding='utf-8', errors='replace')",
                "_bootstrap_sys.stderr.reconfigure(encoding='utf-8', errors='replace')",
                "import pandas as pd",
                "import numpy as np",
                "import matplotlib",
                "matplotlib.use('Agg')",
                "import matplotlib.pyplot as plt",
                "from core.analysis_result import ResultCollector",
                "from core.data_access import LocalDataCatalog",
                "import warnings",
                "warnings.filterwarnings('ignore')",
                f"_manifest = {manifest!r}",
                f"data = LocalDataCatalog(_manifest, sample_rows={sample_rows!r})",
                "dfs = data.dfs",
                "result = ResultCollector()",
                "del ResultCollector, LocalDataCatalog, warnings, _bootstrap_sys",
                "",
                "try:",
                user_code,
                "finally:",
                "    result.extend_audit(data.audit_records)",
                "    result.capture_open_figures(plt)",
                f"    result.write_json({str(result_path)!r})",
            ]
        )

    def _run_subprocess(
        self,
        script_path: str,
        timeout: int,
        memory_limit_mb: int,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> ExecutionResult:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--run-script", script_path]
        else:
            command = [sys.executable, script_path]

        started = time.monotonic()
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        peak_memory = 0.0
        timed_out = False
        memory_exceeded = False
        stdout = ""
        stderr = ""
        try:
            monitored = psutil.Process(process.pid)
            while True:
                if cancellation_token is not None:
                    if cancellation_token.is_cancelled:
                        self._kill_process_tree(monitored, process)
                        stdout, stderr = process.communicate()
                        raise RequestCancelled("Request cancelled")
                elapsed = time.monotonic() - started
                if elapsed > timeout:
                    timed_out = True
                    self._kill_process_tree(monitored, process)
                    break
                try:
                    memory = monitored.memory_info().rss
                    for child in monitored.children(recursive=True):
                        memory += child.memory_info().rss
                    peak_memory = max(peak_memory, memory / (1024 * 1024))
                    if peak_memory > memory_limit_mb:
                        memory_exceeded = True
                        self._kill_process_tree(monitored, process)
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                try:
                    stdout, stderr = process.communicate(timeout=0.05)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if timed_out or memory_exceeded:
                stdout, stderr = process.communicate()
        except RequestCancelled:
            raise
        except Exception as exc:
            try:
                monitored = psutil.Process(process.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                monitored = None
            self._kill_process_tree(monitored, process)
            stdout, stderr = process.communicate()
            stderr = f"{stderr}\nExecution monitor error: {exc}".strip()
            logger.exception("Execution monitor failed")

        elapsed = round(time.monotonic() - started, 2)
        if timed_out:
            stderr = (
                f"Execution timed out after {timeout} seconds. "
                "Use cached data.get(), explicit columns, aggregation, or "
                "data.sql() to reduce the workload."
            )
        elif memory_exceeded:
            stderr = (
                f"Execution exceeded the {memory_limit_mb} MB memory "
                "limit. Load fewer columns or use data.sql(..., sources=...) "
                "for aggregation and joins."
            )
        return ExecutionResult(
            success=(
                process.returncode == 0
                and not timed_out
                and not memory_exceeded
            ),
            stdout=stdout,
            stderr=stderr,
            elapsed_sec=elapsed,
            timed_out=timed_out,
            peak_memory_mb=round(peak_memory, 2),
        )

    @staticmethod
    def _kill_process_tree(
        monitored: psutil.Process | None,
        process: subprocess.Popen,
    ) -> None:
        if monitored is not None:
            try:
                for child in monitored.children(recursive=True):
                    try:
                        child.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass

    @staticmethod
    def _load_analysis_result(
        result_path: Path,
        stdout: str,
    ) -> AnalysisResult:
        payload: dict[str, Any] = {}
        if result_path.exists():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.exception("Failed to load structured analysis result from %s", result_path)
                payload = {}
        analysis_result = AnalysisResult.from_dict(payload)
        analysis_result.raw_output = stdout.strip()
        if not analysis_result.summary and analysis_result.raw_output:
            analysis_result.summary = analysis_result.raw_output[:1200]
        return analysis_result

    @staticmethod
    def _semantic_audit(
        result: AnalysisResult,
        analysis_plan: dict[str, Any],
    ) -> str:
        issues: list[str] = []
        requirement_ids = {
            str(item.get("id"))
            for item in analysis_plan.get("requirements", [])
            if isinstance(item, dict) and item.get("id")
        }
        completed = set(result.completed_requirements)
        missing = sorted(requirement_ids - completed)
        if missing:
            issues.append(f"Requirements were not marked complete: {missing}")

        confirmed_many_to_many = {
            (
                str((join.get("left") or {}).get("dataset_id") or ""),
                str((join.get("right") or {}).get("dataset_id") or ""),
            )
            for requirement in analysis_plan.get("requirements", [])
            if isinstance(requirement, dict)
            for join in requirement.get("joins", []) or []
            if isinstance(join, dict)
            and join.get("expected_relationship") == "many_to_many"
            and join.get("many_to_many_confirmed")
        }
        for record in result.audit:
            if record.get("kind") != "join":
                continue
            pair = (str(record.get("left")), str(record.get("right")))
            relationship = record.get("relationship")
            multiplier = float(record.get("row_multiplier") or 0)
            if relationship == "many_to_many" and pair not in confirmed_many_to_many:
                issues.append(
                    f"Unconfirmed many-to-many join: {pair[0]} -> {pair[1]}"
                )
            if multiplier > 5 and pair not in confirmed_many_to_many:
                issues.append(
                    f"Join expanded rows by {multiplier:.2f}x: "
                    f"{pair[0]} -> {pair[1]}"
                )

        invalid_metrics = [
            metric.label
            for metric in result.metrics
            if metric.value is None
        ]
        if invalid_metrics:
            issues.append(
                f"Metrics contain null/non-finite results: {invalid_metrics}"
            )

        if issues:
            return "Semantic validation failed:\n- " + "\n- ".join(issues)

        if result.audit:
            result.insights.append(
                InsightResult(
                    "Execution audit",
                    (
                        f"{len(result.audit)} audited data operation(s) completed. "
                        "Dataset loads and joins were recorded locally."
                    ),
                    "insight",
                )
            )
        return ""

    @staticmethod
    def _ensure_fallback_answers(
        result: AnalysisResult,
        analysis_plan: dict[str, Any],
    ) -> None:
        if result.answers:
            return
        requirements = [
            item
            for item in analysis_plan.get("requirements", [])
            if isinstance(item, dict) and item.get("id")
        ]
        if not requirements:
            return
        completed = {str(item) for item in result.completed_requirements}
        metric_labels = [metric.label for metric in result.metrics]
        table_titles = [table.title for table in result.tables]
        chart_titles = [chart.title for chart in result.charts]
        insight_titles = [insight.title for insight in result.insights]
        fallback_text = (
            result.summary
            or result.raw_output
            or "Analysis completed. Review the supporting outputs for details."
        )
        for requirement in requirements:
            requirement_id = str(requirement.get("id"))
            if requirement_id not in completed:
                continue
            result.answers.append(
                AnswerResult(
                    answer_id=requirement_id,
                    question=str(
                        requirement.get("objective")
                        or requirement.get("formula")
                        or requirement_id
                    ),
                    answer=fallback_text,
                    supporting_metrics=metric_labels,
                    supporting_tables=table_titles,
                    supporting_charts=chart_titles,
                    supporting_insights=insight_titles,
                    confidence_or_notes=(
                        "Generated by the local fallback because the script "
                        "did not provide result.add_answer(...)."
                    ),
                )
            )

    @staticmethod
    def _execution_timeout(
        files_meta: list[FileMeta],
        sample: bool,
    ) -> int:
        if sample:
            return max(15, settings.EXEC_TIMEOUT_SEC)
        total_rows = sum(
            sheet.rows
            for file_meta in files_meta
            for sheet in file_meta.sheets
        )
        scaled = settings.EXEC_TIMEOUT_SEC + int(total_rows / 100_000) * 10
        large = any(
            file_meta.file_size_kb
            >= settings.BACKGROUND_ANALYSIS_MB * 1024
            or sum(sheet.rows for sheet in file_meta.sheets)
            >= settings.BACKGROUND_ANALYSIS_ROWS
            for file_meta in files_meta
        )
        maximum = (
            settings.BACKGROUND_EXEC_TIMEOUT_SEC if large else 600
        )
        minimum = settings.EXEC_TIMEOUT_SEC
        if large:
            minimum = max(settings.EXEC_TIMEOUT_SEC * 4, 300)
        return max(minimum, min(scaled, maximum))

    @staticmethod
    def _execution_memory_limit(
        files_meta: list[FileMeta],
        sample: bool,
    ) -> int:
        if sample:
            return max(settings.EXEC_MAX_MEM_MB, 1024)
        large = any(
            file_meta.file_size_kb
            >= settings.BACKGROUND_ANALYSIS_MB * 1024
            or sum(sheet.rows for sheet in file_meta.sheets)
            >= settings.BACKGROUND_ANALYSIS_ROWS
            for file_meta in files_meta
        )
        return (
            settings.BACKGROUND_EXEC_MAX_MEM_MB
            if large
            else max(settings.EXEC_MAX_MEM_MB, 2048)
        )
