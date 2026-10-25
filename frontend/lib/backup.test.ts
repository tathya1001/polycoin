import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BackupProblem,
  fetchBackup,
  fileNameFrom,
  MAX_BACKUP_BYTES,
  restoreBackup,
  restoreSummary,
  type RestoreCounts,
} from "./backup";

const TODAY = new Date("2026-10-25T10:00:00Z");

describe("fileNameFrom", () => {
  it("uses the name the server sent", () => {
    const header = 'attachment; filename="backup-2026-10-24.polycoin"';
    expect(fileNameFrom(header, TODAY)).toBe("backup-2026-10-24.polycoin");
  });

  it.each([null, "attachment", 'attachment; filename="../../evil.sh"', 'attachment; filename="a b.polycoin"'])(
    "falls back to a dated name for %s",
    (header) => {
      expect(fileNameFrom(header, TODAY)).toBe("backup-2026-10-25.polycoin");
    },
  );
});

describe("restoreSummary", () => {
  const counts = (patch: Partial<RestoreCounts>): RestoreCounts => ({
    transactions: { added: 0, skipped: 0 },
    categories: { added: 0 },
    keywords: { added: 0 },
    dashboards: { added: 0, skipped: 0 },
    panels_skipped: 0,
    ...patch,
  });

  it("says what was added", () => {
    const text = restoreSummary(
      counts({ transactions: { added: 1200, skipped: 0 }, categories: { added: 1 }, dashboards: { added: 2, skipped: 0 } }),
    );
    expect(text).toBe("Restored 1,200 transactions, 1 category, 2 dashboards.");
  });

  it("says what was already there and what could not be restored", () => {
    const text = restoreSummary(
      counts({ transactions: { added: 0, skipped: 3 }, dashboards: { added: 0, skipped: 1 }, panels_skipped: 1 }),
    );
    expect(text).toBe(
      "Restored 0 transactions, 0 categories, 0 dashboards. 4 items were already there. 1 panel could not be restored.",
    );
  });
});

describe("the server calls", () => {
  afterEach(() => vi.unstubAllGlobals());

  function mockFetch(respond: () => Response) {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, init });
        return respond();
      }),
    );
    vi.stubGlobal("document", { cookie: "csrftoken=abc" });
    return calls;
  }

  it("downloads the file with the server's name", async () => {
    mockFetch(
      () =>
        new Response(new Uint8Array([1, 2, 3]), {
          headers: { "Content-Disposition": 'attachment; filename="backup-2026-10-25.polycoin"' },
        }),
    );
    const { name, blob } = await fetchBackup();
    expect(name).toBe("backup-2026-10-25.polycoin");
    expect(blob.size).toBe(3);
  });

  it("uploads the file as multipart form data", async () => {
    const calls = mockFetch(() => new Response(JSON.stringify({ panels_skipped: 0 }), { status: 200 }));
    await restoreBackup(new File([new Uint8Array([1])], "backup.polycoin"));
    expect(calls[0].url).toBe("/api/backup/restore/");
    expect(calls[0].init?.method).toBe("POST");
    expect((calls[0].init?.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("refuses a file that is too big without uploading it", async () => {
    const calls = mockFetch(() => new Response("{}"));
    const big = new File([new Uint8Array(MAX_BACKUP_BYTES + 1)], "big.polycoin");
    await expect(restoreBackup(big)).rejects.toMatchObject({ code: "too_large" });
    expect(calls).toHaveLength(0);
  });

  it("turns a refusal into a problem with the server's code", async () => {
    mockFetch(
      () =>
        new Response(JSON.stringify({ code: "not_your_backup", detail: "Not a backup of this account." }), {
          status: 400,
        }),
    );
    const failure = restoreBackup(new File([new Uint8Array([1])], "x.polycoin"));
    await expect(failure).rejects.toBeInstanceOf(BackupProblem);
    await expect(restoreBackup(new File([new Uint8Array([1])], "x.polycoin"))).rejects.toMatchObject({
      code: "not_your_backup",
      message: "Not a backup of this account.",
    });
  });
});
