import PageClient from "./page-client";

export function generateStaticParams() {
  return [{ metricsSetId: "_" }];
}

export default function Page() {
  return <PageClient />;
}
