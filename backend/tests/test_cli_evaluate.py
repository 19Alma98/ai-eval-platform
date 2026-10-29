from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from opengrade_server.cli import (
    EXIT_CONFIG,
    EXIT_GATE_FAILED,
    EXIT_PASS,
    app,
    split_meta,
)
from opengrade_server.cli_evaluate import (
    EvaluateConfigError,
    apply_judge_env,
    load_task_from_ref,
    load_task_from_script,
    resolve_evaluate_config,
    split_config,
)

runner = CliRunner()


def test_split_meta_strips_evaluate_for_check() -> None:
    raw = {
        "api_base_url": "http://localhost:8000",
        "project_id": "11111111-1111-1111-1111-111111111111",
        "experiment_id": "22222222-2222-2222-2222-222222222222",
        "evaluate": {"task": "m:t", "dataset": "x", "metrics": ["hit_at_k"]},
        "hit_at_k": {"min": 0.8},
    }
    meta, policy = split_meta(raw)
    assert "evaluate" not in meta
    assert policy == {"hit_at_k": {"min": 0.8}}
    assert meta["project_id"].startswith("1111")


def test_split_config_keeps_evaluate_block() -> None:
    raw = {
        "project": "demo",
        "evaluate": {"task": "pkg:fn", "from_experiment": "abc"},
        "latency": {"p95_max_ms": 1000},
    }
    meta, block, policy = split_config(raw)
    assert meta["project"] == "demo"
    assert block["from_experiment"] == "abc"
    assert policy == {"latency": {"p95_max_ms": 1000}}


def test_resolve_xor_task_and_exam(tmp_path: Path) -> None:
    with pytest.raises(EvaluateConfigError, match="exactly one"):
        resolve_evaluate_config({"evaluate": {}})
    with pytest.raises(EvaluateConfigError, match="exam definition"):
        resolve_evaluate_config({"evaluate": {"task": "pkg:fn"}})
    with pytest.raises(EvaluateConfigError, match="XOR"):
        resolve_evaluate_config(
            {
                "evaluate": {
                    "task": "pkg:fn",
                    "from_experiment": "e1",
                    "dataset": "d.csv",
                    "metrics": ["hit_at_k"],
                }
            }
        )
    cfg = resolve_evaluate_config(
        {
            "evaluate": {
                "task": "pkg:fn",
                "dataset": "d.csv",
                "metrics": ["hit_at_k", "latency"],
            }
        }
    )
    assert cfg.task_ref == "pkg:fn"
    assert cfg.metrics == ["hit_at_k", "latency"]


def test_load_task_from_ref() -> None:
    fn = load_task_from_ref("json:dumps")
    assert callable(fn)
    assert fn({"a": 1}) == '{"a": 1}'


def test_load_task_from_script(tmp_path: Path) -> None:
    path = tmp_path / "task_mod.py"
    path.write_text(
        "DATASET = 'gold.csv'\nMETRICS = ['hit_at_k']\ndef task(item):\n    return 'ok'\n",
        encoding="utf-8",
    )
    task, extras = load_task_from_script(path)
    assert task(None) == "ok"
    assert extras["dataset"] == "gold.csv"
    assert extras["metrics"] == ["hit_at_k"]


def test_apply_judge_api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from opengrade_server.cli_evaluate import EvaluateConfig

    cfg = EvaluateConfig(
        base_url=None,
        project="demo",
        task_ref="pkg:fn",
        from_experiment="e1",
        judge_api_key_env="MY_JUDGE_KEY",
    )
    with pytest.raises(EvaluateConfigError, match="unset"):
        apply_judge_env(cfg)
    monkeypatch.setenv("MY_JUDGE_KEY", "secret-value")
    apply_judge_env(cfg)
    assert __import__("os").environ["LLM_API_KEY"] == "secret-value"


def test_evaluate_cli_config_error_missing_exam(tmp_path: Path) -> None:
    path = tmp_path / "opengrade.yaml"
    path.write_text(
        "evaluate:\n  task: json:dumps\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["evaluate", "--config", str(path)])
    assert result.exit_code == EXIT_CONFIG


def test_check_ignores_evaluate_block(tmp_path: Path) -> None:
    path = tmp_path / "opengrade.yaml"
    path.write_text(
        """api_base_url: http://localhost:8000
project_id: 11111111-1111-1111-1111-111111111111
experiment_id: 22222222-2222-2222-2222-222222222222
evaluate:
  task: pkg:fn
  dataset: x.csv
  metrics: [hit_at_k]
hit_at_k:
  min: 0.8
""",
        encoding="utf-8",
    )
    from unittest.mock import MagicMock, patch

    with patch("opengrade_server.cli_evaluate.httpx2.post") as post:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"status": "passed", "checks": []}
        post.return_value = response
        result = runner.invoke(app, ["check", "--policy", str(path)])
    assert result.exit_code == EXIT_PASS
    sent = post.call_args.kwargs["json"]["policy"]
    assert "evaluate" not in sent
    assert sent == {"hit_at_k": {"min": 0.8}}


def _write_bootstrap_files(tmp_path: Path) -> tuple[Path, Path]:
    dataset = tmp_path / "gold.json"
    dataset.write_text(
        '[{"input": "q1", "expected_output": "a1", "expected_doc_ids": ["d1"]},'
        ' {"input": "q2", "expected_output": "a2", "expected_doc_ids": ["d1"]}]\n',
        encoding="utf-8",
    )
    task_py = tmp_path / "rag_task.py"
    task_py.write_text(
        """
import opengrade

def task(item):
    opengrade.set_retrieval_documents([{"id": "d1", "text": "doc"}])
    return f"answer to {item.input}"
""",
        encoding="utf-8",
    )
    config = tmp_path / "opengrade.yaml"
    config.write_text(
        f"""project: ci-demo
evaluate:
  script: {task_py.as_posix()}
  dataset: {dataset.as_posix()}
  metrics: [hit_at_k]
  name: ci-smoke
  max_concurrency: 1
hit_at_k:
  min: 0.4
""",
        encoding="utf-8",
    )
    return config, task_py


def test_evaluate_embedded_bootstrap_and_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spin embedded API, run evaluate + policy (deterministic hit_at_k)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    config, _ = _write_bootstrap_files(tmp_path)

    result = runner.invoke(app, ["evaluate", "--config", str(config), "--json"])
    assert result.exit_code == EXIT_PASS, result.output
    assert "experiment_id" in result.output

    # Impossible threshold so the same setup fails the gate
    fail_config = tmp_path / "fail.yaml"
    fail_config.write_text(
        config.read_text(encoding="utf-8").replace("min: 0.4", "min: 1.1"),
        encoding="utf-8",
    )
    failed = runner.invoke(app, ["evaluate", "--config", str(fail_config)])
    assert failed.exit_code == EXIT_GATE_FAILED, failed.output


def _json_tail(output: str) -> dict[str, Any]:
    start = output.index("{\n")
    parsed, _ = json.JSONDecoder().raw_decode(output[start:])
    assert isinstance(parsed, dict)
    return parsed


def test_resolve_promote_requires_policy_and_reads_yaml() -> None:
    block = {"task": "pkg:fn", "dataset": "x.csv", "metrics": ["hit_at_k"]}
    with pytest.raises(EvaluateConfigError, match="promote needs policy"):
        resolve_evaluate_config({"evaluate": {**block, "promote": "main"}})
    with pytest.raises(EvaluateConfigError, match="empty alias"):
        resolve_evaluate_config({"evaluate": {**block, "baseline": "alias: "}})
    cfg = resolve_evaluate_config(
        {
            "evaluate": {**block, "promote": "main", "version": "abc123"},
            "hit_at_k": {"min": 0.1},
        },
        version="def456",
    )
    assert cfg.promote == "main"
    assert cfg.version == "def456"


def _git_commit(repo: Path, marker: str) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    if not (repo / ".git").exists():
        git("init", "-q", "-b", "main")
        git("config", "user.email", "t@example.com")
        git("config", "user.name", "t")
    (repo / "marker.txt").write_text(marker, encoding="utf-8")
    git("add", "marker.txt")
    git("commit", "-q", "-m", marker)


def test_evaluate_promotes_alias_and_compares_against_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    config, _ = _write_bootstrap_files(tmp_path)
    rows = [
        {"input": f"q{i}", "expected_output": "a", "expected_doc_ids": ["d1"]} for i in range(5)
    ]
    (tmp_path / "gold.json").write_text(json.dumps(rows), encoding="utf-8")
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "  max_concurrency: 1\n",
            "  max_concurrency: 1\n  baseline: alias:main\n  promote: main\n",
        )
        + "regression:\n  max_delta: -0.05\n",
        encoding="utf-8",
    )
    store = f"sqlite+aiosqlite:///{(tmp_path / 'store.db').as_posix()}"
    common = ["evaluate", "--config", str(config), "--backend-store-uri", store, "--json"]

    _git_commit(tmp_path, "v1")
    first = runner.invoke(app, [*common, "--version", "sha-1"])
    assert first.exit_code == EXIT_PASS, first.output
    assert "No baseline yet" in first.output
    one = _json_tail(first.output)
    assert one["baseline_id"] is None
    assert one["version"] == "sha-1"
    assert one["promoted"]["experiment_id"] == one["experiment_id"]
    assert one["promoted"]["previous_experiment_id"] is None

    assert one["git"]["branch"] == "main" and one["git"]["dirty"] is False

    _git_commit(tmp_path, "v2")
    second = runner.invoke(app, [*common, "--version", "sha-2"])
    assert second.exit_code == EXIT_PASS, second.output
    two = _json_tail(second.output)
    assert two["baseline_id"] == one["experiment_id"]
    assert two["baseline_git"] == one["git"]
    assert two["git"]["commit"] != one["git"]["commit"]
    assert any(c["metric"].startswith("regression.") for c in two["checks"]), two["checks"]
    assert two["promoted"]["previous_experiment_id"] == one["experiment_id"]

    failing = tmp_path / "failing.yaml"
    failing.write_text(
        config.read_text(encoding="utf-8").replace("min: 0.4", "min: 1.1"), encoding="utf-8"
    )
    third = runner.invoke(
        app,
        ["evaluate", "--config", str(failing), "--backend-store-uri", store, "--json"],
    )
    assert third.exit_code == EXIT_GATE_FAILED, third.output
    three = _json_tail(third.output)
    assert three["baseline_id"] == two["experiment_id"]
    assert three["promoted"] is None

    task_py = tmp_path / "rag_task.py"
    reuse = tmp_path / "reuse.yaml"
    reuse.write_text(
        f"""project: ci-demo
evaluate:
  script: {task_py.as_posix()}
  from_experiment: alias:main
hit_at_k:
  min: 0.4
regression:
  max_delta: -0.05
""",
        encoding="utf-8",
    )
    reread = runner.invoke(
        app, ["evaluate", "--config", str(reuse), "--backend-store-uri", store, "--json"]
    )
    assert reread.exit_code == EXIT_PASS, reread.output
    assert _json_tail(reread.output)["baseline_id"] == two["experiment_id"]

    rows.append({"input": "q-new", "expected_output": "a", "expected_doc_ids": ["d1"]})
    (tmp_path / "gold.json").write_text(json.dumps(rows), encoding="utf-8")
    changed = runner.invoke(app, [*common, "--version", "sha-3"])
    assert changed.exit_code == EXIT_PASS, changed.output
    assert "Exam changed" in changed.output
    four = _json_tail(changed.output)
    assert four["baseline_id"] is None
    assert not any(c["metric"].startswith("regression.") for c in four["checks"])
    assert four["promoted"]["exam_changed"] is True
    assert four["promoted"]["previous_experiment_id"] == two["experiment_id"]
