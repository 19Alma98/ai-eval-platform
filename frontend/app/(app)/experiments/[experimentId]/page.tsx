import PageClient from "./page-client";

export function generateStaticParams() {
  return [{ experimentId: "_" }];
}

export default function Page() {
  return <PageClient />;
}
