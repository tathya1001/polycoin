// next/font self-hosts each Google font and exposes it as a CSS variable. `preload: false`
// means the browser only downloads a font once the page actually uses it, so a font nobody
// picked costs nothing. Settings > Appearance chooses one via html[data-font] (globals.css).
//
// next/font needs every loader call to be a top-level const with literal options, so this
// can't be generated from lib/fonts.ts: keep the two files in step.

import {
  Bitter,
  Crimson_Pro,
  Geist,
  Geist_Mono,
  Geologica,
  IBM_Plex_Mono,
  IBM_Plex_Sans,
  Instrument_Serif,
  Inter,
  Source_Serif_4,
  Space_Grotesk,
  Spectral,
  VT323,
  Xanh_Mono,
} from "next/font/google";

// The default font, loaded eagerly (it is on every first paint).
const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

const inter = Inter({ variable: "--font-inter", subsets: ["latin"], preload: false });
const spaceGrotesk = Space_Grotesk({ variable: "--font-space-grotesk", subsets: ["latin"], preload: false });
const plexSans = IBM_Plex_Sans({ variable: "--font-plex-sans", subsets: ["latin"], preload: false });
const geologica = Geologica({ variable: "--font-geologica", subsets: ["latin"], preload: false });
const sourceSerif = Source_Serif_4({ variable: "--font-source-serif", subsets: ["latin"], preload: false });
const instrumentSerif = Instrument_Serif({ variable: "--font-instrument-serif", weight: "400", subsets: ["latin"], preload: false });
const bitter = Bitter({ variable: "--font-bitter", subsets: ["latin"], preload: false });
const crimsonPro = Crimson_Pro({ variable: "--font-crimson-pro", subsets: ["latin"], preload: false });
// Spectral, IBM Plex Mono, Xanh Mono and VT323 are not variable fonts: list the weights the UI uses.
const spectral = Spectral({ variable: "--font-spectral", weight: ["400", "500", "600", "700"], subsets: ["latin"], preload: false });
const plexMono = IBM_Plex_Mono({ variable: "--font-plex-mono", weight: ["400", "500", "600", "700"], subsets: ["latin"], preload: false });
const xanhMono = Xanh_Mono({ variable: "--font-xanh-mono", weight: "400", subsets: ["latin"], preload: false });
const vt323 = VT323({ variable: "--font-vt323", weight: "400", subsets: ["latin"], preload: false });

// All the CSS variable class names, for <html className>.
export const fontVariables = [
  geistSans,
  geistMono,
  inter,
  spaceGrotesk,
  plexSans,
  geologica,
  sourceSerif,
  instrumentSerif,
  bitter,
  crimsonPro,
  spectral,
  plexMono,
  xanhMono,
  vt323,
]
  .map((font) => font.variable)
  .join(" ");
