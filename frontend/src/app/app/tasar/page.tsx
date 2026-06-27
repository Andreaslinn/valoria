import { InternalBackLink } from "@/components/layout/placeholder-panel";
import { PageHeading } from "@/components/layout/page-heading";
import { ValuationWorkspace } from "@/features/valuation/ValuationWorkspace";

export default function TasarPage() {
  return (
    <>
      <InternalBackLink />
      <PageHeading
        eyebrow="Tasacion conectada"
        title="Tasar propiedad"
        description="Ejecuta una valoracion real contra FastAPI y revisa estimacion, rango, confianza, warnings y comparables cuando esten disponibles."
      />
      <ValuationWorkspace />
    </>
  );
}
