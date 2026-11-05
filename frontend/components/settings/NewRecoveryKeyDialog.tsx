"use client";

import { useState } from "react";
import { RecoveryKeyPanel } from "@/components/auth/RecoveryKeyPanel";
import { PasswordConfirmDialog } from "@/components/settings/PasswordConfirmDialog";
import { Dialog } from "@/components/ui/Dialog";

// Phase 12.1, D14: for a user who lost their recovery key but can still sign in. The password
// first, then the new key, shown once. The old key stops working.
export function NewRecoveryKeyDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [recoveryKey, setRecoveryKey] = useState<string | null>(null);

  function finish() {
    setRecoveryKey(null);
    onClose();
  }

  if (recoveryKey) {
    return (
      // Closing without confirming is allowed: the key works from now on either way.
      <Dialog open onClose={finish} title="Your new recovery key">
        <div className="pb-3">
          <RecoveryKeyPanel
            recoveryKey={recoveryKey}
            intro="Your old recovery key no longer works. Save this one instead."
            continueLabel="Done"
            onContinue={finish}
          />
        </div>
      </Dialog>
    );
  }

  return (
    <PasswordConfirmDialog
      open={open}
      onClose={onClose}
      title="Make a new recovery key?"
      url="/api/accounts/recovery-key/"
      confirmLabel="Make a new key"
      failure="Could not make a new recovery key."
      onDone={async (res) => setRecoveryKey((await res.json()).recovery_key)}
    >
      <p className="text-ink-2">
        Your current recovery key will stop working, and you will be shown a new one, once. Do this if you lost the
        old one or think someone else has seen it.
      </p>
    </PasswordConfirmDialog>
  );
}
