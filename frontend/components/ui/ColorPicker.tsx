"use client";

import { useState } from "react";
import { HexColorPicker } from "react-colorful";
import { RotateCcw } from "lucide-react";
import { cn } from "@/lib/cn";
import { CATEGORY_COLORS, isHexColor, normalizeHex } from "@/lib/colors";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Popover } from "@/components/ui/Popover";

// A round swatch that opens a colour wheel: 12 quick swatches, a free picker, a hex box.
// `onReset` (optional) shows a "back to default" button, used by chart overrides.
export function ColorPicker({
  value,
  onChange,
  label,
  onReset,
  resetLabel = "Reset",
  size = 22,
}: {
  value: string;
  onChange: (hex: string) => void;
  label: string; // for screen readers: "Colour for Food"
  onReset?: () => void;
  resetLabel?: string;
  size?: number;
}) {
  return (
    <Popover
      trigger={(p) => (
        <button
          type="button"
          aria-label={label}
          title={label}
          onClick={p.onClick}
          aria-expanded={p["aria-expanded"]}
          aria-haspopup="dialog"
          style={{ backgroundColor: value, width: size, height: size }}
          className="shrink-0 rounded-full border-[1.5px] border-ink transition-transform duration-150 hover:scale-110"
        />
      )}
      className="w-64"
    >
      <Picker value={value} onChange={onChange} onReset={onReset} resetLabel={resetLabel} />
    </Popover>
  );
}

function Picker({
  value,
  onChange,
  onReset,
  resetLabel,
}: {
  value: string;
  onChange: (hex: string) => void;
  onReset?: () => void;
  resetLabel: string;
}) {
  // The text box keeps what the user is typing; it only commits once it is a full hex colour.
  const [draft, setDraft] = useState(value.toUpperCase());

  function commit(hex: string) {
    const clean = normalizeHex(hex);
    setDraft(clean);
    if (isHexColor(clean)) onChange(clean);
  }

  return (
    <div className="space-y-3 [&_.react-colorful]:w-full [&_.react-colorful__saturation]:rounded-sm [&_.react-colorful__hue]:mt-3 [&_.react-colorful__hue]:rounded-full">
      <HexColorPicker color={value} onChange={commit} />
      <div className="grid grid-cols-6 gap-2">
        {CATEGORY_COLORS.map((hex) => (
          <button
            key={hex}
            type="button"
            aria-label={hex}
            onClick={() => commit(hex)}
            style={{ backgroundColor: hex }}
            className={cn(
              "size-7 rounded-full border-[1.5px] border-ink transition-transform hover:scale-110",
              hex.toLowerCase() === value.toLowerCase() && "outline-2 outline-offset-2 outline-ink",
            )}
          />
        ))}
      </div>
      <Input dense aria-label="Hex colour" value={draft} maxLength={7} onChange={(e) => commit(e.target.value)} className="font-mono" />
      {onReset && (
        <Button size="sm" variant="ghost" icon={<RotateCcw size={14} />} onClick={onReset}>
          {resetLabel}
        </Button>
      )}
    </div>
  );
}
