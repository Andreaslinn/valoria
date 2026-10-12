import { clsx } from "clsx";

type Tone = "info" | "warning" | "success";

const toneClass: Record<Tone, string> = {
  info: "border-brand-500/25 bg-brand-500/10 text-violet-100",
  warning: "border-amber-500/25 bg-amber-500/10 text-amber-200",
  success: "border-accent-500/25 bg-accent-500/10 text-emerald-100",
};

export function StatusNote({
  children,
  tone = "info",
}: {
  children: React.ReactNode;
  tone?: Tone;
}) {
  return (
    <div className={clsx("rounded-lg border px-4 py-3 text-sm leading-6", toneClass[tone])}>
      {children}
    </div>
  );
}
