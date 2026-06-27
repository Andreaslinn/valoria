import { clsx } from "clsx";

export function Card({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={clsx(
        "rounded-lg border border-line bg-white/[0.055] p-5 shadow-soft backdrop-blur-xl",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function CardTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-base font-semibold text-ink">{children}</h3>;
}

export function CardDescription({ children }: { children: React.ReactNode }) {
  return <p className="mt-2 text-sm leading-6 text-muted">{children}</p>;
}
