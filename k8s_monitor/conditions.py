"""Alert condition rules for Kubernetes monitoring.

This module defines alert-generating conditions used by the monitor.
Each rule implements `evaluate(previous, current)` and returns a list of AlertEvent.
`evaluate_alert_rules(previous, current)` aggregates all rule outputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List
import threading
import logging

from .state import ClusterSnapshot
from .config import config
from .emailer import emailer
from .alerts import alert_client

logger = logging.getLogger(__name__)

@dataclass
class AlertEvent:
    key: str
    severity: str
    message: str
    subject: str
    rule: str

def _send_alert_and_email_parallel(severity: str, message: str, subject: str, key: str):
    """Send alert creation and email in parallel threads"""
    logger.info("[Parallel Trigger] Starting alert + email for %s", key)
    
    def create_alert_task():
        try:
            logger.info("[Alert Thread] Creating alert for %s", key)
            alert_client.run_alert_flow(
                severity=severity,
                ticket_message=message,
                created_by=config.alert_created_by
            )
            logger.info("[Alert Thread] ✅ Alert creation initiated for %s", key)
        except Exception as e:
            logger.error("[Alert Thread] ❌ Failed to create alert for %s: %s", key, e)
    
    def send_email_task():
        try:
            logger.info("[Email Thread] Sending email for %s", key)
            emailer.send(subject=subject, lines=[message])
            logger.info("[Email Thread] ✅ Email sent for %s", key)
        except Exception as e:
            logger.error("[Email Thread] ❌ Failed to send email for %s: %s", key, e)
    
    # Start both tasks in parallel
    alert_thread = threading.Thread(target=create_alert_task, name=f"alert-{key}", daemon=True)
    email_thread = threading.Thread(target=send_email_task, name=f"email-{key}", daemon=True)
    
    alert_thread.start()
    email_thread.start()
    
    logger.info("[Parallel Trigger] ⚡ Alert and email threads started for %s", key)

class ReplicasBelowThresholdRule:
    name = "replicas_below_threshold"

    def evaluate(self, previous: ClusterSnapshot, current: ClusterSnapshot) -> List[AlertEvent]:
        events: List[AlertEvent] = []
        threshold = config.min_replicas_threshold
        for key, replicas in current.deployments.items():
            prev_replicas = previous.deployments.get(key)
            if "/" in key:
                ns, name = key.split("/", 1)
            else:
                ns, name = "default", key
            # Trigger only when current replicas are strictly below threshold
            crossed_below = (prev_replicas is None and replicas < threshold) or (prev_replicas is not None and prev_replicas >= threshold and replicas < threshold)
            changed_while_below = prev_replicas is not None and prev_replicas < threshold and replicas < threshold and replicas != prev_replicas
            if crossed_below or changed_while_below:
                severity = "medium" if replicas > 0 else "high"
                msg = (
                    f"Alert: Deployment '{name}' is experiencing high workload and currently running on "
                    f"{replicas} replicas, but required capacity is {threshold} in namespace {ns}."
                )
                subject = f"Deployment replicas below threshold: {ns}/{name} ({replicas} < {threshold})"
                
                # Trigger alert and email in parallel if alerts are enabled
                if config.alerts_enabled:
                    _send_alert_and_email_parallel(severity, msg, subject, key)
                
                events.append(AlertEvent(key=key, severity=severity, message=msg, subject=subject, rule=self.name))
        return events

# class PodHealthRule:
#     name = "pod_health"
#     unhealthy_reasons = {"CrashLoopBackOff", "Error", "OOMKilled", "Terminating"}

#     def evaluate(self, previous: ClusterSnapshot, current: ClusterSnapshot) -> List[AlertEvent]:
#         events: List[AlertEvent] = []
#         for key, phase in current.pods.items():
#             prev_phase = previous.pods.get(key)
#             # Trigger only when a pod transitions from Running to a different phase
#             if prev_phase == "Running" and phase != "Running":
#                 ns, name = (key.split("/", 1) + ["default"])[:2]
#                 reason = current.pod_reasons.get(key, "")
#                 # Build meaningful alert messages starting with 'Alert: ...'
#                 if reason == "CrashLoopBackOff":
#                     msg = f"Alert: Pod '{name}' in namespace {ns} is stuck in CrashLoopBackOff — repeated restart failures detected."
#                 elif reason == "OOMKilled":
#                     msg = f"Alert: Pod '{name}' in namespace {ns} was OOMKilled — memory exhaustion detected."
#                 elif reason == "Error":
#                     msg = f"Alert: Pod '{name}' in namespace {ns} encountered an Error state — investigation required."
#                 elif reason == "Terminating":
#                     msg = f"Alert: Pod '{name}' in namespace {ns} is Terminating — unexpected shutdown observed."
#                 elif phase == "Pending":
#                     msg = f"Alert: Pod '{name}' is unreachable in namespace {ns}."
#                 else:
#                     msg = f"Alert: Pod '{name}' is down in namespace {ns}."
#                 subject = f"Pod health alert: {ns}/{name} (phase={phase}{', reason='+reason if reason else ''})"
#                 sev = "high" if (reason in {"CrashLoopBackOff", "Error", "OOMKilled"}) else "medium"
                
#                 # Trigger alert and email in parallel if alerts are enabled
#                 if config.alerts_enabled:
#                     _send_alert_and_email_parallel(sev, msg, subject, key)
                
#                 events.append(AlertEvent(key=key, severity=sev, message=msg, subject=subject, rule=self.name))
#         return events

# class ServicePortPolicyRule:
#     name = "service_port_policy"
#     nginx_expected_port = 8089
#     kubernetes_expected_port = 443

#     def evaluate(self, previous: ClusterSnapshot, current: ClusterSnapshot) -> List[AlertEvent]:
#         events: List[AlertEvent] = []
#         for key, ports in current.services.items():
#             ns, svc = (key.split("/", 1) + ["default"])[:2]
#             if ns != "default":
#                 continue
#             # Disabled nginx-service port enforcement per request
#             # if svc == "nginx-service":
#             #     expected = self.nginx_expected_port
#             if svc == "kubernetes":
#                 expected = self.kubernetes_expected_port
#             else:
#                 continue
#             actual_ports = {p for p, _proto in ports}
#             if expected not in actual_ports:
#                 msg1 = f"Alert: Service {svc} in namespace {ns} is exposing incorrect port. Expected port: {expected}."
#                 subject = f"Service port policy alert: {ns}/{svc} expected {expected}, actual={sorted(list(actual_ports))}"
                
#                 # Trigger alert and email in parallel if alerts are enabled
#                 if config.alerts_enabled:
#                     _send_alert_and_email_parallel("medium", msg1, subject, key)
                
#                 events.append(AlertEvent(key=key, severity="medium", message=msg1, subject=subject, rule=self.name))
#         return events

_RULES = [
    ReplicasBelowThresholdRule(),
    # PodHealthRule(),
    # ServicePortPolicyRule(),
]

def evaluate_alert_rules(previous: ClusterSnapshot, current: ClusterSnapshot) -> List[AlertEvent]:
    all_events: List[AlertEvent] = []
    if not config.alerts_enabled:
        return all_events
    for rule in _RULES:
        try:
            all_events.extend(rule.evaluate(previous, current))
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Rule %s failed: %s", getattr(rule, 'name', rule.__class__.__name__), e)
    return all_events
