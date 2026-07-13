import { PageHeading } from "@/components/layout/page-heading";
import { InternalBackLink } from "@/components/layout/placeholder-panel";
import { AlertsWorkspace } from "@/features/alerts/AlertsWorkspace";

export default function AlertsPage() {
  return (
    <>
      <InternalBackLink />
      <PageHeading
        eyebrow="Monitoreo"
        title="Alertas"
        description="Revisa alertas de propiedades guardadas y marca como leidas las que ya gestionaste."
      />
      <AlertsWorkspace />
    </>
  );
}
