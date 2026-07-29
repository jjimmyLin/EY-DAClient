"""Qt worker for company-entity preflight resolution."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from dify.company_resolution_client import CompanyResolutionDifyClient
from llm.cancellation import CancellationToken, RequestCancelled


logger = logging.getLogger(__name__)


class CompanyResolutionWorker(QObject):
    event = Signal(dict)
    finished = Signal(object)
    error = Signal(str)
    cancelled = Signal()

    def __init__(self, company_query: str) -> None:
        super().__init__()
        self._company_query = company_query
        self._cancellation_token = CancellationToken()

    def cancel(self) -> None:
        self._cancellation_token.cancel()

    @Slot()
    def run(self) -> None:
        try:
            client = CompanyResolutionDifyClient(
                cancellation_token=self._cancellation_token
            )
            result = client.resolve(
                self._company_query,
                event_callback=self.event.emit,
            )
            if self._cancellation_token.is_cancelled:
                self.cancelled.emit()
                return
            self.finished.emit(result)
        except RequestCancelled:
            logger.info(
                "Company resolution cancelled query=%s",
                self._company_query,
            )
            self.cancelled.emit()
        except Exception as exc:
            logger.exception(
                "Company resolution failed query=%s",
                self._company_query,
            )
            self.error.emit(str(exc))
