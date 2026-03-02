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
import time
import threading

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
        # Random 12-char alphanumeric ticket ID (digits + lowercase)
        alphabet = string.ascii_lowercase + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(12))

    # Stage 1: Alert Creation
    def create_alert(self, created_by: str, severity: str, ticket_message: str) -> tuple[Optional[int], Optional[str]]:
        ticket_id = self._new_ticket_id()
        payload = {
            "ticketId": ticket_id,
            "createdBy": created_by,
            "severity": severity,
            "ticket": ticket_message,
            "source": "Kubernetes",
        }
        url = self.base_url
        
        # Start timing
        start_time = time.time()
        logger.info("[Alert Creation] Starting alert creation with ticketId=%s", ticket_id)
        logger.debug("[Alert Creation] POST %s payload=%s", url, payload)
        
        try:
            # Time the HTTP request
            request_start = time.time()
            resp = requests.post(url, json=payload, timeout=config.alert_timeout_seconds)
            request_duration = time.time() - request_start
            
            logger.info("[Alert Creation] HTTP request completed in %.2fs (status=%s)", 
                       request_duration, resp.status_code)
            
            if not resp.ok:
                logger.error("[Alert Creation] Failed: status=%s body=%s", resp.status_code, resp.text[:500])
                return None, ticket_id
            
            # Time JSON parsing
            parse_start = time.time()
            alert_id = None
            try:
                data = resp.json()
                parse_duration = time.time() - parse_start
                logger.debug("[Alert Creation] Response JSON parsed in %.3fs: %s", 
                           parse_duration, data)
                alert_id = data.get("id")
            except Exception:
                logger.warning("[Alert Creation] Non-JSON response")
                
            if not isinstance(alert_id, int):
                logger.error("[Alert Creation] Missing numeric 'id' in response; aborting flow. ticketId=%s", ticket_id)
                return None, ticket_id
            
            total_duration = time.time() - start_time
            logger.info("[Alert Creation] Success id=%s ticketId=%s (total time: %.2fs)", 
                       alert_id, ticket_id, total_duration)
            # Track created ticket IDs to help diagnose duplicates
            self._created_ticket_ids.add(ticket_id)
            return alert_id, ticket_id
        except requests.exceptions.Timeout:
            duration = time.time() - start_time
            logger.error("[Alert Creation] Timeout after %.2fs (limit: %ss) ticketId=%s", 
                        duration, config.alert_timeout_seconds, ticket_id)
            return None, ticket_id
        except Exception as e:
            duration = time.time() - start_time
            logger.error("[Alert Creation] Error after %.2fs: %s ticketId=%s", 
                        duration, e, ticket_id)
            return None, ticket_id

    # Stage 2: Classification
    def classify_alert(self, alert_id: int) -> bool:
        url = f"{self.base_host}/api/v1/client/trigger-classification?alertId={alert_id}"
        headers = {"Content-Type": "application/json"}
        
        start_time = time.time()
        logger.info("[Classification] Starting classification for alertId=%s", alert_id)
        logger.debug("[Classification] POST %s", url)
        
        try:
            resp = requests.post(url, headers=headers, timeout=config.classification_timeout_seconds)
            duration = time.time() - start_time
            
            logger.info("[Classification] Request completed in %.2fs (status=%s)", 
                       duration, resp.status_code)
            
            if not resp.ok:
                logger.error("[Classification] Failed: status=%s body=%s", resp.status_code, resp.text[:500])
                return False
            try:
                data = resp.json()
                logger.debug("[Classification] Response JSON: %s", data)
            except Exception:
                logger.warning("[Classification] Non-JSON response")
            logger.info("[Classification] Success alertId=%s (%.2fs)", alert_id, duration)
            return True
        except requests.exceptions.Timeout:
            duration = time.time() - start_time
            logger.error("[Classification] Timeout after %.2fs (limit: %ss) alertId=%s", 
                        duration, config.classification_timeout_seconds, alert_id)
            return False
        except Exception as e:
            duration = time.time() - start_time
            logger.error("[Classification] Error after %.2fs: %s", duration, e)
            return False

    # Stage 3: Solving / Task Agent
    def solve_alert(self, alert_id: int) -> bool:
        if alert_id in self._processed_alert_ids:
            logger.debug("[Task Agent] Skipping duplicate solve for alertId=%s (already processed)", alert_id)
            return True
            
        url = f"{self.base_host}/api/v1/client/trigger-task-agent?alertId={alert_id}"
        headers = {"Content-Type": "application/json"}
        
        start_time = time.time()
        logger.info("[Task Agent] Starting task agent for alertId=%s", alert_id)
        logger.debug("[Task Agent] POST %s", url)
        
        try:
            resp = requests.post(url, headers=headers, timeout=config.task_agent_timeout_seconds)
            duration = time.time() - start_time
            
            logger.info("[Task Agent] Request completed in %.2fs (status=%s)", 
                       duration, resp.status_code)
            
            if not resp.ok:
                logger.error("[Task Agent] Failed: status=%s body=%s", resp.status_code, resp.text[:500])
                return False
            logger.info("[Task Agent] Success alertId=%s (%.2fs)", alert_id, duration)
            self._processed_alert_ids.add(alert_id)
            return True
        except requests.exceptions.Timeout:
            duration = time.time() - start_time
            logger.error("[Task Agent] Timeout after %.2fs (limit: %ss) alertId=%s", 
                        duration, config.task_agent_timeout_seconds, alert_id)
            return False
        except Exception as e:
            duration = time.time() - start_time
            logger.error("[Task Agent] Error after %.2fs: %s", duration, e)
            return False

    def _run_classification_and_task_async(self, alert_id: int, ticket_id: str):
        """Run classification and task agent sequentially in background thread"""
        try:
            logger.info("[Alert Flow Background] Starting classification for alertId=%s", alert_id)
            classified = self.classify_alert(alert_id)
            if not classified:
                logger.error("[Alert Flow Background] Classification failed, stopping flow (alertId=%s ticketId=%s)", 
                           alert_id, ticket_id)
                return
            
            logger.info("[Alert Flow Background] Classification success, starting task agent (alertId=%s)", alert_id)
            solved = self.solve_alert(alert_id)
            if solved:
                logger.info("[Alert Flow Background] Complete flow finished successfully (alertId=%s ticketId=%s)", 
                           alert_id, ticket_id)
            else:
                logger.error("[Alert Flow Background] Task agent failed (alertId=%s ticketId=%s)", 
                           alert_id, ticket_id)
        except Exception as e:
            logger.error("[Alert Flow Background] Unexpected error: %s (alertId=%s ticketId=%s)", 
                        e, alert_id, ticket_id)

    def run_alert_flow(self, severity: str, ticket_message: str, created_by: Optional[str] = None) -> bool:
        creator = created_by or config.alert_created_by
        
        flow_start = time.time()
        logger.info("[Alert Flow] Starting alert creation (async mode)")
        
        # Step 1: Create alert synchronously (fast - ~0.3s)
        alert_id, ticket_id = self.create_alert(created_by=creator, severity=severity, ticket_message=ticket_message)
        if alert_id is None:
            logger.error("[Alert Flow] Alert creation failed, aborting flow")
            return False
        
        creation_duration = time.time() - flow_start
        logger.info("[Alert Flow] ✅ Alert created in %.2fs (alertId=%s ticketId=%s)", 
                   creation_duration, alert_id, ticket_id)
        
        # Step 2: Start classification and task agent in background thread
        logger.info("[Alert Flow] Spawning background thread for classification → task agent")
        bg_thread = threading.Thread(
            target=self._run_classification_and_task_async,
            args=(alert_id, ticket_id),
            name=f"alert-flow-{alert_id}",
            daemon=True
        )
        bg_thread.start()
        
        logger.info("[Alert Flow] ⚡ Returning immediately (background processing started)")
        return True

    # Backward compatibility wrapper
    def post_alert(self, created_by: Optional[str], severity: str, ticket_message: str) -> bool:
        return self.run_alert_flow(severity=severity, ticket_message=ticket_message, created_by=created_by)

alert_client = AlertClient()
