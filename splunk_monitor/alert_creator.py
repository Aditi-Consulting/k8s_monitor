"""Alert creator using same API as k8s_monitor (create -> classify -> solve flow)."""
from __future__ import annotations

import logging
import secrets
import string
from typing import Optional, Dict, Any
import requests

from .config import splunk_config
from .api_client import ApplicationException

logger = logging.getLogger(__name__)

class AlertCreator:
    """Creates alerts using the same alert API flow as k8s_monitor."""

    def __init__(self):
        self.base_url = splunk_config.alert_api_url

        if "/api/v1/alerts" in self.base_url:
            self.base_host = self.base_url.split("/api/v1/alerts")[0]
        else:
            self.base_host = self.base_url

        self._processed_alert_ids: set[int] = set()
        self._created_ticket_ids: set[str] = set()


    def _new_ticket_id(self) -> str:
        """Generate unique random 12-char alphanumeric ticket ID."""
        alphabet = string.ascii_lowercase + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(12))

    def run_alert_flow(
        self,
        exception: ApplicationException,
        llm_analysis: Dict[str, Any]
    ) -> tuple[Optional[int], Optional[str], bool]:
        """
        Run full 3-stage alert flow (create -> classify -> solve).
        Returns (alert_id, ticket_id, success) tuple.
        """
        logger.info("[Splunk Monitor] [Alert Flow] Starting 3-stage alert flow")

        # Stage 1: Create alert
        alert_id, ticket_id = self._create_alert(exception, llm_analysis)
        if alert_id is None:
            logger.error("[Splunk Monitor] [Alert Flow] Stage 1 failed: Alert creation failed")
            return None, ticket_id, False

        logger.info("[Splunk Monitor] [Alert Flow] Stage 1 success: alert_id=%s ticket_id=%s", alert_id, ticket_id)

        # Stage 2: Classify alert
        classified = self._classify_alert(alert_id)
        if not classified:
            logger.error("[Splunk Monitor] [Alert Flow] Stage 2 failed: Classification failed; stopping before solve (alertId=%s ticketId=%s)", alert_id, ticket_id)
            return alert_id, ticket_id, False

        logger.info("[Splunk Monitor] [Alert Flow] Stage 2 success: Classification completed (alertId=%s)", alert_id)

        # Stage 3: Solve alert
        solved = self._solve_alert(alert_id)
        if not solved:
            logger.error("[Splunk Monitor] [Alert Flow] Stage 3 failed: Solve/Task stage failed (alertId=%s ticketId=%s)", alert_id, ticket_id)
            return alert_id, ticket_id, False

        logger.info("[Splunk Monitor] [Alert Flow] Stage 3 success: Solve/Task completed (alertId=%s)", alert_id)
        logger.info("[Splunk Monitor] [Alert Flow] ✅ Full 3-stage flow completed successfully")
        return alert_id, ticket_id, True

    def _create_alert(
        self,
        exception: ApplicationException,
        llm_analysis: Dict[str, Any]
    ) -> tuple[Optional[int], Optional[str]]:
        """Stage 1: Create alert with separate signal and structured evidence."""
        ticket_id = self._new_ticket_id()
        ticket_message = self._build_ticket_message(exception, llm_analysis)

        payload = {
            "ticketId": ticket_id,
            "createdBy": splunk_config.alert_created_by,
            "severity": llm_analysis.get("severity", "medium"),
            "source": "Splunk",

            # SIGNAL (clean, LLM-generated operational alert)
            "ticket": ticket_message,

            # EVIDENCE (structured, machine-readable facts)
            "evidence": {
                "endpoint": exception.path,
                "status": exception.status,
                "error": exception.error,
                "error_code": exception.code,
                "message": exception.message,
                "location": exception.location,
                "context": exception.context,
                "timestamp": exception.timestamp,
                "source": "splunk_monitor",
                "environment": "production"
            }
        }

        url = self.base_url
        logger.info("[Splunk Monitor] [Alert Creation] Creating alert with ticketId=%s", ticket_id)
        logger.debug("[Splunk Monitor] [Alert Creation] POST %s payload=%s", url, payload)

        try:
            resp = requests.post(
                url,
                json=payload,
                timeout=splunk_config.alert_timeout_seconds
            )

            if not resp.ok:
                logger.error(
                    "[Splunk Monitor] [Alert Creation] Failed: status=%s body=%s",
                    resp.status_code,
                    resp.text[:500]
                )
                return None, ticket_id

            alert_id = None
            try:
                data = resp.json()
                logger.debug("[Splunk Monitor] [Alert Creation] Response JSON: %s", data)
                alert_id = data.get("id")
            except Exception:
                logger.warning("[Splunk Monitor] [Alert Creation] Non-JSON response")

            if not isinstance(alert_id, int):
                logger.error(
                    "[Splunk Monitor] [Alert Creation] Missing numeric 'id' in response; ticketId=%s",
                    ticket_id
                )
                return None, ticket_id

            logger.info("[Splunk Monitor] [Alert Creation] Success id=%s ticketId=%s", alert_id, ticket_id)
            self._created_ticket_ids.add(ticket_id)
            return alert_id, ticket_id

        except requests.exceptions.Timeout:
            logger.error(
                "[Splunk Monitor] [Alert Creation] Timeout (>%ss) ticketId=%s",
                splunk_config.alert_timeout_seconds,
                ticket_id
            )
            return None, ticket_id

        except Exception as e:
            logger.error("[Splunk Monitor] [Alert Creation] Error: %s ticketId=%s", e, ticket_id)
            return None, ticket_id

    def _classify_alert(self, alert_id: int) -> bool:
        """Stage 2: Classification."""
        url = f"{self.base_host}/api/v1/client/trigger-classification?alertId={alert_id}"
        headers = {"Content-Type": "application/json"}
        logger.info("[Splunk Monitor] [Classification] Triggering classification for alertId=%s", alert_id)
        logger.debug("[Splunk Monitor] [Classification] POST %s", url)

        try:
            resp = requests.post(url, headers=headers, timeout=splunk_config.classification_timeout_seconds)
            if not resp.ok:
                logger.error("[Splunk Monitor] [Classification] Failed: status=%s body=%s", resp.status_code, resp.text[:500])
                return False

            logger.info("[Splunk Monitor] [Classification] Success alertId=%s", alert_id)
            return True

        except requests.exceptions.Timeout:
            logger.error("[Splunk Monitor] [Classification] Timeout (>%ss) alertId=%s", splunk_config.classification_timeout_seconds, alert_id)
            return False

        except Exception as e:
            logger.error("[Splunk Monitor] [Classification] Error: %s", e)
            return False

    def _solve_alert(self, alert_id: int) -> bool:
        """Stage 3: Solving / Task Agent (with duplicate prevention)."""
        if alert_id in self._processed_alert_ids:
            logger.debug("[Splunk Monitor] [Task Agent] Skipping duplicate solve for alertId=%s", alert_id)
            return True

        url = f"{self.base_host}/api/v1/client/trigger-task-agent?alertId={alert_id}"
        headers = {"Content-Type": "application/json"}
        logger.info("[Splunk Monitor] [Task Agent] Triggering task agent for alertId=%s", alert_id)
        logger.debug("[Splunk Monitor] [Task Agent] POST %s", url)

        try:
            resp = requests.post(url, headers=headers, timeout=splunk_config.task_agent_timeout_seconds)
            if not resp.ok:
                logger.error("[Splunk Monitor] [Task Agent] Failed: status=%s body=%s", resp.status_code, resp.text[:500])
                return False

            logger.info("[Splunk Monitor] [Task Agent] Success alertId=%s", alert_id)
            self._processed_alert_ids.add(alert_id)
            return True

        except requests.exceptions.Timeout:
            logger.error("[Splunk Monitor] [Task Agent] Timeout (>%ss) alertId=%s", splunk_config.task_agent_timeout_seconds, alert_id)
            return False

        except Exception as e:
            logger.error("[Splunk Monitor] [Task Agent] Error: %s", e)
            return False

    def _build_ticket_message(
        self,
        exception: ApplicationException,
        llm_analysis: Dict[str, Any]
    ) -> str:
        """Return detailed alert message for downstream agent processing."""
        return llm_analysis.get(
            "alert_message",
            f"Alert: Application failure at {exception.location or exception.path} - {exception.message}"
        )

alert_creator = AlertCreator()

