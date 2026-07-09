export function PageHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow?: string;
  title: string;
  description: string;
}) {
  return (
    <div className="mb-6 hidden lg:block">
      {eyebrow ? (
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-500">
          {eyebrow}
        </p>
      ) : null}
      <h1 className="max-w-4xl text-3xl font-semibold tracking-normal text-ink md:text-4xl">
        {title}
      </h1>
      <p className="mt-3 max-w-3xl text-sm leading-6 text-muted">{description}</p>
    </div>
  );
}
