"""Application service for consented, background experience learning."""

from __future__ import annotations

from typing import Any

from config.settings import settings
from core.analysis_result import AnalysisResult
from core.experience_payload import build_experience_payload
from core.preprocessor import FileMeta
from dify.experience_client import ExperienceClient, ExperienceSubmissionResult
from llm.cancellation import CancellationToken


class ExperienceService:
    """Keep experience eligibility and workflow submission outside the UI."""

    @staticmethod
    def is_available() -> bool:
        return bool(
            settings.EXPERIENCE_LEARNING_ENABLED
            and settings.DIFY_EXPERIENCE_BASE_URL.strip()
            and settings.DIFY_EXPERIENCE_API_KEY.strip()
        )

    @staticmethod
    def should_prompt(task: dict[str, Any] | None) -> bool:
        if not ExperienceService.is_available() or not task:
            return False
        return bool(
            task.get("status") == "Completed"
            and task.get("finished")
            and task.get("analysis_verified")
            and not task.get("experience_prompted")
            and task.get("analysis_result")
        )

    @staticmethod
    def build_payload(
        *,
        task: dict[str, Any],
        analysis_result: AnalysisResult,
    ) -> dict[str, Any]:
        return build_experience_payload(
            analysis_session_id=str(task.get("analysis_session_id") or ""),
            analysis_run_id=str(task.get("analysis_run_id") or ""),
            files_meta=list(task.get("files_meta") or []),
            user_query=str(task.get("query") or ""),
            analysis_plan=dict(task.get("analysis_plan") or {}),
            analysis_result=analysis_result,
            repair_count=int(task.get("repair_count") or 0),
            manual_edit=bool(task.get("manual_edit")),
        )

    @staticmethod
    def submit(
        payload: dict[str, Any],
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> ExperienceSubmissionResult:
        return ExperienceClient(
            cancellation_token=cancellation_token,
        ).submit(payload)
