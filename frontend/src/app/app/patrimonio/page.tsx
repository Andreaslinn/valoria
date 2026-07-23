import { PageHeading } from "@/components/layout/page-heading";
import { InternalBackLink } from "@/components/layout/placeholder-panel";
import { PatrimonyWorkspace } from "@/features/patrimony/PatrimonyWorkspace";

export default function PatrimonyPage() {
  return (
    <>
      <InternalBackLink />
      <div className="mb-6 lg:hidden">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-brand-500">Mi hogar</p>
        <h1 className="text-3xl font-semibold tracking-normal text-ink">Mi patrimonio</h1>
        <p className="mt-3 text-sm leading-6 text-muted">
          Revisa tus propiedades guardadas, sus valoraciones y las senales que requieren atencion.
        </p>
      </div>
      <PageHeading
        eyebrow="Mi hogar"
        title="Mi patrimonio"
        description="Revisa tus propiedades guardadas, sus valoraciones y las senales que requieren atencion."
      />
      <PatrimonyWorkspace />
    </>
  );
}
