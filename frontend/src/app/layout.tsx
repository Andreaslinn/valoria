import type { Metadata, Viewport } from "next";
import { MobileViewportLock } from "@/components/layout/mobile-viewport-lock";
import "./globals.css";

const appName = "Valoria Beta";
const appDescription = "Plataforma de inteligencia inmobiliaria para Chile.";
const themeColor = "#09090b";

export const metadata: Metadata = {
  title: appName,
  description: appDescription,
  applicationName: appName,
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "Valoria",
    statusBarStyle: "black-translucent",
  },
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  themeColor,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es">
      <body>
        <MobileViewportLock />
        {children}
      </body>
    </html>
  );
}
