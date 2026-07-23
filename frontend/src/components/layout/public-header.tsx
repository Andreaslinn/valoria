import Link from "next/link";
import { ButtonLink } from "@/components/ui/button";

export function PublicHeader() {
  return (
    <header className="mx-auto flex w-full max-w-7xl items-center justify-between gap-3 px-4 py-5 sm:px-5">
      <Link className="flex min-w-0 items-center gap-3" href="/">
        <span className="grid h-9 w-9 place-items-center rounded-lg border border-brand-500/35 bg-brand-500/15 text-sm font-black text-brand-500 shadow-glow">
          V
        </span>
        <span className="min-w-0">
          <span className="block text-sm font-bold uppercase tracking-[0.22em] text-ink">
            Valoria
          </span>
          <span className="block truncate text-xs text-muted">Inteligencia inmobiliaria Chile</span>
        </span>
      </Link>
      <nav className="flex shrink-0 items-center gap-2">
        <ButtonLink className="min-h-10 px-3" href="/login" variant="ghost">
          Entrar
        </ButtonLink>
        <ButtonLink className="min-h-10 px-3" href="/register" variant="secondary">
          Beta
        </ButtonLink>
      </nav>
    </header>
  );
}
