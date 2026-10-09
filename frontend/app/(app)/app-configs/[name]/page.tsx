import PageClient from "./page-client";

export function generateStaticParams() {
  return [{ name: "_" }];
}

export default function Page() {
  return <PageClient />;
}
