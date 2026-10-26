"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { PublicHeader } from "@/components/layout/public-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusNote } from "@/components/ui/status-note";
import { login } from "@/lib/api/auth";
import { setAccessToken } from "@/lib/auth/token";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result = await login(email, password);
      setAccessToken(result.access_token);
      router.push("/app");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No pudimos iniciar sesion.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-transparent">
      <PublicHeader />
      <section className="mx-auto grid max-w-5xl gap-8 px-5 py-12 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
        <div className="hidden lg:block">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-500">Acceso beta</p>
          <h1 className="mt-3 text-4xl font-semibold leading-tight text-ink">
            Tu cockpit inmobiliario empieza con una sesion segura.
          </h1>
          <p className="mt-4 text-sm leading-6 text-muted">
            Login mantiene el endpoint actual de FastAPI. La experiencia visual cambia; la
            autenticacion no.
          </p>
        </div>
        <div className="rounded-lg border border-line bg-white/[0.06] p-6 shadow-soft backdrop-blur-xl">
          <h1 className="text-2xl font-semibold text-ink">Entrar a Valoria</h1>
          <p className="mt-2 text-sm leading-6 text-muted">
            Usa las credenciales de la beta privada. El token se guarda localmente para esta
            primera version.
          </p>
          <form className="mt-6 grid gap-4" onSubmit={onSubmit}>
            <Input
              autoComplete="email"
              label="Email"
              name="email"
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
            <Input
              autoComplete="current-password"
              label="Password"
              name="password"
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
            {error ? <StatusNote tone="warning">{error}</StatusNote> : null}
            <Button disabled={loading} type="submit">
              {loading ? "Conectando..." : "Iniciar sesion"}
            </Button>
          </form>
          <p className="mt-5 text-sm text-muted">
            No tienes cuenta?{" "}
            <Link className="font-semibold text-brand-500" href="/register">
              Solicitar acceso beta
            </Link>
          </p>
        </div>
      </section>
    </main>
  );
}
