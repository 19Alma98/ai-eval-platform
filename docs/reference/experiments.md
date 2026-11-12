# Experiments

Run an app over a test set, score it, compare it with a baseline.

Call these as methods of your `Opengrade` instance: `og.evaluate`, `og.start_experiment`,
`og.sweep`, `og.evaluate_retrieval`. They take exactly the arguments documented below (type
checkers see the same signatures), run with `og` activated and use `og.client` unless you pass
`client=`. The module-level functions use the instance activated with `og.activate()`.

::: opengrade.experiment.evaluate

::: opengrade.experiment.start_experiment

::: opengrade.experiment.Experiment

::: opengrade.experiment.ExperimentResult

::: opengrade.experiment.ItemRun

::: opengrade.experiment.log_params

::: opengrade.experiment.log_metrics

::: opengrade.experiment.DatasetColumnError

::: opengrade.sweeps.sweep

::: opengrade.sweeps.SweepResult

::: opengrade.sweeps.SweepRun

::: opengrade.retrieval.evaluate_retrieval

::: opengrade._eval_run.set_retrieval_documents

::: opengrade._eval_run.set_search_query

## Chat test cases

Helpers for `rag_chat` datasets, where `item.input` is `{"history": [...], "question": "..."}`.
Recipe: [Evaluate a chat assistant](../chat-assistants.md).

::: opengrade.chat.chat_input

::: opengrade.chat.RagChatInput

::: opengrade.chat.ChatTurn

::: opengrade._eval_run.bind_evaluation
