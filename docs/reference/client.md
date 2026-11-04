# Control plane client

HTTP client for projects, datasets, experiments, metrics, alerts and live runs. `Client` groups its methods by resource (`client.datasets`, `client.experiments`, ...); each resource is documented below.

::: opengrade.client.Client

::: opengrade.client._ProjectsResource
    options:
      heading: "client.projects"
      toc_label: "client.projects"

::: opengrade.client._DatasetsResource
    options:
      heading: "client.datasets"
      toc_label: "client.datasets"

::: opengrade.client._ExperimentsResource
    options:
      heading: "client.experiments"
      toc_label: "client.experiments"

::: opengrade.client._MetricsPacksResource
    options:
      heading: "client.metrics_packs"
      toc_label: "client.metrics_packs"

::: opengrade.client._MetricsSetsResource
    options:
      heading: "client.metrics_sets"
      toc_label: "client.metrics_sets"

::: opengrade.client._EvaluatorsResource
    options:
      heading: "client.evaluators"
      toc_label: "client.evaluators"

::: opengrade.client._AlertsResource
    options:
      heading: "client.alerts"
      toc_label: "client.alerts"

::: opengrade.client._LiveRunsResource
    options:
      heading: "client.live_runs"
      toc_label: "client.live_runs"

::: opengrade.client._TraceScoresResource
    options:
      heading: "client.trace_scores"
      toc_label: "client.trace_scores"

::: opengrade.async_client.AsyncClient

::: opengrade.registry.AppConfigClient
