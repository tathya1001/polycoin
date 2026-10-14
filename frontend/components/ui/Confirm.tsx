"use client";

import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";

type ConfirmOptions = {
  title: string;
  message?: ReactNode;
  confirmLabel?: string;
  tone?: "default" | "danger";
};

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm | null>(null);

// const confirm = useConfirm();  if (!(await confirm({ title: "Delete?", tone: "danger" }))) return;
export function useConfirm(): Confirm {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error("useConfirm must be used inside <ConfirmProvider>");
  return confirm;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((answer: boolean) => void) | null>(null);

  const confirm = useCallback<Confirm>((next) => {
    resolver.current?.(false); // a second question cancels the first
    setOptions(next);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  function answer(value: boolean) {
    resolver.current?.(value);
    resolver.current = null;
    setOptions(null);
  }

  return (
    <ConfirmContext value={confirm}>
      {children}
      <Dialog
        open={options !== null}
        onClose={() => answer(false)}
        title={options?.title ?? ""}
        footer={
          <>
            <Button variant="ghost" onClick={() => answer(false)}>
              Cancel
            </Button>
            <Button variant={options?.tone === "danger" ? "danger" : "primary"} onClick={() => answer(true)}>
              {options?.confirmLabel ?? "Confirm"}
            </Button>
          </>
        }
      >
        {options?.message && <p className="text-ink-2">{options.message}</p>}
      </Dialog>
    </ConfirmContext>
  );
}
