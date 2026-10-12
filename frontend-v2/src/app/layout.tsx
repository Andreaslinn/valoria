import type { Metadata, Viewport } from "next";
import "./tokens.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Resumen · Valoria 2.0",
  description: "Tu patrimonio en perspectiva. Inteligencia inmobiliaria para mejores decisiones.",
};
export const viewport: Viewport = { themeColor: "#10181c" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="es"><body>{children}</body></html>;
}
