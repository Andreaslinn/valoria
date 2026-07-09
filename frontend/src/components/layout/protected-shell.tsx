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
  Radar,
  Settings,
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

const mobileNavigation = navigation.filter((item) => item.showInMobileNav);

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

  function logout() {
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
            La primera version del frontend usa el token actual de la API para una beta cerrada.
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
          <p className="mt-1 text-sm text-ink">Datos reales / cobertura limitada</p>
        </div>
      </aside>
      <div className="min-w-0 lg:pl-72">
        <header className="relative z-20 border-b border-line bg-surface/72 px-5 py-2.5 backdrop-blur-xl">
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
        className="fixed inset-x-0 bottom-0 z-40 border-t border-white/10 bg-[#050914]/85 px-3 pb-[calc(0.55rem+env(safe-area-inset-bottom))] pt-2 shadow-[0_-18px_48px_rgba(0,0,0,0.45)] backdrop-blur-2xl lg:hidden"
      >
        <div className="mx-auto grid max-w-md grid-cols-5 gap-1">
          {mobileNavigation.map((item) => {
            const Icon = item.icon;
            const active = isActiveRoute(pathname, item.href);
            return (
              <Link
                aria-current={active ? "page" : undefined}
                className={clsx(
                  "flex min-h-14 min-w-0 flex-col items-center justify-center gap-1 rounded-lg px-1 text-[11px] font-semibold transition",
                  active
                    ? "text-ink"
                    : "text-muted hover:bg-white/[0.055] hover:text-ink active:bg-white/[0.08]",
                )}
                href={item.href}
                key={item.href}
              >
                <span
                  className={clsx(
                    "grid h-8 w-8 place-items-center rounded-lg border transition",
                    active
                      ? "border-brand-500/40 bg-brand-500/[0.18] text-brand-500 shadow-glow"
                      : "border-transparent bg-transparent text-slate-400",
                  )}
                >
                  <Icon size={18} aria-hidden />
                </span>
                <span className="w-full truncate text-center leading-none">
                  {item.mobileLabel ?? item.label}
                </span>
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
