import { ProtectedShell } from "@/components/layout/protected-shell";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <ProtectedShell>{children}</ProtectedShell>;
}
