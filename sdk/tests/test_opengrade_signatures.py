from __future__ import annotations

import inspect

from opengrade._opengrade import Opengrade
from opengrade._otel import init_for_instance
from opengrade.experiment.api import evaluate, start_experiment
from opengrade.feedback import log_feedback, log_score, score_trace
from opengrade.retrieval import evaluate_retrieval
from opengrade.sweeps import sweep


def _param_names(fn: object, *, skip_self: bool = False) -> list[str]:
    params = list(inspect.signature(fn).parameters)
    if skip_self and params and params[0] == "self":
        params = params[1:]
    return params


def _signature_without_self(fn: object) -> inspect.Signature:
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    if params and params[0].name == "self":
        params = params[1:]
    return sig.replace(parameters=params)


def test_opengrade_delegates_keep_concrete_signatures() -> None:
    assert _param_names(Opengrade.log_score, skip_self=True) == _param_names(log_score)
    assert _param_names(Opengrade.log_feedback, skip_self=True) == _param_names(log_feedback)
    assert _param_names(Opengrade.score_trace, skip_self=True) == _param_names(score_trace)
    assert _signature_without_self(Opengrade.start_experiment) == inspect.signature(
        start_experiment
    )
    assert _signature_without_self(Opengrade.evaluate) == inspect.signature(evaluate)
    assert _signature_without_self(Opengrade.sweep) == inspect.signature(sweep)
    assert _signature_without_self(Opengrade.evaluate_retrieval) == inspect.signature(
        evaluate_retrieval
    )


def test_init_tracing_exposes_init_for_instance_kwargs() -> None:
    og_names = _param_names(Opengrade.init_tracing, skip_self=True)
    init_names = [n for n in _param_names(init_for_instance) if n != "og"]
    assert og_names == init_names
    assert "project_id" in og_names
    assert og_names != ["kwargs"]
