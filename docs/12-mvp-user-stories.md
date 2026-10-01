# MVP User Stories

## Platform operator

As an operator, I can start the full stack with Docker Compose and use it on a trusted network without configuring an identity system.

## Developer

As a developer, I can instrument my Python AI application and send traces to the platform.

## Debugging

As a developer, I can inspect a trace and understand which LLM/tool/retrieval step caused latency or failure.

## Dataset

As a developer, I can convert a production trace into an evaluation example.

## Evaluation

As a developer, I can run a dataset against a new application/model version.

## Comparison

As a developer, I can compare two experiments and see quality, cost and latency deltas.

## CI

As a developer, I can define release thresholds in YAML and make CI fail on regressions.

## Extender

As a contributor, I can add a deterministic evaluator through the registry without modifying the API layer.

## Reviewer

As a reviewer, I can label an AI output and leave a comment.

## Portfolio demo

A new user should be able to clone the repository and, within approximately 10 minutes:

1. start the stack;
2. run the example AI application;
3. generate traces;
4. inspect them;
5. create a dataset;
6. run an evaluation;
7. compare experiments;
8. execute a release check.

No account signup or login step is required for this demo.
