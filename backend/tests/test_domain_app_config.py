from __future__ import annotations

import uuid

from aiobs_server.domain.app_config import AppConfig, compute_content_hash


def test_create_rejects_empty_name() -> None:
    try:
        AppConfig.create(uuid.uuid4(), "  ")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "empty" in str(exc).lower()


def test_create_defaults_sections_and_version() -> None:
    project_id = uuid.uuid4()
    cfg = AppConfig.create(project_id, "rag-faq")
    assert cfg.name == "rag-faq"
    assert cfg.version == 1
    assert cfg.prompt == {}
    assert cfg.model == {}
    assert cfg.retrieval == {}
    assert cfg.content_hash == compute_content_hash({}, {}, {})


def test_content_hash_stable_for_same_payload() -> None:
    a = compute_content_hash({"system": "x"}, {"model_id": "m"}, {"top_k": 5})
    b = compute_content_hash({"system": "x"}, {"model_id": "m"}, {"top_k": 5})
    assert a == b
    assert a != compute_content_hash({"system": "y"}, {"model_id": "m"}, {"top_k": 5})


def test_to_snapshot_includes_identity_and_sections() -> None:
    cfg = AppConfig.create(
        uuid.uuid4(),
        "rag-faq",
        version=3,
        prompt={"system": "s"},
        model={"model_id": "gpt"},
        retrieval={"top_k": 4},
    )
    snap = cfg.to_snapshot()
    assert snap["name"] == "rag-faq"
    assert snap["version"] == 3
    assert snap["app_config_id"] == str(cfg.id)
    assert snap["prompt"] == {"system": "s"}
    assert snap["model"] == {"model_id": "gpt"}
    assert snap["retrieval"] == {"top_k": 4}
    assert "content_hash" in snap


def test_experiment_create_accepts_app_config_id() -> None:
    from aiobs_server.domain.experiment import Experiment

    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    config_id = uuid.uuid4()
    exp = Experiment.create(
        project_id,
        "exp-1",
        dataset_id,
        app_config_id=config_id,
        model_config={"name": "rag-faq"},
    )
    assert exp.app_config_id == config_id
