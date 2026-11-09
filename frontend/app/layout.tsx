import type { Metadata } from "next";
import { UiProviders } from "@/components/ui/UiProviders";
import { PREFERENCES_KEY } from "@/lib/storage";
import { fontVariables } from "./fonts";
import "./globals.css";

export const metadata: Metadata = {
  title: "MoneyAngle",
  description: "Import a bank statement. MoneyAngle sorts every transaction and builds your dashboards.",
};

// Runs before first paint so a saved font or colour mode never flashes the default one. It only
// reads the cached copy of the preferences (localStorage); the real values are fetched after
// sign-in. The font id is checked against a strict pattern (an id with no CSS rule just means
// "default"). A theme other than the three fixed modes, or none cached at all (a visitor, or after
// logging out), means the default, "Match device": the device's light or dark setting. When
// localStorage is blocked, the device still decides.
const APPLY_LOOK = `(function(){var d=document.documentElement,p={};try{p=JSON.parse(localStorage.getItem(${JSON.stringify(PREFERENCES_KEY)})||"{}")||{}}catch(e){}try{var f=p.font,t=p.theme;if(typeof f==="string"&&/^[a-z0-9-]{1,32}$/.test(f)&&f!=="geist")d.dataset.font=f;if(t!=="classic"&&t!=="light"&&t!=="dark")t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";if(t!=="classic")d.dataset.theme=t}catch(e){}})()`;

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
