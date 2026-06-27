import { FileText } from "lucide-react";

import { PageHeading } from "@/components/layout/page-heading";
import { InternalBackLink, PlaceholderPanel } from "@/components/layout/placeholder-panel";

export default function ReportesPage() {
  return (
    <>
      <InternalBackLink />
      <PageHeading
        eyebrow="Modulo en preparacion"
        title="Reportes"
        description="Area preparada para descargas autenticadas cuando el contrato backend de reportes este listo."
      />
      <PlaceholderPanel
        description="No genera reportes todavia. La generacion debe quedar en backend antes de exponerla aqui."
        icon={FileText}
        nextSteps={[
          "Mover generador HTML a servicio backend.",
          "Crear endpoint autenticado de reporte.",
          "Renderizar preview y descarga segura.",
        ]}
        title="Reportes en espera de contrato backend"
      />
    </>
  );
}
