import { PageHeading } from "@/components/layout/page-heading";
import { DashboardWorkspace } from "@/features/dashboard/DashboardWorkspace";

export default function DashboardPage() {
  return (
    <>
      <PageHeading
        eyebrow="Cockpit"
        title="Centro de inteligencia Valoria"
        description="Dashboard beta con estado de modulos y datos reales disponibles, sin metricas simuladas."
      />
      <DashboardWorkspace />
    </>
  );
}
