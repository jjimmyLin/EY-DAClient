# services/dify_service.py

import json

import requests


class DifyService:
    """
    Dify workflow service.
    """

    def __init__(
        self,
        api_key,
        workflow_url,
    ):
        self.api_key = api_key

        self.workflow_url = workflow_url

    # =========================================================
    # Public API
    # =========================================================

    def run_workflow(
        self,
        user_request,
        dataset_profiles,
    ):
        """
        Execute Dify workflow.

        Parameters
        ----------
        user_request : str

        dataset_profiles : list[dict]

        Returns
        -------
        dict
        """

        payload = self._build_payload(
            user_request=user_request,
            dataset_profiles=dataset_profiles,
        )

        response = requests.post(
            url=self.workflow_url,
            headers=self._build_headers(),
            json=payload,
            timeout=120,
        )

        response.raise_for_status()

        return response.json()

    # =========================================================
    # Internal
    # =========================================================

    def _build_headers(self):
        """
        Build HTTP headers.
        """

        return {
            "Authorization": (
                f"Bearer {self.api_key}"
            ),
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        user_request,
        dataset_profiles,
    ):
        """
        Build workflow payload.
        """

        return {
            "inputs": {
                "user_request": user_request,
                "dataset_profiles": (
                    json.dumps(
                        dataset_profiles,
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            },
            "response_mode": "blocking",
            "user": "local-user",
        }