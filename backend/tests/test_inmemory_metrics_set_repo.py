from __future__ import annotations

import uuid

import pytest

from aiobs.domain.metrics_set import MetricsSet
from tests.support.repositories import InMemoryMetricsSetRepository


@pytest.mark.asyncio
async def test_inmemory_next_version_and_project_default() -> None:
    repo = InMemoryMetricsSetRepository()
    pid = uuid.uuid4()
    first = await repo.add(MetricsSet.create_project_default(pid))
    assert (await repo.get_project_default(pid)).id == first.id
    assert await repo.next_version(pid, "Default") == 2
    listed = await repo.list_by_project(pid)
    assert [s.id for s in listed] == [first.id]
