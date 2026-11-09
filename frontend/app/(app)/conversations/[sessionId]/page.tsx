import PageClient from "./page-client";

export function generateStaticParams() {
  return [{ sessionId: "_" }];
}

export default function Page() {
  return <PageClient />;
}
