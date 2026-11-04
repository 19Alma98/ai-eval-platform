# API reference

Generated from the docstrings of the `opengrade-ai` package ([`sdk/src/opengrade`](../../sdk/src/opengrade/)). For a guided tour with examples, read the [Python SDK guide](../sdk.md) first.

Everything documented here is importable from the top-level package, whatever module it is defined in:

```python
import opengrade

opengrade.init(instrument="auto")
result = opengrade.evaluate(dataset="rag_qa", task=answer, metrics=[...])
```

| Page | Contents |
|---|---|
| [Tracing](tracing.md) | `init`, `flush`, `@trace`, `span`, span attributes, users / sessions / tags |
| [Experiments](experiments.md) | `evaluate`, `start_experiment`, `Experiment`, `ExperimentResult`, `sweep`, `evaluate_retrieval` |
| [Metrics and judges](metrics.md) | `metric`, `LocalMetric`, `Sample`, `Score`, `LlmJudge` |
| [Production scores and feedback](feedback.md) | `score_trace`, `log_score`, `log_feedback` |
| [Control plane client](client.md) | `Client`, `AsyncClient`, `AppConfigClient` |
| [Configuration and errors](config.md) | tracking URI, API key, active project, exceptions |
