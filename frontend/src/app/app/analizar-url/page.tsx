import { PageHeading } from "@/components/layout/page-heading";
import { InternalBackLink } from "@/components/layout/placeholder-panel";
import { ListingUrlWorkspace } from "@/features/listing-url/ListingUrlWorkspace";

export default function AnalizarUrlPage() {
  return (
    <>
      <InternalBackLink />
      <PageHeading
        eyebrow="Analisis de publicacion"
        title="Analizar URL"
        description="Extrae datos disponibles desde una publicacion soportada y prepara una lectura inicial."
      />
      <ListingUrlWorkspace />
    </>
  );
}
