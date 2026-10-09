from __future__ import annotations

import uuid

from aiobs_server.domain.experiment import Experiment


def test_create_defaults_metrics_set_id_to_none() -> None:
    exp = Experiment.create(uuid.uuid4(), "run", uuid.uuid4())
    assert exp.metrics_set_id is None


def test_with_metrics_set_id_returns_new_instance() -> None:
    exp = Experiment.create(uuid.uuid4(), "run", uuid.uuid4())
    set_id = uuid.uuid4()
    updated = exp.with_metrics_set_id(set_id)
    assert updated.metrics_set_id == set_id
    assert exp.metrics_set_id is None
