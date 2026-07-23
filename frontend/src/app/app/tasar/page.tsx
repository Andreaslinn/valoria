import { ValuationWorkspace } from "@/features/valuation/ValuationWorkspace";

export default function TasarPage() {
  return (
    <div className="mx-auto max-w-[1180px]">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-ink sm:text-3xl">Tasar propiedad</h1>
        <p className="mt-2 text-sm text-muted">
          Obtén una estimación de mercado, su rango de confianza y la evidencia utilizada.
        </p>
      </header>
      <ValuationWorkspace />
    </div>
  );
}
