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
  Search,
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

const navigation: NavigationItem[] = [
  { label: "Inicio", href: "/app", icon: LayoutDashboard },
  { label: "Tasar", href: "/app/tasar", icon: Gauge },
  { label: "Analizar URL", href: "/app/analizar-url", icon: Link2 },
  { label: "Radar", href: "/app/radar", icon: Radar },
  { label: "Portfolio", href: "/app/portfolio", icon: WalletCards },
  { label: "Alertas", href: "/app/alerts", icon: Bell },
  { label: "Reportes", href: "/app/reportes", icon: FileText },
  { label: "Settings", href: "/app/settings", icon: Settings },
];

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
      <aside className="fixed inset-y-0 left-0 hidden w-72 border-r border-line bg-black/25 px-4 py-5 backdrop-blur-xl lg:block">
        <Link className="mb-8 flex items-center gap-3 px-2" href="/app">
          <span className="grid h-10 w-10 place-items-center rounded-lg border border-brand-500/40 bg-brand-500/15 text-sm font-black text-brand-500 shadow-glow">
            V
          </span>
          <span>
            <span className="block text-sm font-bold uppercase tracking-[0.22em] text-ink">
              Valoria
            </span>
            <span className="block text-xs text-muted">Cockpit beta</span>
          </span>
        </Link>
        <nav className="grid gap-1">
          {navigation.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href;
            return (
              <Link
                className={clsx(
                  "flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm font-semibold transition",
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
        <div className="absolute bottom-5 left-4 right-4 rounded-lg border border-line bg-white/[0.05] p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">API beta</p>
          <p className="mt-2 text-sm text-ink">FastAPI local/tunnel</p>
          <p className="mt-1 text-xs leading-5 text-muted">Datos reales solo en modulos conectados.</p>
        </div>
      </aside>
      <div className="lg:pl-72">
        <header className="sticky top-0 z-10 border-b border-line bg-surface/72 px-5 py-4 backdrop-blur-xl">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
            <div className="hidden min-h-11 w-full max-w-xl items-center gap-3 rounded-lg border border-line bg-white/[0.06] px-3 text-sm text-muted md:flex">
              <Search size={17} />
              <span>Buscar modulo, comuna o flujo...</span>
              <span className="ml-auto rounded border border-line px-2 py-1 text-xs">beta</span>
            </div>
            <div className="min-w-0">
              <p className="truncate text-xs font-semibold uppercase tracking-wide text-muted">
                Sesion activa
              </p>
              <p className="truncate text-sm text-ink">{user?.email ?? "Usuario beta"}</p>
            </div>
            <Button onClick={logout} type="button" variant="secondary">
              <LogOut size={16} />
              Salir
            </Button>
          </div>
        </header>
        <div className="mx-auto max-w-7xl px-5 py-6 lg:py-8">{children}</div>
      </div>
    </div>
  );
}
