"use client";

import { ArrowRight, LockKeyhole, Mail, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/public-button";
import { StatusNote } from "@/components/ui/public-status-note";
import { summaryApi } from "@/lib/api/summary";
import "./login.css";
import { getAccessToken, setAccessToken } from "@/lib/auth/token";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!getAccessToken()) return;
    const controller = new AbortController();
    void summaryApi.user({ signal: controller.signal }).then(() => {
      if (!controller.signal.aborted) window.location.replace("/resumen");
    }).catch(() => { /* An invalid session leaves the existing login form available. */ });
    return () => controller.abort();
  }, []);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result = await summaryApi.login(email, password);
      setAccessToken(result.access_token);
      window.location.assign("/resumen");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No pudimos iniciar sesion.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="public-login"><main className="relative min-h-screen overflow-hidden bg-[#02040b] text-ink">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_28%,rgba(124,92,255,0.24),transparent_24rem),radial-gradient(circle_at_50%_94%,rgba(95,45,255,0.32),transparent_34rem),linear-gradient(180deg,#02040b_0%,#060916_52%,#02040b_100%)]" />
      <div className="pointer-events-none absolute inset-x-[-10%] bottom-[-34rem] h-[52rem] rounded-[50%] border border-violet-400/25 bg-[radial-gradient(circle_at_50%_0%,rgba(124,92,255,0.3),rgba(20,10,48,0.18)_32%,transparent_62%)] shadow-[0_-42px_160px_rgba(124,92,255,0.28)]" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-48 bg-[linear-gradient(180deg,transparent,rgba(2,4,11,0.78)),linear-gradient(90deg,transparent,rgba(124,92,255,0.14),transparent)]" />

      <section className="relative z-10 mx-auto flex min-h-screen w-full max-w-2xl flex-col items-center px-5 py-8 sm:py-9">
        <Link className="group flex flex-col items-center text-center" href="/">
          <span className="grid h-16 w-16 place-items-center rounded-[1.1rem] border border-violet-300/25 bg-white/[0.035] text-4xl font-black text-brand-500 shadow-[0_0_70px_rgba(124,92,255,0.38)] backdrop-blur-xl transition group-hover:border-violet-300/45">
            V
          </span>
          <span className="mt-5 text-4xl font-semibold uppercase leading-none tracking-[0.28em] text-white sm:text-5xl">
            Valoria
          </span>
        </Link>

        <div className="mt-7 text-center">
          <h1 className="mx-auto max-w-lg text-2xl font-semibold leading-tight text-white sm:text-3xl">
            Inteligencia inmobiliaria para decisiones con{" "}
            <span className="text-brand-500">ventaja.</span>
          </h1>
          <div className="mt-5 inline-flex items-center gap-2 rounded-lg border border-brand-500/30 bg-brand-500/10 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.16em] text-violet-200 shadow-glow">
            <LockKeyhole size={16} />
            Acceso beta privado
          </div>
          <p className="mt-3 text-sm text-slate-300">Acceso exclusivo para usuarios invitados</p>
        </div>

        <div className="mt-8 w-full max-w-xl rounded-lg border border-violet-400/25 bg-[#050812]/80 p-5 shadow-[0_28px_110px_rgba(0,0,0,0.62),0_0_70px_rgba(124,92,255,0.14)] backdrop-blur-2xl sm:p-7">
          <div>
            <h2 className="text-2xl font-semibold text-white">Iniciar sesion</h2>
            <p className="mt-2 text-sm leading-6 text-slate-300">
              Ingresa tus credenciales para acceder a Valoria.
            </p>
          </div>

          <form className="mt-6 grid gap-4" onSubmit={onSubmit}>
            <label className="grid gap-1.5 text-sm font-medium text-white" htmlFor="email">
              Email
              <span className="relative block">
                <Mail
                  className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500"
                  size={20}
                />
                <input
                  autoComplete="email"
                  className="min-h-12 w-full rounded-lg border border-slate-700/70 bg-black/25 px-11 text-sm text-white outline-none transition placeholder:text-slate-600 focus:border-brand-500/80 focus:ring-4 focus:ring-brand-100"
                  id="email"
                  name="email"
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="tucorreo@ejemplo.com"
                  required
                  type="email"
                  value={email}
                />
              </span>
            </label>

            <label className="grid gap-1.5 text-sm font-medium text-white" htmlFor="password">
              Contrasena
              <span className="relative block">
                <LockKeyhole
                  className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500"
                  size={19}
                />
                <input
                  autoComplete="current-password"
                  className="min-h-12 w-full rounded-lg border border-slate-700/70 bg-black/25 px-11 text-sm text-white outline-none transition placeholder:text-slate-600 focus:border-brand-500/80 focus:ring-4 focus:ring-brand-100"
                  id="password"
                  name="password"
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Ingresa tu contrasena"
                  required
                  type="password"
                  value={password}
                />
              </span>
            </label>

            <div className="rounded-lg border border-line bg-white/[0.045] px-3 py-2.5 text-xs leading-5 text-slate-300 sm:text-sm">
              La sesion se recuerda en este navegador para que puedas volver con facilidad.
            </div>

            {error ? <StatusNote tone="warning">{error}</StatusNote> : null}

            <Button
              className="min-h-12 w-full px-5 text-sm"
              disabled={loading}
              type="submit"
            >
              {loading ? "Conectando..." : "Entrar a Valoria"}
              <ArrowRight size={20} />
            </Button>
          </form>

          <div className="mt-5 flex flex-col gap-3 border-t border-line pt-4 text-sm text-slate-300 sm:flex-row sm:items-center sm:justify-between">
            <span>Beta privada para usuarios aprobados.</span>
            <Link className="font-semibold text-violet-300 hover:text-white" href="https://valoria-beta.netlify.app/register">
              Solicitar acceso
            </Link>
          </div>
        </div>

        <footer className="mt-auto flex w-full flex-col items-center gap-4 pb-4 pt-8 text-center text-xs text-slate-400">
          <div className="flex items-center gap-4">
            <span className="hidden h-px w-24 bg-line sm:block" />
            <ShieldCheck className="text-slate-300" size={26} />
            <span className="max-w-56 text-sm leading-6 text-slate-300">
              Tu informacion esta protegida. Infraestructura segura en Chile.
            </span>
            <span className="hidden h-px w-24 bg-line sm:block" />
          </div>
          <p>(c) 2026 Valoria. Todos los derechos reservados.</p>
        </footer>
      </section>
    </main></div>
  );
}

