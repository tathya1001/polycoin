"use client";

import { useState } from "react";
import { Copy, Download } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";

// A recovery key, shown once (Phase 12.1). It is the only way back into the data if the password
// is forgotten: the server can't show it again, and nobody can reset a password without it. So
// the user must say they saved it before they can go on.
export function RecoveryKeyPanel({
  recoveryKey,
  intro,
  continueLabel = "Continue",
  onContinue,
}: {
  recoveryKey: string;
  intro: string;
  continueLabel?: string;
  onContinue: () => void;
}) {
  const toast = useToast();
  const [saved, setSaved] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(recoveryKey);
      toast.success("Recovery key copied.");
    } catch {
      toast.error("Could not copy. Select the key and copy it yourself.");
    }
  }

  function download() {
    const text =
      `MoneyAngle recovery key\n\n${recoveryKey}\n\n` +
      "With your email address, this key lets you set a new password if you forget yours.\n" +
      "Keep it somewhere safe and private. Anyone who has it can open your MoneyAngle data.\n";
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "moneyangle-recovery-key.txt";
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-2">{intro}</p>
      <p
        className="rounded-md border-[1.5px] border-line bg-surface px-4 py-3 text-center font-mono text-[15px] font-semibold tracking-wide break-all select-all"
        aria-label="Your recovery key"
      >
        {recoveryKey}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" icon={<Copy size={14} />} onClick={copy}>
          Copy
        </Button>
        <Button size="sm" icon={<Download size={14} />} onClick={download}>
          Download as a file
        </Button>
      </div>
      <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
        <li>It is shown only now. We can&apos;t show it again, and we can&apos;t reset your password for you.</li>
        <li>If you lose both your password and this key, your data can&apos;t be opened by anyone, us included.</li>
        <li>Keep it private: with your email address, it opens your account.</li>
      </ul>
      <Checkbox label="I have saved my recovery key somewhere safe" checked={saved} onChange={setSaved} />
      <Button variant="primary" className="w-full" disabled={!saved} onClick={onContinue}>
        {continueLabel}
      </Button>
    </div>
  );
}
