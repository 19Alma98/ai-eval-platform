export type Project = {
  id: string;
  name: string;
  slug: string;
  created_at: string;
};

export type TraceSummary = {
  trace_id: string;
  name: string;
  status: string;
  start_time: string;
  end_time: string | null;
  span_count: number;
};

export type TraceListResponse = {
  items: TraceSummary[];
  next_cursor: string | null;
};

export type Span = {
  span_id: string;
  parent_span_id: string | null;
  name: string;
  kind: string;
  start_time: string;
  end_time: string | null;
  status: string;
  attributes: Record<string, unknown>;
  events: Record<string, unknown>[];
};

export type TraceDetail = {
  id: string;
  project_id: string;
  trace_id: string;
  name: string;
  status: string;
  start_time: string;
  end_time: string | null;
  input: unknown;
  output: unknown;
  metadata: Record<string, unknown>;
  environment: string | null;
  user_id: string | null;
  session_id: string | null;
  spans: Span[];
};

export type Dataset = {
  id: string;
  project_id: string;
  name: string;
  version: number;
  description: string | null;
  task_type: string | null;
  created_at: string;
};

export type TaskType = {
  id: string;
  label: string;
  field_hints: string[];
  recommended_evaluator_kinds: string[];
};

export type DatasetItem = {
  id: string;
  dataset_id: string;
  input: unknown;
  expected_output: unknown | null;
  actual_output: unknown | null;
  context: unknown | null;
  metadata: Record<string, unknown>;
  source_trace_id: string | null;
  source_span_id: string | null;
};

export type DatasetDetail = Dataset & {
  items: DatasetItem[];
};

export type ImportDatasetItemError = {
  row: number;
  message: string;
};

export type ImportDatasetItemsResult = {
  created: number;
  errors: ImportDatasetItemError[];
};

export type MetricsPackEntry = {
  kind: string;
  enabled: boolean;
  threshold: number | null;
  config: Record<string, unknown>;
  evaluator_id: string | null;
  removable: boolean;
};

export type MetricsPack = {
  id: string;
  project_id: string;
  entries: MetricsPackEntry[];
  updated_at: string;
};

export type ReplaceMetricsPackBody = {
  entries: MetricsPackEntry[];
};

export type MetricsSetEntry = {
  id: string;
  kind: string;
  enabled: boolean;
  threshold: number | null;
  config: Record<string, unknown>;
  evaluator_id: string | null;
  is_default: boolean;
  created_at: string;
};

export type MetricsSetSummary = {
  id: string;
  project_id: string;
  name: string;
  version: number;
  description: string | null;
  is_project_default: boolean;
  created_at: string;
  updated_at: string;
  entry_count: number;
  enabled_count: number;
};

export type MetricsSet = MetricsSetSummary & { entries: MetricsSetEntry[] };

export type MetricsSetEntryInput = {
  kind: string;
  enabled: boolean;
  threshold: number | null;
  config: Record<string, unknown>;
  evaluator_id: string | null;
};

export type CreateMetricsSetBody = {
  name: string;
  description?: string | null;
  entries: MetricsSetEntryInput[];
};

export type PatchMetricsSetBody = {
  name?: string;
  description?: string | null;
  entries?: MetricsSetEntryInput[];
};

export type Experiment = {
  id: string;
  project_id: string;
  name: string;
  dataset_id: string;
  model_config: Record<string, unknown>;
  app_config_id: string | null;
  version: string | null;
  baseline_experiment_id: string | null;
  metrics_set_id: string | null;
  status: string;
  created_at: string;
};

export type Evaluator = {
  id: string;
  project_id: string;
  name: string;
  type: string;
  config: Record<string, unknown>;
  version: number;
};

export type EvaluatorSummary = {
  evaluator_id: string;
  evaluator_name: string | null;
  run_id: string;
  status: string;
  n_items: number;
  n_scored: number;
  n_error: number;
  n_skipped: number;
  mean_score: number | null;
  pass_rate: number | null;
};

export type ExperimentSummary = {
  experiment_id: string;
  evaluators: EvaluatorSummary[];
};

export type MetricComparison = {
  evaluator_id: string;
  evaluator_name: string | null;
  metric: string;
  candidate: number | null;
  baseline: number | null;
  delta: number | null;
  status: string;
};

export type ExperimentCompareResponse = {
  experiment_id: string;
  baseline_experiment_id: string;
  metrics: MetricComparison[];
  regressions: MetricComparison[];
  improved: MetricComparison[];
  unchanged: MetricComparison[];
};

export type ItemSide = {
  actual_output: unknown | null;
  context: unknown | null;
  score: number | null;
  label: string | null;
  explanation: string | null;
  run_id: string | null;
};

export type ItemComparisonRow = {
  dataset_item_id: string;
  input: unknown;
  expected_output: unknown | null;
  baseline: ItemSide;
  candidate: ItemSide;
  delta: number | null;
  status: "regression" | "improved" | "unchanged" | "unavailable";
};

export type ItemComparisonResponse = {
  experiment_id: string;
  baseline_experiment_id: string;
  evaluator_id: string;
  items: ItemComparisonRow[];
};

export type EvaluationResult = {
  id: string;
  run_id: string;
  dataset_item_id: string;
  score: number | null;
  label: string | null;
  explanation: string | null;
  metadata: Record<string, unknown>;
  duration_ms: number | null;
};

export type EvaluationRun = {
  id: string;
  experiment_id: string;
  evaluator_id: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  metadata: Record<string, unknown>;
  results: EvaluationResult[];
};

export type ExperimentItemOutput = {
  id: string;
  experiment_id: string;
  dataset_item_id: string;
  actual_output: unknown | null;
  context: unknown | null;
  metadata: Record<string, unknown>;
  updated_at: string;
};

export type EvaluateResponse = {
  experiment: Experiment;
  runs: EvaluationRun[];
};

export type ReleaseCheckItemResponse = {
  metric: string;
  actual: number | null;
  threshold: number | null;
  status: string;
};

export type ReleaseCheckResponse = {
  status: string;
  experiment_id: string;
  baseline_experiment_id: string | null;
  checks: ReleaseCheckItemResponse[];
};

export type AppConfig = {
  id: string;
  project_id: string;
  name: string;
  version: number;
  description: string | null;
  prompt: Record<string, unknown>;
  model: Record<string, unknown>;
  retrieval: Record<string, unknown>;
  content_hash: string;
  created_at: string;
};

export type AppConfigSummary = {
  id: string;
  name: string;
  version: number;
};

export type AppConfigAlias = {
  name: string;
  app_config_id: string;
  updated_at: string;
  app_config: AppConfigSummary;
};
