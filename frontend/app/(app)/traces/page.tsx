import { EmptyState } from "@/components/empty-state";

export default function TracesPage() {
  return (
    <EmptyState
      title="Traces"
      description="No traces yet. Run the OTLP example against this project."
    />
  );
}
