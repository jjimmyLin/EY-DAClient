"""Qt worker for the dedicated business-indicator Dify workflow."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from core.metric_discovery import MetricDiscoveryRequest
from dify.metric_client import MetricDifyClient
from llm.cancellation import CancellationToken, RequestCancelled


logger = logging.getLogger(__name__)


class MetricDiscoveryWorker(QObject):
    event = Signal(dict)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, request: MetricDiscoveryRequest) -> None:
        super().__init__()
        self._request = request
        self._cancellation_token = CancellationToken()

    def cancel(self) -> None:
        self._cancellation_token.cancel()
        logger.info(
            "Metric discovery cancellation requested request_id=%s",
            self._request.request_id,
        )

    @Slot()
    def run(self) -> None:
        try:
            logger.info(
                "Metric discovery started request_id=%s attachments=%s",
                self._request.request_id,
                len(self._request.attachments),
            )
            client = MetricDifyClient(
                cancellation_token=self._cancellation_token
            )
            result = client.generate(
                self._request,
                event_callback=self.event.emit,
            )
            if self._cancellation_token.is_cancelled:
                self.error.emit("Request cancelled")
                return
            logger.info(
                "Metric discovery finished request_id=%s indicators=%s",
                self._request.request_id,
                len(result.indicators),
            )
            self.finished.emit(result)
        except RequestCancelled:
            logger.info(
                "Metric discovery cancelled request_id=%s",
                self._request.request_id,
            )
            self.error.emit("Request cancelled")
        except Exception as exc:
            logger.exception(
                "Metric discovery failed request_id=%s",
                self._request.request_id,
            )
            self.error.emit(str(exc))
