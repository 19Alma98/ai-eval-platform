from __future__ import annotations

from collections.abc import Iterator

import pytest
from tests.support.reset import reset_sdk


@pytest.fixture(autouse=True)
def _reset_sdk_light() -> Iterator[None]:
    reset_sdk(otel=False)
    yield
    reset_sdk(otel=False)
