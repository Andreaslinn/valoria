import Link from "next/link";
import { clsx } from "clsx";

type ButtonVariant = "primary" | "secondary" | "ghost";

const variants: Record<ButtonVariant, string> = {
  primary:
    "border border-brand-500/40 bg-brand-600 text-white shadow-glow hover:bg-brand-500 hover:border-brand-500",
  secondary:
    "border border-line bg-white/[0.06] text-ink hover:border-brand-500/45 hover:bg-brand-500/10",
  ghost: "text-muted hover:bg-white/[0.06] hover:text-ink",
};

const baseClass =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-55";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
};

export function Button({ className, variant = "primary", ...props }: ButtonProps) {
  return <button className={clsx(baseClass, variants[variant], className)} {...props} />;
}

type ButtonLinkProps = {
  href: string;
  children: React.ReactNode;
  variant?: ButtonVariant;
  className?: string;
};

export function ButtonLink({ href, children, variant = "primary", className }: ButtonLinkProps) {
  return (
    <Link className={clsx(baseClass, variants[variant], className)} href={href}>
      {children}
    </Link>
  );
}
