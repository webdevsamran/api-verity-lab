"""The chart, held against the application it deploys.

`helm lint` checks the chart is a chart. It cannot check that `VERITY_LOG_LEVEL`
is a setting the server reads, that `/healthz` is a route, or that
`replicaCount: 3` would be data loss — and those are the three ways a chart is
wrong while rendering perfectly.

So this reads the templates as text (they are Go templates, not YAML) and binds
what they claim to what the code does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_CHART = _ROOT / "deploy/helm/apiverity"
_TEMPLATES = _CHART / "templates"


def _template_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(_TEMPLATES.glob("*")))


def _env_names() -> set[str]:
    return set(re.findall(r"- name: (VERITY_[A-Z_]+)", _template_text()))


def test_every_variable_the_launcher_documents_can_be_set_from_the_chart() -> None:
    """`ENVIRONMENT` in the launcher is the contract; the chart is one way of
    satisfying it. A variable the launcher reads and the chart cannot set is a
    setting Kubernetes users do not have."""
    from apiverity.server.launch import ENVIRONMENT

    unsettable = set(ENVIRONMENT) - _env_names()
    assert not unsettable, f"the chart cannot set {sorted(unsettable)}"


def _code_env_names() -> set[str]:
    found: set[str] = set()
    for path in list((_ROOT / "apiverity").rglob("*.py")) + list((_ROOT / "docker").rglob("*")):
        if path.is_file():
            found.update(
                re.findall(r"VERITY_[A-Z_]+", path.read_text(encoding="utf-8", errors="replace"))
            )
    return found


# ------------------------------------------------------ it deploys this app


def test_every_variable_the_chart_sets_is_one_the_code_reads() -> None:
    """A value a chart sets that nothing reads is a setting somebody will
    change and wonder why nothing happened.

    `VERITY_LOG_LEVEL` was in the first draft of this chart and in no line of
    the application.
    """
    unread = _env_names() - _code_env_names()
    assert not unread, f"the chart sets {sorted(unread)}, which the application never reads"


def test_the_probe_path_is_a_real_route() -> None:
    text = _template_text()
    paths = set(re.findall(r"httpGet:\s*\n\s*path: (\S+)", text))
    assert paths, "the deployment declares no HTTP probe"
    api = (_ROOT / "apiverity/server/api.py").read_text(encoding="utf-8")
    for path in paths:
        assert f'"{path}"' in api, f"the chart probes {path}, which the server does not route"


def test_the_image_is_the_one_this_repository_builds() -> None:
    values = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))
    assert values["image"]["repository"] == "apiverity"
    dockerfile = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "apiverity" in dockerfile


def test_the_app_version_matches_the_package() -> None:
    """A chart shipping `appVersion: 0.1.0` for a 0.2.0 application is a
    version somebody will trust."""
    from apiverity import __version__

    chart = yaml.safe_load((_CHART / "Chart.yaml").read_text(encoding="utf-8"))
    assert str(chart["appVersion"]) == __version__


# --------------------------------------------- what it refuses to render


def test_more_than_one_replica_is_refused_rather_than_rendered() -> None:
    """The server keeps everything in one SQLite file. Two replicas writing to
    one ReadWriteOnce volume is data loss, so a `--set replicaCount=3` that
    rendered successfully would be the chart agreeing to something that cannot
    work."""
    deployment = (_TEMPLATES / "deployment.yaml").read_text(encoding="utf-8")
    assert "fail " in deployment
    assert "replicaCount" in deployment.split("fail ")[0]
    assert "data loss" in deployment


def test_the_rollout_strategy_cannot_run_two_pods_at_once() -> None:
    """A RollingUpdate would hold the same SQLite file in two pods for the
    length of the rollout — the exact state the replica check prevents."""
    deployment = (_TEMPLATES / "deployment.yaml").read_text(encoding="utf-8")
    assert "type: Recreate" in deployment
    # The value, not the word: the comment above it explains why RollingUpdate
    # is wrong here, and a bare substring check reads that explanation as the
    # setting.
    assert "type: RollingUpdate" not in deployment


# --------------------------------------------------------------- defaults


def test_the_defaults_suit_a_disconnected_cluster() -> None:
    values = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))
    # No registry host: the reference resolves to whatever the cluster serves.
    assert "/" not in values["image"]["repository"]
    # And no reaching out for a digest already held.
    assert values["image"]["pullPolicy"] == "IfNotPresent"


def test_it_runs_unprivileged_with_a_read_only_root() -> None:
    values = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))
    assert values["podSecurityContext"]["runAsNonRoot"] is True
    assert values["securityContext"]["readOnlyRootFilesystem"] is True
    assert values["securityContext"]["capabilities"]["drop"] == ["ALL"]


def test_a_read_only_root_gets_the_writable_paths_it_needs() -> None:
    """Python writes to /tmp, and `readOnlyRootFilesystem` means every path the
    process writes needs a volume. Without this the pod starts and fails on the
    first temporary file."""
    deployment = (_TEMPLATES / "deployment.yaml").read_text(encoding="utf-8")
    assert "mountPath: /tmp" in deployment
    assert "mountPath: /data" in deployment


def test_the_data_volume_survives_deleting_the_release() -> None:
    """The audit log is hash-chained and the approvals are a record somebody
    may need later."""
    pvc = (_TEMPLATES / "pvc.yaml").read_text(encoding="utf-8")
    assert '"helm.sh/resource-policy": keep' in pvc


def test_persistence_off_is_stated_rather_than_discovered() -> None:
    notes = (_TEMPLATES / "NOTES.txt").read_text(encoding="utf-8")
    assert "emptyDir" in notes
    assert "gone when the pod restarts" in notes


# ------------------------------------------------------------ egress claims


def test_the_network_policy_is_off_by_default_and_says_why() -> None:
    """A cluster whose CNI does not implement NetworkPolicy applies it
    cleanly and enforces nothing, which is worse than not having one."""
    values = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))
    assert values["networkPolicy"]["enabled"] is False
    policy = (_TEMPLATES / "networkpolicy.yaml").read_text(encoding="utf-8")
    assert "enforces nothing" in policy
    notes = (_TEMPLATES / "NOTES.txt").read_text(encoding="utf-8")
    assert "enforces nothing" in notes


@pytest.mark.parametrize(
    "name", ["Chart.yaml", "values.yaml", "templates/deployment.yaml", "templates/service.yaml"]
)
def test_the_chart_has_the_files_helm_requires(name: str) -> None:
    assert (_CHART / name).is_file()
