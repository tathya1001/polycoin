"use client";

import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";
import { IconButton } from "@/components/ui/Button";

// Built on the native <dialog>: the browser traps focus, makes the page behind inert, and
// closes on Esc. We only add the look, the backdrop click and the open/close wiring.
export function Dialog({
  open,
  onClose,
  title,
  size = "sm",
  footer,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  size?: "sm" | "md" | "lg";
  footer?: ReactNode;
  children?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose(); // a click on the backdrop
      }}
      className={cn(
        "m-auto w-[min(92vw,var(--dialog-w))] rounded-lg border-[1.5px] border-ink bg-surface p-0 text-ink shadow-hard-lg",
        "open:animate-[pop-in_160ms_ease-out]",
      )}
      style={{ "--dialog-w": { sm: "26rem", md: "38rem", lg: "52rem" }[size] } as CSSProperties}
    >
      {open && (
        <div className="flex max-h-[85vh] flex-col">
          <div className="flex items-center justify-between gap-3 px-5 pt-4 pb-2">
            <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
            <IconButton label="Close" size="sm" icon={<X size={16} />} onClick={onClose} />
          </div>
          <div className="overflow-y-auto px-5 py-2">{children}</div>
          {footer && <div className="flex justify-end gap-2 px-5 pt-3 pb-5">{footer}</div>}
        </div>
      )}
    </dialog>
  );
}
