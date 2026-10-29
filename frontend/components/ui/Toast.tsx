"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "@/lib/cn";

type Tone = "success" | "error" | "info";
type ToastOptions = {
  tone?: Tone;
  action?: { label: string; onClick: () => void }; // e.g. Undo
  duration?: number; // ms; 0 keeps it until dismissed
};
type ToastItem = ToastOptions & { id: number; message: string };

type ToastApi = {
  toast: (message: string, options?: ToastOptions) => void;
  success: (message: string, options?: Omit<ToastOptions, "tone">) => void;
  error: (message: string, options?: Omit<ToastOptions, "tone">) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error("useToast must be used inside <ToastProvider>");
  return api;
}

const ICONS = { success: CheckCircle2, error: AlertCircle, info: Info };
const ICON_COLOR = { success: "text-pos", error: "text-neg", info: "text-ink" };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);

  const toast = useCallback(
    (message: string, options: ToastOptions = {}) => {
      const id = nextId.current++;
      const tone = options.tone ?? "info";
      const duration = options.duration ?? (options.action || tone === "error" ? 7000 : 4000);
      setItems((all) => [...all.slice(-3), { ...options, tone, id, message }]); // keep at most 4
      if (duration > 0) window.setTimeout(() => dismiss(id), duration);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      toast,
      success: (message, options) => toast(message, { ...options, tone: "success" }),
      error: (message, options) => toast(message, { ...options, tone: "error" }),
    }),
    [toast],
  );

  return (
    <ToastContext value={api}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-[min(92vw,22rem)] flex-col gap-2"
      >
        {items.map((item) => {
          const tone = item.tone ?? "info";
          const Icon = ICONS[tone];
          return (
            <div
              key={item.id}
              role={tone === "error" ? "alert" : "status"}
              className="pointer-events-auto flex animate-[toast-in_200ms_var(--ease-spring)] items-start gap-3 rounded-md border-[1.5px] border-line bg-surface p-3 shadow-pop"
            >
              <Icon size={18} className={cn("mt-0.5 shrink-0", ICON_COLOR[tone])} aria-hidden />
              <p className="flex-1 text-sm font-medium">{item.message}</p>
              {item.action && (
                <button
                  type="button"
                  className="text-sm font-semibold underline underline-offset-2"
                  onClick={() => {
                    item.action?.onClick();
                    dismiss(item.id);
                  }}
                >
                  {item.action.label}
                </button>
              )}
              <button type="button" aria-label="Dismiss" onClick={() => dismiss(item.id)} className="text-muted hover:text-ink">
                <X size={16} aria-hidden />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext>
  );
}
