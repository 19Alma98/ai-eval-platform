export function PageIntro({
  title,
  glossary,
}: {
  title: string;
  glossary: string;
}) {
  return (
    <div className="mb-4">
      <h1 className="text-lg font-semibold tracking-tight text-foreground">{title}</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{glossary}</p>
    </div>
  );
}
