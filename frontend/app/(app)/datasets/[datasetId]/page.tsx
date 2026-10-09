import PageClient from "./page-client";

export function generateStaticParams() {
  return [{ datasetId: "_" }];
}

export default function Page() {
  return <PageClient />;
}
