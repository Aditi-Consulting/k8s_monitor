"""Alert client handling full alert flow lifecycle.

Lifecycle (single cycle per alert event):
 1. Create alert (create_alert)
 2. Classify alert (classify_alert)
 3. Trigger task/solver (solve_alert)

`run_alert_flow` performs the chained lifecycle. `post_alert` kept for backward compatibility.
A simple in-memory set `_processed_alert_ids` prevents solving twice in rare cases of duplicate triggers
within the same process run (e.g., multiple rules generating the same key simultaneously).
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional
import requests
import secrets
import string

from .config import config

logger = logging.getLogger(__name__)

class AlertClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or config.alert_api_url
        if "/api/v1/alerts" in self.base_url:
            self.base_host = self.base_url.split("/api/v1/alerts")[0]
        else:
            self.base_host = self.base_url
        self._processed_alert_ids: set[int] = set()
        self._created_ticket_ids: set[str] = set()

    def _new_ticket_id(self) -> str:
        # Fixed-length 10 chars: 'K8M-' + 6-char random tail (base36-like: digits+lowercase)
        prefix = "K8M-"
        alphabet = string.ascii_lowercase + string.digits
        tail = ''.join(secrets.choice(alphabet) for _ in range(6))
        return prefix + tail

    # Stage 1: Alert Creation
    def create_alert(self, created_by: str, severity: str, ticket_message: str) -> tuple[Optional[int], Optional[str]]:
        ticket_id = self._new_ticket_id()
        payload = {
            "ticketId": ticket_id,
            "createdBy": created_by,
            "severity": severity,
            "ticket": ticket_message,
        }
        url = self.base_url
        logger.info("[Alert Creation] Creating alert with ticketId=%s", ticket_id)
        logger.debug("[Alert Creation] POST %s payload=%s", url, payload)
        try:
            resp = requests.post(url, json=payload, timeout=config.alert_timeout_seconds)
            if not resp.ok:
                logger.error("[Alert Creation] Failed: status=%s body=%s", resp.status_code, resp.text[:500])
                return None, ticket_id
            alert_id = None
            try:
                data = resp.json()
                logger.debug("[Alert Creation] Response JSON: %s", data)
                alert_id = data.get("id")
            except Exception:
                logger.warning("[Alert Creation] Non-JSON response")
            if not isinstance(alert_id, int):
                logger.error("[Alert Creation] Missing numeric 'id' in response; aborting flow. ticketId=%s", ticket_id)
                return None, ticket_id
            logger.info("[Alert Creation] Success id=%s ticketId=%s", alert_id, ticket_id)
            # Track created ticket IDs to help diagnose duplicates
            self._created_ticket_ids.add(ticket_id)
            return alert_id, ticket_id
        except requests.exceptions.Timeout:
            logger.error("[Alert Creation] Timeout (>%ss) ticketId=%s", config.alert_timeout_seconds, ticket_id)
            return None, ticket_id
        except Exception as e:
            logger.error("[Alert Creation] Error: %s ticketId=%s", e, ticket_id)
            return None, ticket_id

    # Stage 2: Classification
    def classify_alert(self, alert_id: int) -> bool:
        url = f"{self.base_host}/api/v1/client/trigger-classification?alertId={alert_id}"
        headers = {"Content-Type": "application/json"}
        logger.debug("[Classification] POST %s", url)
        try:
            resp = requests.post(url, headers=headers, timeout=config.classification_timeout_seconds)
            if not resp.ok:
                logger.error("[Classification] Failed: status=%s body=%s", resp.status_code, resp.text[:500])
                return False
            try:
                data = resp.json()
                logger.debug("[Classification] Response JSON: %s", data)
            except Exception:
                logger.warning("[Classification] Non-JSON response")
            logger.info("[Classification] Success alertId=%s", alert_id)
            return True
        except requests.exceptions.Timeout:
            logger.error("[Classification] Timeout (>%ss) alertId=%s", config.classification_timeout_seconds, alert_id)
            return False
        except Exception as e:
            logger.error("[Classification] Error: %s", e)
            return False

    # Stage 3: Solving / Task Agent
    def solve_alert(self, alert_id: int) -> bool:
        if alert_id in self._processed_alert_ids:
            logger.debug("[Task Agent] Skipping duplicate solve for alertId=%s (already processed)", alert_id)
            return True
        url = f"{self.base_host}/api/v1/client/trigger-task-agent?alertId={alert_id}"
        headers = {"Content-Type": "application/json"}
        logger.debug("[Task Agent] POST %s", url)
        try:
            resp = requests.post(url, headers=headers, timeout=config.task_agent_timeout_seconds)
            if not resp.ok:
                logger.error("[Task Agent] Failed: status=%s body=%s", resp.status_code, resp.text[:500])
                return False
            logger.info("[Task Agent] Success alertId=%s", alert_id)
            self._processed_alert_ids.add(alert_id)
            return True
        except requests.exceptions.Timeout:
            logger.error("[Task Agent] Timeout (>%ss) alertId=%s", config.task_agent_timeout_seconds, alert_id)
            return False
        except Exception as e:
            logger.error("[Task Agent] Error: %s", e)
            return False

    def run_alert_flow(self, severity: str, ticket_message: str, created_by: Optional[str] = None) -> bool:
        creator = created_by or config.alert_created_by
        alert_id, ticket_id = self.create_alert(created_by=creator, severity=severity, ticket_message=ticket_message)
        if alert_id is None:
            return False
        classified = self.classify_alert(alert_id)
        if not classified:
            logger.error("[Alert Flow] Classification failed; stopping before solve (alertId=%s ticketId=%s)", alert_id, ticket_id)
            return False
        solved = self.solve_alert(alert_id)
        if not solved:
            logger.error("[Alert Flow] Solve/Task stage failed (alertId=%s ticketId=%s)", alert_id, ticket_id)
        return solved

    # Backward compatibility wrapper
    def post_alert(self, created_by: Optional[str], severity: str, ticket_message: str) -> bool:
        return self.run_alert_flow(severity=severity, ticket_message=ticket_message, created_by=created_by)

alert_client = AlertClient()
