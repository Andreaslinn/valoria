import { Radar } from "lucide-react";

import { PageHeading } from "@/components/layout/page-heading";
import { InternalBackLink, PlaceholderPanel } from "@/components/layout/placeholder-panel";

export default function RadarPage() {
  return (
    <>
      <InternalBackLink />
      <PageHeading
        eyebrow="Modulo en preparacion"
        title="Radar"
        description="Base visual para oportunidades inmobiliarias. No ejecuta consultas reales ni mapas en esta fase."
      />
      <PlaceholderPanel
        description="La siguiente fase podra consumir /api/v1/radar/opportunities con paginacion/filtros cuando el contrato este listo."
        icon={Radar}
        nextSteps={[
          "Disenar cards y tabla de oportunidades.",
          "Conectar filtros backend gradualmente.",
          "Agregar mapa solo cuando la calidad de coordenadas sea suficiente.",
        ]}
        title="Radar real se migrara despues"
      />
    </>
  );
}
