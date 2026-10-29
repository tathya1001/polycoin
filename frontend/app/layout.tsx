import type { Metadata } from "next";
import { UiProviders } from "@/components/ui/UiProviders";
import { fontVariables } from "./fonts";
import "./globals.css";

export const metadata: Metadata = {
  title: "Polycoin",
  description: "Secure Smart Personal Bank Statement Analyzer",
};

// Runs before first paint so a saved font or colour mode never flashes the default one. It only
// reads the cached copy of the preferences (localStorage); the real values are fetched after
// sign-in. The font id is checked against a strict pattern (an id with no CSS rule just means
// "default"); the theme must be one of the known modes, and "system" asks the device.
const APPLY_LOOK = `try{var d=document.documentElement,p=JSON.parse(localStorage.getItem("polycoin.prefs")||"{}"),f=p.font,t=p.theme;if(typeof f==="string"&&/^[a-z0-9-]{1,32}$/.test(f)&&f!=="geist")d.dataset.font=f;if(t==="system")t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";if(t==="light"||t==="dark")d.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${fontVariables} h-full antialiased`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: APPLY_LOOK }} />
      </head>
      <body className="flex min-h-full flex-col">
        <UiProviders>{children}</UiProviders>
      </body>
    </html>
  );
}
