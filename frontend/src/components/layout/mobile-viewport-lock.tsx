"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

const LOCKED_VIEWPORT_DIRECTIVES = ["maximum-scale=1", "user-scalable=no"] as const;

function shouldLockZoom(): boolean {
  return (
    window.matchMedia("(pointer: coarse)").matches ||
    (window.matchMedia("(display-mode: standalone)").matches &&
      window.matchMedia("(hover: none)").matches)
  );
}

function lockViewportZoom(): void {
  const meta = document.querySelector('meta[name="viewport"]');
  if (!meta) {
    return;
  }

  const content = meta.getAttribute("content") ?? "";
  const directives = content
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .filter(
      (part) =>
        !part.startsWith("maximum-scale") && !part.startsWith("user-scalable"),
    );

  meta.setAttribute("content", [...directives, ...LOCKED_VIEWPORT_DIRECTIVES].join(", "));
}

export function MobileViewportLock() {
  const pathname = usePathname();

  useEffect(() => {
    if (!shouldLockZoom()) {
      return;
    }

    lockViewportZoom();

    const frameId = requestAnimationFrame(() => {
      lockViewportZoom();
    });

    return () => {
      cancelAnimationFrame(frameId);
    };
  }, [pathname]);

  return null;
}
