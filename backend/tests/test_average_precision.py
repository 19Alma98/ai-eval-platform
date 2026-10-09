from __future__ import annotations

import pytest

from aiobs_server.evaluation.judges.claims import average_precision


def test_average_precision_all_irrelevant() -> None:
    assert average_precision([False, False, False]) == 0.0


def test_average_precision_first_relevant() -> None:
    assert average_precision([True, False, False]) == 1.0


def test_average_precision_interleaved() -> None:
    # relevant at ranks 1 and 3: (1/1 + 2/3) / 2
    assert average_precision([True, False, True]) == pytest.approx(5 / 6)


def test_average_precision_empty() -> None:
    assert average_precision([]) == 0.0
