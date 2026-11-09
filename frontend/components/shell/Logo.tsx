import { cn } from "@/lib/cn";

// The MoneyAngle mark. It is drawn in the text colour (currentColor), so it works in every colour
// mode, and its height follows the font size around it. The same shapes are the browser tab icon
// (app/icon.svg).
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 219 292" fill="currentColor" aria-hidden className={cn("aspect-[219/292] h-[1.2em] w-auto shrink-0", className)}>
      <path d="M118.479 142.153L189.19 212.863C203.175 198.878 212.699 181.06 216.557 161.662C220.416 142.264 218.436 122.157 210.867 103.884C203.298 85.6119 190.481 69.994 174.036 59.0059C157.591 48.0177 138.257 42.1528 118.479 42.1528V142.153Z" />
      <path d="M100.001 149.807L29.2903 79.0962C15.305 93.0814 5.78099 110.9 1.92248 130.298C-1.93603 149.696 0.0443153 169.803 7.61308 188.075C15.1818 206.348 27.9991 221.966 44.444 232.954C60.8889 243.942 80.2228 249.807 100.001 249.807V149.807Z" />
      <path d="M98.4788 120V0C66.6528 -1.92322e-05 36.1304 12.6428 13.626 35.1471L98.4788 120Z" />
      <path d="M120.001 171.96V291.96C151.827 291.96 182.349 279.317 204.854 256.813L120.001 171.96Z" />
    </svg>
  );
}

// The mark and the name: the sidebar, the phone header, the home page and the sign-in pages. The
// name is part of the logo, so it is always set in Geist, whatever font the user picked.
export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-brand text-lg font-semibold tracking-tight", className)}>
      <LogoMark />
      MoneyAngle
    </span>
  );
}
