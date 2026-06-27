import Link from "next/link";
import { ButtonLink } from "@/components/ui/button";

export function PublicHeader() {
  return (
    <header className="mx-auto flex w-full max-w-7xl items-center justify-between px-5 py-5">
      <Link className="flex items-center gap-3" href="/">
        <span className="grid h-9 w-9 place-items-center rounded-lg border border-brand-500/35 bg-brand-500/15 text-sm font-black text-brand-500 shadow-glow">
          V
        </span>
        <span>
          <span className="block text-sm font-bold uppercase tracking-[0.22em] text-ink">
            Valoria
          </span>
          <span className="block text-xs text-muted">Inteligencia inmobiliaria Chile</span>
        </span>
      </Link>
      <nav className="flex items-center gap-2">
        <ButtonLink href="/login" variant="ghost">
          Login
        </ButtonLink>
        <ButtonLink href="/register" variant="secondary">
          Beta
        </ButtonLink>
      </nav>
    </header>
  );
}
