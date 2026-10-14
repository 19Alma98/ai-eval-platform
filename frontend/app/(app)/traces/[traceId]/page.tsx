import PageClient from "./page-client";

export function generateStaticParams() {
  return [{ traceId: "_" }];
}

export default function Page() {
  return <PageClient />;
}
