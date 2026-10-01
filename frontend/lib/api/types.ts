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
