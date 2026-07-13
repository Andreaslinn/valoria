"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Bell,
  FileText,
  Gauge,
  LayoutDashboard,
  Link2,
  LogOut,
  MoreHorizontal,
  Radar,
  Settings,
  X,
  WalletCards,
} from "lucide-react";
import { clsx } from "clsx";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusNote } from "@/components/ui/status-note";
import { getAccessToken, clearAccessToken } from "@/lib/auth/token";
import { me, type User } from "@/lib/api/auth";
import type { NavigationItem } from "@/types/navigation";

type ProtectedNavigationItem = NavigationItem & {
  mobileLabel?: string;
  showInMobileNav?: boolean;
};

const navigation: ProtectedNavigationItem[] = [
  {
    label: "Inicio",
    href: "/app",
    icon: LayoutDashboard,
    mobileLabel: "Inicio",
    showInMobileNav: true,
  },
  {
    label: "Tasar propiedad",
    href: "/app/tasar",
    icon: Gauge,
    mobileLabel: "Tasar",
    showInMobileNav: true,
  },
  { label: "Analizar publicación", href: "/app/analizar-url", icon: Link2 },
  {
    label: "Buscar oportunidades",
    href: "/app/radar",
    icon: Radar,
    mobileLabel: "Radar",
    showInMobileNav: true,
  },
  {
    label: "Watchlist",
    href: "/app/portfolio",
    icon: WalletCards,
    mobileLabel: "Portfolio",
    showInMobileNav: true,
  },
  {
    label: "Alertas",
    href: "/app/alerts",
    icon: Bell,
    mobileLabel: "Alertas",
    showInMobileNav: true,
  },
  { label: "Reportes", href: "/app/reportes", icon: FileText },
  { label: "Settings", href: "/app/settings", icon: Settings },
];

const mobileNavigation = ["/app", "/app/radar", "/app/tasar", "/app/portfolio", "/app/alerts"]
  .map((href) => navigation.find((item) => item.href === href))
  .filter((item): item is ProtectedNavigationItem => Boolean(item));
const secondaryMobileNavigation = navigation.filter((item) => !item.showInMobileNav);

function isActiveRoute(pathname: string, href: string) {
  if (href === "/app") {
    return pathname === href;
  }

  return pathname === href || pathname.startsWith(`${href}/`);
}

export function ProtectedShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [status, setStatus] = useState<"checking" | "ready" | "missing">("checking");
  const [user, setUser] = useState<User | null>(null);
  const [moreOpen, setMoreOpen] = useState(false);
  const activeNavigationItem =
    navigation.find((item) => isActiveRoute(pathname, item.href)) ?? navigation[0];
  const mobileTitle = activeNavigationItem.mobileLabel ?? activeNavigationItem.label;

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      setStatus("missing");
      return;
    }

    me(token)
      .then((currentUser) => {
        setUser(currentUser);
        setStatus("ready");
      })
      .catch(() => {
        clearAccessToken();
        setStatus("missing");
      });
  }, []);

  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);

  function logout() {
    setMoreOpen(false);
    clearAccessToken();
    router.push("/login");
  }

  if (status === "checking") {
    return (
      <main className="grid min-h-screen place-items-center px-5">
        <StatusNote>Validando sesion con Valoria...</StatusNote>
      </main>
    );
  }

  if (status === "missing") {
    return (
      <main className="grid min-h-screen place-items-center px-5">
        <div className="max-w-md rounded-lg border border-line bg-white/[0.06] p-6 text-center shadow-soft backdrop-blur-xl">
          <h1 className="text-xl font-semibold text-ink">Necesitas iniciar sesion</h1>
          <p className="mt-3 text-sm leading-6 text-muted">
            Inicia sesion para acceder a tu espacio privado de Valoria.
          </p>
          <Link
            className="mt-5 inline-flex min-h-11 items-center justify-center rounded-lg bg-brand-600 px-4 text-sm font-semibold text-white"
            href="/login"
          >
            Ir a login
          </Link>
        </div>
      </main>
    );
  }

  return (
    <div className="min-h-screen bg-transparent">
      <aside className="fixed inset-y-0 left-0 hidden w-72 flex-col border-r border-line bg-[#030712]/72 px-4 py-4 backdrop-blur-xl lg:flex">
        <Link className="mb-5 flex items-center gap-3 px-2" href="/app">
          <span className="grid h-11 w-11 place-items-center rounded-lg border border-brand-500/40 bg-gradient-to-br from-brand-500/30 to-brand-900/50 text-base font-black text-brand-500 shadow-glow">
            V
          </span>
          <span>
            <span className="block text-base font-bold uppercase tracking-[0.24em] text-ink">
              Valoria
            </span>
            <span className="block text-xs text-muted">Inteligencia inmobiliaria</span>
          </span>
        </Link>
        <nav className="grid flex-1 content-start gap-1 overflow-y-auto pr-1">
          {navigation.map((item) => {
            const Icon = item.icon;
            const active = isActiveRoute(pathname, item.href);
            return (
              <Link
                className={clsx(
                  "flex min-h-10 items-center gap-3 rounded-lg px-3 text-sm font-semibold transition",
                  active
                    ? "border border-brand-500/35 bg-brand-500/15 text-ink shadow-glow"
                    : "text-muted hover:bg-white/[0.06] hover:text-ink",
                )}
                href={item.href}
                key={item.href}
              >
                <Icon size={18} />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-4 shrink-0 rounded-lg border border-line bg-white/[0.045] p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Beta privada</p>
          <p className="mt-1 text-sm text-ink">Cobertura limitada</p>
        </div>
      </aside>
      <div className="min-w-0 lg:pl-72">
        <header className="sticky top-0 z-30 border-b border-white/10 bg-[#050914]/85 px-4 py-2.5 backdrop-blur-2xl lg:hidden">
          <div className="mx-auto flex min-h-12 max-w-md items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-brand-500">
                Valoria
              </p>
              <h1 className="truncate text-lg font-semibold text-ink">{mobileTitle}</h1>
            </div>
            {pathname === "/app" ? (
              <button
                aria-expanded={moreOpen}
                aria-label="Abrir menu secundario"
                className="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-line bg-white/[0.06] text-ink transition active:bg-white/[0.1]"
                onClick={() => setMoreOpen((current) => !current)}
                type="button"
              >
                <MoreHorizontal className="h-5 w-5" aria-hidden />
              </button>
            ) : null}
          </div>
        </header>
        <header className="relative z-20 hidden border-b border-line bg-surface/72 px-5 py-2.5 backdrop-blur-xl lg:block">
          <div className="mx-auto flex w-full max-w-[1600px] items-center justify-end gap-3">
            <div className="min-w-0 text-right">
              <p className="truncate text-xs font-semibold uppercase tracking-wide text-muted">
                Beta privada
              </p>
              <p className="truncate text-sm text-ink">{user?.email ?? "Usuario beta"}</p>
            </div>
            <Button className="min-h-9 px-3" onClick={logout} type="button" variant="secondary">
              <LogOut size={16} />
              Salir
            </Button>
          </div>
        </header>
        <div className="mx-auto w-full max-w-[1600px] px-5 pb-[calc(6rem+env(safe-area-inset-bottom))] pt-6 lg:px-6 lg:pb-6">
          {children}
        </div>
      </div>
      <nav
        aria-label="Navegacion principal movil"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-40 px-3 pb-[calc(0.55rem+env(safe-area-inset-bottom))] pt-2 lg:hidden"
      >
        <div className="pointer-events-auto mx-auto grid max-w-md grid-cols-5 gap-1 rounded-lg border border-white/10 bg-[#050914]/90 p-1.5 shadow-[0_-18px_56px_rgba(0,0,0,0.5)] backdrop-blur-2xl">
          {mobileNavigation.map((item) => {
            const Icon = item.icon;
            const active = isActiveRoute(pathname, item.href);
            const primary = item.href === "/app/tasar";
            return (
              <Link
                aria-current={active ? "page" : undefined}
                className={clsx(
                  "relative flex min-h-14 min-w-0 flex-col items-center justify-center gap-1 rounded-lg px-1 text-[11px] font-semibold transition",
                  primary && "-mt-3 min-h-[4.25rem]",
                  active
                    ? "text-ink"
                    : "text-muted hover:bg-white/[0.055] hover:text-ink active:bg-white/[0.08]",
                )}
                href={item.href}
                key={item.href}
              >
                <span
                  className={clsx(
                    "grid place-items-center rounded-lg border transition",
                    primary
                      ? "h-11 w-11 border-brand-500/45 bg-brand-600 text-white shadow-[0_0_28px_rgba(124,92,255,0.28)]"
                      : "h-8 w-8",
                    active && !primary
                      ? "border-brand-500/40 bg-brand-500/[0.18] text-brand-500 shadow-glow"
                      : !primary && "border-transparent bg-transparent text-slate-400",
                  )}
                >
                  <Icon size={primary ? 20 : 18} aria-hidden />
                </span>
                <span className="w-full truncate text-center leading-none">
                  {item.mobileLabel ?? item.label}
                </span>
              </Link>
            );
          })}
        </div>
      </nav>
      {moreOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            aria-label="Cerrar menu secundario"
            className="absolute inset-0 h-full w-full bg-black/55"
            onClick={() => setMoreOpen(false)}
            type="button"
          />
          <div className="absolute inset-x-3 bottom-3 mx-auto max-w-md rounded-lg border border-line bg-[#050914]/95 p-4 shadow-[0_-24px_80px_rgba(0,0,0,0.55)] backdrop-blur-2xl">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted">
                  Menu
                </p>
                <p className="mt-1 truncate text-sm text-ink">{user?.email ?? "Usuario beta"}</p>
              </div>
              <button
                aria-label="Cerrar menu"
                className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-white/[0.06] text-muted"
                onClick={() => setMoreOpen(false)}
                type="button"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>
            <div className="mt-4 grid gap-2">
              {secondaryMobileNavigation.map((item) => {
                const Icon = item.icon;
                return (
                  <Link
                    className="flex min-h-12 items-center gap-3 rounded-lg border border-line bg-white/[0.045] px-3 text-sm font-semibold text-ink"
                    href={item.href}
                    key={item.href}
                  >
                    <Icon className="h-4 w-4 text-brand-500" aria-hidden />
                    {item.mobileLabel ?? item.label}
                  </Link>
                );
              })}
              <button
                className="flex min-h-12 items-center gap-3 rounded-lg border border-line bg-white/[0.045] px-3 text-left text-sm font-semibold text-ink"
                onClick={logout}
                type="button"
              >
                <LogOut className="h-4 w-4 text-brand-500" aria-hidden />
                Cerrar sesion
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
