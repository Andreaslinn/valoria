import { PageHeading } from "@/components/layout/page-heading";
import { InternalBackLink } from "@/components/layout/placeholder-panel";
import { RadarWorkspace } from "@/features/radar/RadarWorkspace";

export default function RadarPage() {
  return (
    <>
      <InternalBackLink />
      <PageHeading
        eyebrow="Beta"
        title="Radar"
        description="Busca oportunidades bajo el valor estimado por Valoria cuando tu decidas ejecutar Radar."
      />
      <RadarWorkspace />
    </>
  );
}
