import { PageHeading } from "@/components/layout/page-heading";
import { InternalBackLink } from "@/components/layout/placeholder-panel";
import { PortfolioWorkspace } from "@/features/portfolio/PortfolioWorkspace";

export default function PortfolioPage() {
  return (
    <>
      <InternalBackLink />
      <PageHeading
        eyebrow="Watchlist"
        title="Portfolio / Watchlist"
        description="Primera capa de propiedades guardadas. Portfolio financiero avanzado queda fuera de esta fase."
      />
      <PortfolioWorkspace />
    </>
  );
}
