from __future__ import annotations

import uuid

from aiobs.domain.experiment_output import ExperimentItemOutput


def test_create_and_patch_clears_and_preserves() -> None:
    exp = uuid.uuid4()
    item = uuid.uuid4()
    out = ExperimentItemOutput.create(
        experiment_id=exp,
        dataset_item_id=item,
        actual_output="v1",
        context={"latency_ms": 10},
        metadata={"src": "a"},
    )
    assert out.actual_output == "v1"

    patched = out.with_patch(actual_output="v2")  # omit context/metadata
    assert patched.actual_output == "v2"
    assert patched.context == {"latency_ms": 10}
    assert patched.metadata == {"src": "a"}

    cleared = patched.with_patch(context=None)
    assert cleared.context is None
