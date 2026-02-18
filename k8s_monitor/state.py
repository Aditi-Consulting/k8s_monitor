"""State snapshot and diff utilities for Kubernetes resources."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

@dataclass
class ClusterSnapshot:
    pods: Dict[str, str] = field(default_factory=dict)  # name -> phase
    pod_reasons: Dict[str, str] = field(default_factory=dict)  # name -> reason (e.g., CrashLoopBackOff, OOMKilled, Error, Terminating)
    services: Dict[str, List[Tuple[int, str]]] = field(default_factory=dict)  # name -> list of (port, protocol)
    deployments: Dict[str, int] = field(default_factory=dict)  # name -> replicas

    def summary_counts(self) -> Dict[str, int]:
        return {
            'pods': len(self.pods),
            'services': len(self.services),
            'deployments': len(self.deployments),
        }

EMPTY_SNAPSHOT = ClusterSnapshot()

def diff_snapshots(old: ClusterSnapshot, new: ClusterSnapshot) -> List[str]:
    changes: List[str] = []
    # Pod changes
    old_pods = set(old.pods.keys())
    new_pods = set(new.pods.keys())
    for added in sorted(new_pods - old_pods):
        changes.append(f"Pod added: {added} (phase={new.pods[added]})")
    for removed in sorted(old_pods - new_pods):
        changes.append(f"Pod removed: {removed} (was phase={old.pods[removed]})")
    for name in sorted(old_pods & new_pods):
        if old.pods[name] != new.pods[name]:
            changes.append(f"Pod phase changed: {name} {old.pods[name]} -> {new.pods[name]}")

    # Service changes
    old_svcs = set(old.services.keys())
    new_svcs = set(new.services.keys())
    for added in sorted(new_svcs - old_svcs):
        ports = ",".join(f"{p}/{proto}" for p, proto in new.services[added])
        changes.append(f"Service added: {added} (ports={ports})")
    for removed in sorted(old_svcs - new_svcs):
        ports = ",".join(f"{p}/{proto}" for p, proto in old.services[removed])
        changes.append(f"Service removed: {removed} (was ports={ports})")
    for name in sorted(old_svcs & new_svcs):
        old_ports = set(old.services[name])
        new_ports = set(new.services[name])
        if old_ports != new_ports:
            removed_ports = old_ports - new_ports
            added_ports = new_ports - old_ports
            if added_ports:
                changes.append(f"Service ports added: {name} +{sorted(list(added_ports))}")
            if removed_ports:
                changes.append(f"Service ports removed: {name} -{sorted(list(removed_ports))}")

    # Deployment changes
    old_deps = set(old.deployments.keys())
    new_deps = set(new.deployments.keys())
    for added in sorted(new_deps - old_deps):
        changes.append(f"Deployment added: {added} (replicas={new.deployments[added]})")
    for removed in sorted(old_deps - new_deps):
        changes.append(f"Deployment removed: {removed} (was replicas={old.deployments[removed]})")
    for name in sorted(old_deps & new_deps):
        if old.deployments[name] != new.deployments[name]:
            changes.append(f"Deployment replica change: {name} {old.deployments[name]} -> {new.deployments[name]}")

    # High-level count change summary (if counts changed and no granular changes captured)
    if not changes:
        if old.summary_counts() != new.summary_counts():
            changes.append(f"Counts changed: {old.summary_counts()} -> {new.summary_counts()}")
    return changes
