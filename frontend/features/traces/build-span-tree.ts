import type { Span } from "@/lib/api/types";

export type SpanNode = {
  span: Span;
  children: SpanNode[];
  depth: number;
};

export type FlatSpanRow = {
  node: SpanNode;
  depth: number;
  hasChildren: boolean;
};

export function buildSpanTree(spans: Span[]): SpanNode[] {
  const byId = new Map<string, Span>();
  for (const span of spans) {
    byId.set(span.span_id, span);
  }

  const childMap = new Map<string | null, Span[]>();
  for (const span of spans) {
    const parent = span.parent_span_id;
    const key =
      parent != null && byId.has(parent) ? parent : null;
    const list = childMap.get(key) ?? [];
    list.push(span);
    childMap.set(key, list);
  }

  const sortByStart = (a: Span, b: Span) =>
    new Date(a.start_time).getTime() - new Date(b.start_time).getTime();

  function buildNodes(parentKey: string | null, depth: number): SpanNode[] {
    const siblings = (childMap.get(parentKey) ?? []).slice().sort(sortByStart);
    return siblings.map((span) => ({
      span,
      depth,
      children: buildNodes(span.span_id, depth + 1),
    }));
  }

  return buildNodes(null, 0);
}

export function flattenVisible(
  tree: SpanNode[],
  collapsed: Set<string>,
): FlatSpanRow[] {
  const rows: FlatSpanRow[] = [];

  function walk(nodes: SpanNode[]) {
    for (const node of nodes) {
      const hasChildren = node.children.length > 0;
      rows.push({ node, depth: node.depth, hasChildren });
      if (hasChildren && !collapsed.has(node.span.span_id)) {
        walk(node.children);
      }
    }
  }

  walk(tree);
  return rows;
}
