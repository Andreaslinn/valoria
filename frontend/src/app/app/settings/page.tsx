import { Settings } from "lucide-react";

import { PageHeading } from "@/components/layout/page-heading";
import { InternalBackLink, PlaceholderPanel } from "@/components/layout/placeholder-panel";

export default function SettingsPage() {
  return (
    <>
      <InternalBackLink />
      <PageHeading
        eyebrow="Configuracion"
        title="Settings"
        description="Preferencias y datos de cuenta para la beta privada."
      />
      <PlaceholderPanel
        description="En el futuro aqui viviran preferencias de cuenta, notificaciones y entorno de trabajo."
        icon={Settings}
        nextSteps={[
          "Mostrar preferencias de notificacion.",
          "Agregar perfil de usuario y preferencias simples.",
          "Ordenar opciones de cuenta para la beta.",
        ]}
        title="Settings inicial"
      />
    </>
  );
}
