import type { Metadata } from "next";
import { UiProviders } from "@/components/ui/UiProviders";
import { fontVariables } from "./fonts";
import "./globals.css";

export const metadata: Metadata = {
  title: "Polycoin",
  description: "Secure Smart Personal Bank Statement Analyzer",
};

// Runs before first paint so a saved font never flashes the default one. It only reads the
// cached copy of the preferences (localStorage); the real value is fetched after sign-in.
// The id is checked against a strict pattern, and an id with no CSS rule just means "default".
const APPLY_FONT = `try{var f=JSON.parse(localStorage.getItem("polycoin.prefs")||"{}").font;if(typeof f==="string"&&/^[a-z0-9-]{1,32}$/.test(f)&&f!=="geist")document.documentElement.dataset.font=f}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${fontVariables} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: APPLY_FONT }} />
      </head>
      <body className="flex min-h-full flex-col">
        <UiProviders>{children}</UiProviders>
      </body>
    </html>
  );
}
