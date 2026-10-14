import { AppShell } from "@/components/shell/AppShell";
import { SessionProvider } from "@/components/shell/Session";

// Everything behind sign-in: the sidebar shell plus who the user is and how they like the app.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
