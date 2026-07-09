import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Valoria Beta",
    short_name: "Valoria",
    description: "Plataforma de inteligencia inmobiliaria para Chile.",
    start_url: "/app",
    display: "standalone",
    orientation: "portrait",
    theme_color: "#09090b",
    background_color: "#09090b",
    icons: [
      {
        src: "/icons/icon-192.png",
        sizes: "192x192",
        type: "image/png",
      },
      {
        src: "/icons/icon-512.png",
        sizes: "512x512",
        type: "image/png",
      },
    ],
  };
}
