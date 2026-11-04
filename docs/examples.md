# Examples

Runnable examples live in [`examples/`](../examples/) in the repository. Each one has a README with the commands to run it.

| Example | What it shows | Needs an LLM? |
|---|---|---|
| [`sdk_hello`](../examples/sdk_hello/README.md) | Instrument an app and see its first trace in the UI | Optional (Ollama or any OpenAI-compatible endpoint) |
| [`sdk_tour`](../examples/sdk_tour/README.md) | Dataset → metrics → experiment → gate → App Config prompt A/B, in five scripts | No (deterministic metrics by default) |
| [`ci_regression_gate`](../examples/ci_regression_gate/README.md) | PR-vs-main regression gate with `opengrade evaluate` | No |
| [`llm_regression_gate`](../examples/llm_regression_gate/README.md) | Same gate with a real LLM app and an LLM judge | Yes |
| [`non_inferiority_gate`](../examples/non_inferiority_gate/README.md) | Require a PR to be *shown* not worse than `main` | No |

GitHub Actions templates: [`release-gate.yml.example`](../.github/workflows/release-gate.yml.example), [`judge-sanity.yml.example`](../.github/workflows/judge-sanity.yml.example).
