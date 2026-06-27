"use client";

import Link from "next/link";
import { useState } from "react";

import { PublicHeader } from "@/components/layout/public-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusNote } from "@/components/ui/status-note";
import { register } from "@/lib/api/auth";

export default function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    setError(null);
    setLoading(true);
    try {
      await register(email, password);
      setMessage("Cuenta creada. Ya puedes iniciar sesion.");
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "No pudimos crear la cuenta. La beta puede estar cerrada.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-transparent">
      <PublicHeader />
      <section className="mx-auto grid max-w-5xl gap-8 px-5 py-12 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
        <div className="hidden lg:block">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-500">Beta cerrada</p>
          <h1 className="mt-3 text-4xl font-semibold leading-tight text-ink">
            Prepara tu acceso sin cambiar la autenticacion existente.
          </h1>
          <p className="mt-4 text-sm leading-6 text-muted">
            Registro sigue llamando al endpoint actual. Si la beta esta cerrada, la UI muestra el
            error de forma controlada.
          </p>
        </div>
        <div className="rounded-lg border border-line bg-white/[0.06] p-6 shadow-soft backdrop-blur-xl">
          <h1 className="text-2xl font-semibold text-ink">Solicitar acceso beta</h1>
          <p className="mt-2 text-sm leading-6 text-muted">
            Este formulario usa el endpoint actual de registro. Si la beta esta cerrada, Valoria
            mostrara una respuesta amable sin romper la pantalla.
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
              autoComplete="new-password"
              label="Password"
              minLength={8}
              name="password"
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
            {message ? <StatusNote tone="success">{message}</StatusNote> : null}
            {error ? <StatusNote tone="warning">{error}</StatusNote> : null}
            <Button disabled={loading} type="submit">
              {loading ? "Enviando..." : "Crear cuenta"}
            </Button>
          </form>
          <p className="mt-5 text-sm text-muted">
            Ya tienes cuenta?{" "}
            <Link className="font-semibold text-brand-500" href="/login">
              Inicia sesion
            </Link>
          </p>
        </div>
      </section>
    </main>
  );
}
