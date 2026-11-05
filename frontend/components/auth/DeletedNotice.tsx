"use client";

import { useSearchParams } from "next/navigation";

// Shown on the landing page after Settings → Delete my account (it sends the browser to
// /?account=deleted). Read in the browser so the landing page itself stays static.
export function DeletedNotice() {
  if (useSearchParams().get("account") !== "deleted") return null;
  return (
    <p role="status" className="mb-8 max-w-xl rounded-md border-[1.5px] border-line bg-surface px-4 py-3 text-sm">
      Your account and everything in it were deleted.
    </p>
  );
}
