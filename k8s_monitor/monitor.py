"""Core monitoring logic for Kubernetes cluster."""
from __future__ import annotations

import logging
import time
from typing import Optional
from kubernetes import client, config as k8s_config
from kubernetes.client import ApiException

from .config import config
from .state import ClusterSnapshot, diff_snapshots, EMPTY_SNAPSHOT
from .emailer import emailer
from .alerts import alert_client
from .conditions import evaluate_alert_rules

logger = logging.getLogger(__name__)

# Skip system namespace from monitoring
KUBE_SYSTEM_NS = "kube-system"

class K8sMonitor:
    def __init__(self, poll_interval: Optional[int] = None):
        self.poll_interval = poll_interval or config.poll_interval_seconds
        self._previous: ClusterSnapshot = EMPTY_SNAPSHOT
        self._first_poll: bool = True
        self._load_client()

    def _load_client(self):
        try:
            if config.kube_context:
                k8s_config.load_kube_config(context=config.kube_context)
            else:
                k8s_config.load_kube_config()
            logger.info("Loaded kubeconfig (outside-cluster)")
        except Exception as e:
            logger.warning("Falling back to in-cluster config: %s", e)
            try:
                k8s_config.load_incluster_config()
                logger.info("Loaded in-cluster config")
            except Exception as e2:
                logger.error("Failed to load any Kubernetes config: %s", e2)
                raise
        self.core = client.CoreV1Api()
        self.apps = client.AppsV1Api()

    def _snapshot(self) -> ClusterSnapshot:
        pods = {}
        pod_reasons = {}
        services = {}
        deployments = {}
        try:
            pod_list = self.core.list_pod_for_all_namespaces(watch=False)
            for p in pod_list.items:
                ns = p.metadata.namespace or ""
                if ns == KUBE_SYSTEM_NS:
                    continue
                key = f"{ns}/{p.metadata.name}"
                phase = p.status.phase or "Unknown"
                reason = ""
                # Try container statuses for detailed reasons
                try:
                    if p.status.container_statuses:
                        for cs in p.status.container_statuses:
                            if cs.state and getattr(cs.state, 'waiting', None) and cs.state.waiting.reason:
                                reason = cs.state.waiting.reason
                                break
                            if cs.state and getattr(cs.state, 'terminated', None) and cs.state.terminated.reason:
                                reason = cs.state.terminated.reason
                                break
                except Exception:
                    pass
                # Fallbacks
                if not reason and getattr(p.status, 'reason', None):
                    reason = p.status.reason or ""
                pods[key] = phase
                if reason:
                    pod_reasons[key] = reason
        except ApiException as e:
            logger.error("Error listing pods: %s", e)
        try:
            svc_list = self.core.list_service_for_all_namespaces(watch=False)
            for s in svc_list.items:
                ns = s.metadata.namespace or ""
                if ns == KUBE_SYSTEM_NS:
                    continue
                ports = []
                if s.spec.ports:
                    for port in s.spec.ports:
                        ports.append((port.port, port.protocol))
                services[f"{ns}/{s.metadata.name}"] = ports
        except ApiException as e:
            logger.error("Error listing services: %s", e)
        try:
            dep_list = self.apps.list_deployment_for_all_namespaces(watch=False)
            for d in dep_list.items:
                ns = d.metadata.namespace or ""
                if ns == KUBE_SYSTEM_NS:
                    continue
                replicas = (d.status.replicas or 0)
                deployments[f"{ns}/{d.metadata.name}"] = replicas
        except ApiException as e:
            logger.error("Error listing deployments: %s", e)
        return ClusterSnapshot(pods=pods, pod_reasons=pod_reasons, services=services, deployments=deployments)

    def _check_and_alert_replicas(self, current: ClusterSnapshot, previous: ClusterSnapshot):
        # Deprecated direct logic replaced by rule engine usage.
        events = evaluate_alert_rules(previous, current)
        for ev in events:
            emailer.send(subject=ev.subject, lines=[ev.message])
            from .alerts import alert_client  # local import to avoid circular at module load
            alert_client.post_alert(created_by=config.alert_created_by, severity=ev.severity, ticket_message=ev.message)

    def poll_once(self) -> None:
        current = self._snapshot()
        changes = diff_snapshots(self._previous, current)
        send_email = True
        if self._first_poll and config.skip_initial_email:
            # Suppress initial email to avoid large 'added' list when starting up.
            if changes:
                logger.info("Initial snapshot captured (%d changes suppressed).", len(changes))
            else:
                logger.info("Initial snapshot captured (no changes).")
            send_email = False
        if changes and send_email:
            logger.info("Detected %d change(s)", len(changes))
            subject = f"K8s changes detected ({len(changes)} event(s))"
            emailer.send(subject, changes)
        else:
            if not changes:
                logger.debug("No changes detected")
        # Evaluate replica alerts with transition logic against previous snapshot
        self._check_and_alert_replicas(current, self._previous)
        self._previous = current
        self._first_poll = False

    def run_forever(self):
        logger.info("Starting monitoring loop (interval=%s s, skip_initial_email=%s)", self.poll_interval, config.skip_initial_email)
        while True:
            start = time.time()
            try:
                self.poll_once()
            except Exception as e:
                logger.exception("Unexpected error during poll: %s", e)
            elapsed = time.time() - start
            sleep_for = max(0.0, self.poll_interval - elapsed)
            time.sleep(sleep_for)
