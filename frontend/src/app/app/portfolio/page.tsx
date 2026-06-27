import { PageHeading } from "@/components/layout/page-heading";
import { InternalBackLink } from "@/components/layout/placeholder-panel";
import { PortfolioWorkspace } from "@/features/portfolio/PortfolioWorkspace";

export default function PortfolioPage() {
  return (
    <>
      <InternalBackLink />
      <PageHeading
        eyebrow="Watchlist conectada"
        title="Portfolio / Watchlist"
        description="Primera capa real de propiedades guardadas. Portfolio financiero avanzado queda fuera de esta fase."
      />
      <PortfolioWorkspace />
    </>
  );
}
