from __future__ import annotations

import json
from pathlib import Path

import pytest

from opengrade_server.evaluation.judges import prompts
from opengrade_server.evaluation.judges.evaluators import JudgeDefaults, create_llm_judge
from opengrade_server.evaluation.judges.snapshots import upsert_prompt_snapshot
from opengrade_server.evaluation.protocol import EvaluationSample
from tests.support.fake_llm import ScriptedJudgeLlm


def test_upsert_prompt_snapshot_writes_bundle(tmp_path: Path) -> None:
    path = tmp_path / "snaps.json"
    upsert_prompt_snapshot("groundedness", "claims", path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    digest = prompts.content_hash(prompts.bundle_for("groundedness", "claims"))
    assert digest in data
    entry = data[digest]
    assert entry["kind"] == "groundedness"
    assert entry["method"] == "claims"
    assert entry["prompt_version"] == prompts.prompt_version("groundedness", "claims")
    assert entry["bundle"] == prompts.bundle_for("groundedness", "claims")
    assert "updated_at" in entry


def test_upsert_merges_without_clobbering_other_hashes(tmp_path: Path) -> None:
    path = tmp_path / "snaps.json"
    upsert_prompt_snapshot("groundedness", "claims", path=path)
    upsert_prompt_snapshot("answer_relevance", "rubric", path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 2
    g = prompts.content_hash(prompts.bundle_for("groundedness", "claims"))
    a = prompts.content_hash(prompts.bundle_for("answer_relevance", "rubric"))
    assert set(data) == {g, a}


def test_upsert_failure_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "missing" / "snaps.json"

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(
        "opengrade_server.evaluation.judges.snapshots._write_entry",
        boom,
    )
    upsert_prompt_snapshot("groundedness", "claims", path=path)  # must not raise


@pytest.mark.asyncio
async def test_snapshot_written_on_evaluate_not_construct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "snaps.json"
    monkeypatch.setenv("OPENGRADE_JUDGE_PROMPT_SNAPSHOTS", str(path))
    judge = create_llm_judge(
        "groundedness",
        {},
        ScriptedJudgeLlm(),
        defaults=JudgeDefaults(model="test-model"),
    )
    assert not path.exists()
    await judge.evaluate(
        EvaluationSample(
            input="q",
            expected_output=None,
            actual_output=None,
            context=None,
        )
    )
    assert path.is_file()
    assert prompts.content_hash(prompts.bundle_for("groundedness", "claims")) in json.loads(
        path.read_text(encoding="utf-8")
    )
