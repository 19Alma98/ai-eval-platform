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
  created_at: string;
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
