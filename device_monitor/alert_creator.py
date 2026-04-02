"""Alert creator for device monitoring (create -> classify -> unlock flow).

This module handles the 3-stage alert lifecycle for device unlock alerts:
  Stage 1: Create alert  — POST /api/v1/alerts
  Stage 2: Classify alert — POST /api/v1/client/trigger-classification?alertId=<id>
  Stage 3: Unlock device  — POST <DEVICE_TASK_AGENT_UNLOCK_URL>?alertId=<id>
                            (custom URL, different from the standard task agent endpoint)

The alert message is hardcoded: "Alert : Unlock the Device: IMEI<config_value>"
Source is always "Service Now".
"""
from __future__ import annotations

import logging
import secrets
import string
from typing import Optional
import requests

from .config import device_config

logger = logging.getLogger(__name__)


class AlertCreator:
    """Creates alerts for device unlock using the 3-stage flow."""

    def __init__(self):
        self.base_url = device_config.alert_api_url

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

    def run_alert_flow(self) -> tuple[Optional[int], Optional[str], bool]:
        """
        Run full 3-stage alert flow (create -> classify -> unlock).
        Returns (alert_id, ticket_id, success) tuple.
        """
        logger.info("[Device Monitor] [Alert Flow] Starting 3-stage alert flow")

        # Stage 1: Create alert
        alert_id, ticket_id = self._create_alert()
        if alert_id is None:
            logger.error("[Device Monitor] [Alert Flow] Stage 1 failed: Alert creation failed")
            return None, ticket_id, False

        logger.info("[Device Monitor] [Alert Flow] Stage 1 success: alert_id=%s ticket_id=%s", alert_id, ticket_id)

        # Stage 2: Classify alert
        classified = self._classify_alert(alert_id)
        if not classified:
            logger.error("[Device Monitor] [Alert Flow] Stage 2 failed: Classification failed (alertId=%s ticketId=%s)", alert_id, ticket_id)
            return alert_id, ticket_id, False

        logger.info("[Device Monitor] [Alert Flow] Stage 2 success: Classification completed (alertId=%s)", alert_id)

        # Stage 3: Unlock device (custom task agent URL)
        unlocked = self._unlock_device(alert_id)
        if not unlocked:
            logger.error("[Device Monitor] [Alert Flow] Stage 3 failed: Unlock failed (alertId=%s ticketId=%s)", alert_id, ticket_id)
            return alert_id, ticket_id, False

        logger.info("[Device Monitor] [Alert Flow] Stage 3 success: Unlock completed (alertId=%s)", alert_id)
        logger.info("[Device Monitor] [Alert Flow] ✅ Full 3-stage flow completed successfully")
        return alert_id, ticket_id, True

    def _create_alert(self) -> tuple[Optional[int], Optional[str]]:
        """Stage 1: Create alert with hardcoded device unlock message."""
        ticket_id = self._new_ticket_id()
        ticket_message = f"Alert : Unlock the Device: IMEI{device_config.device_imei}"

        payload = {
            "ticketId": ticket_id,
            "createdBy": device_config.alert_created_by,
            "severity": "medium",
            "source": "Service Now",
            "ticket": ticket_message,
        }

        url = self.base_url
        logger.info("[Device Monitor] [Alert Creation] Creating alert with ticketId=%s", ticket_id)
        logger.info("[Device Monitor] [Alert Creation] Message: %s", ticket_message)
        logger.debug("[Device Monitor] [Alert Creation] POST %s payload=%s", url, payload)

        try:
            resp = requests.post(url, json=payload, timeout=device_config.alert_timeout_seconds)

            if not resp.ok:
                logger.error("[Device Monitor] [Alert Creation] Failed: status=%s body=%s", resp.status_code, resp.text[:500])
                return None, ticket_id

            alert_id = None
            try:
                data = resp.json()
                logger.debug("[Device Monitor] [Alert Creation] Response JSON: %s", data)
                alert_id = data.get("id")
            except Exception:
                logger.warning("[Device Monitor] [Alert Creation] Non-JSON response")

            if not isinstance(alert_id, int):
                logger.error("[Device Monitor] [Alert Creation] Missing numeric 'id' in response; ticketId=%s", ticket_id)
                return None, ticket_id

            logger.info("[Device Monitor] [Alert Creation] Success id=%s ticketId=%s", alert_id, ticket_id)
            self._created_ticket_ids.add(ticket_id)
            return alert_id, ticket_id

        except requests.exceptions.Timeout:
            logger.error("[Device Monitor] [Alert Creation] Timeout (>%ss) ticketId=%s", device_config.alert_timeout_seconds, ticket_id)
            return None, ticket_id

        except Exception as e:
            logger.error("[Device Monitor] [Alert Creation] Error: %s ticketId=%s", e, ticket_id)
            return None, ticket_id

    def _classify_alert(self, alert_id: int) -> bool:
        """Stage 2: Classification (same endpoint as other monitors)."""
        url = f"{self.base_host}/api/v1/client/trigger-classification?alertId={alert_id}"
        headers = {"Content-Type": "application/json"}
        logger.info("[Device Monitor] [Classification] Triggering classification for alertId=%s", alert_id)
        logger.debug("[Device Monitor] [Classification] POST %s", url)

        try:
            resp = requests.post(url, headers=headers, timeout=device_config.classification_timeout_seconds)
            if not resp.ok:
                logger.error("[Device Monitor] [Classification] Failed: status=%s body=%s", resp.status_code, resp.text[:500])
                return False

            logger.info("[Device Monitor] [Classification] Success alertId=%s", alert_id)
            return True

        except requests.exceptions.Timeout:
            logger.error("[Device Monitor] [Classification] Timeout (>%ss) alertId=%s", device_config.classification_timeout_seconds, alert_id)
            return False

        except Exception as e:
            logger.error("[Device Monitor] [Classification] Error: %s", e)
            return False

    def _unlock_device(self, alert_id: int) -> bool:
        """Stage 3: Unlock device via custom task agent URL.

        Unlike k8s/splunk monitors which use /api/v1/client/trigger-task-agent,
        the device usecase sends the alertId to a dedicated unlock endpoint:
            POST <DEVICE_TASK_AGENT_UNLOCK_URL>?alertId=<id>
        """
        if alert_id in self._processed_alert_ids:
            logger.debug("[Device Monitor] [Unlock Agent] Skipping duplicate for alertId=%s", alert_id)
            return True

        url = f"{device_config.task_agent_unlock_url}?alertId={alert_id}"
        headers = {"Content-Type": "application/json"}
        logger.info("[Device Monitor] [Unlock Agent] Triggering device unlock for alertId=%s", alert_id)
        logger.info("[Device Monitor] [Unlock Agent] URL: %s", url)

        try:
            resp = requests.post(url, headers=headers, timeout=device_config.task_agent_timeout_seconds)
            if not resp.ok:
                logger.error("[Device Monitor] [Unlock Agent] Failed: status=%s body=%s", resp.status_code, resp.text[:500])
                return False

            logger.info("[Device Monitor] [Unlock Agent] Success alertId=%s", alert_id)
            self._processed_alert_ids.add(alert_id)
            return True

        except requests.exceptions.Timeout:
            logger.error("[Device Monitor] [Unlock Agent] Timeout (>%ss) alertId=%s", device_config.task_agent_timeout_seconds, alert_id)
            return False

        except Exception as e:
            logger.error("[Device Monitor] [Unlock Agent] Error: %s", e)
            return False


alert_creator = AlertCreator()
