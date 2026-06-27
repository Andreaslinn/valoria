import { Bell } from "lucide-react";

import { PageHeading } from "@/components/layout/page-heading";
import { InternalBackLink, PlaceholderPanel } from "@/components/layout/placeholder-panel";

export default function AlertsPage() {
  return (
    <>
      <InternalBackLink />
      <PageHeading
        eyebrow="Modulo en preparacion"
        title="Alertas"
        description="Bandeja preparada para alertas reales. Por ahora no consulta ni inventa eventos."
      />
      <PlaceholderPanel
        description="Por ahora no consulta /api/v1/alerts. La pantalla evita mostrar datos simulados como si fueran reales."
        icon={Bell}
        nextSteps={[
          "Conectar inbox real de alertas no leidas.",
          "Agregar marcar como leida y filtros basicos.",
          "Disenar CRUD de reglas en una fase posterior.",
        ]}
        title="Alertas reales vendran despues"
      />
    </>
  );
}
