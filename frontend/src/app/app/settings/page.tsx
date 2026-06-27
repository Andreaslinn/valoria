import { Settings } from "lucide-react";

import { PageHeading } from "@/components/layout/page-heading";
import { InternalBackLink, PlaceholderPanel } from "@/components/layout/placeholder-panel";
import { API_BASE_URL } from "@/lib/config";

export default function SettingsPage() {
  return (
    <>
      <InternalBackLink />
      <PageHeading
        eyebrow="Configuracion"
        title="Settings"
        description="Configuracion tecnica visible para la beta del frontend."
      />
      <PlaceholderPanel
        description={`API configurada: ${API_BASE_URL}. En el futuro aqui viviran preferencias de cuenta y entorno.`}
        icon={Settings}
        nextSteps={[
          "Mostrar estado de health check de API.",
          "Agregar perfil de usuario y preferencias simples.",
          "Documentar URL de API para entornos tunnel.",
        ]}
        title="Settings inicial"
      />
    </>
  );
}
