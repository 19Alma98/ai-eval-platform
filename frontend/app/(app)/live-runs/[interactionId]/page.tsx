import PageClient from "./page-client";

export function generateStaticParams() {
  return [{ interactionId: "_" }];
}

export default function Page() {
  return <PageClient />;
}
