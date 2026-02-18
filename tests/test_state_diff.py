from k8s_monitor.state import ClusterSnapshot, diff_snapshots


def test_diff_add_remove():
    old = ClusterSnapshot()
    new = ClusterSnapshot(pods={"default/pod1": "Running"})
    changes = diff_snapshots(old, new)
    assert any("Pod added" in c for c in changes)


def test_diff_pod_phase_change():
    old = ClusterSnapshot(pods={"default/pod1": "Pending"})
    new = ClusterSnapshot(pods={"default/pod1": "Running"})
    changes = diff_snapshots(old, new)
    assert any("phase changed" in c for c in changes)


def test_diff_service_ports():
    old = ClusterSnapshot(services={"default/svc": [(80, "TCP")]})
    new = ClusterSnapshot(services={"default/svc": [(80, "TCP"), (443, "TCP")]})
    changes = diff_snapshots(old, new)
    assert any("ports added" in c for c in changes)


def test_diff_deployment_replica_change():
    old = ClusterSnapshot(deployments={"default/dep": 1})
    new = ClusterSnapshot(deployments={"default/dep": 3})
    changes = diff_snapshots(old, new)
    assert any("replica change" in c for c in changes)
