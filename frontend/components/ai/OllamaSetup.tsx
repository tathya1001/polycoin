"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { DEFAULT_OLLAMA_URL, loopbackUrl, type OllamaError } from "@/lib/ollama";
import { Button } from "@/components/ui/Button";
import { Card, Chip } from "@/components/ui/Card";
import { Field, Input } from "@/components/ui/Field";

type OS = "windows" | "macos" | "linux";

function guessOS(): OS {
  const agent = typeof navigator === "undefined" ? "" : navigator.userAgent;
  if (agent.includes("Windows")) return "windows";
  if (agent.includes("Mac")) return "macos";
  return "linux";
}

// How to add this site to OLLAMA_ORIGINS, Ollama's list of web pages allowed to call it.
function originCommands(os: OS, origin: string): string[] {
  if (os === "windows") return [`setx OLLAMA_ORIGINS "${origin}"`];
  if (os === "macos") return [`launchctl setenv OLLAMA_ORIGINS "${origin}"`];
  return [
    "sudo systemctl edit ollama.service",
    `# add these two lines:\n[Service]\nEnvironment="OLLAMA_ORIGINS=${origin}"`,
    "sudo systemctl daemon-reload && sudo systemctl restart ollama",
  ];
}

function Code({ children }: { children: string }) {
  return (
    <pre className="mt-1.5 overflow-x-auto rounded-sm border-[1.5px] border-ink/30 bg-canvas px-3 py-2 font-mono text-[13px] whitespace-pre-wrap">
      {children}
    </pre>
  );
}

const TITLES: Partial<Record<OllamaError["code"], string>> = {
  unreachable: "Can't reach Ollama on this computer",
  no_embedding_models: "Ollama has no embedding model yet",
};

export function OllamaSetup({
  problem,
  url,
  checking,
  onRetry,
  onUrlChange,
}: {
  problem: OllamaError;
  url: string;
  checking: boolean;
  onRetry: () => void;
  onUrlChange: (url: string) => void;
}) {
  const [os, setOS] = useState<OS>(guessOS);
  const [draft, setDraft] = useState(url);
  const [draftError, setDraftError] = useState<string | null>(null);

  const origin = typeof window === "undefined" ? "" : window.location.origin;
  // A site served from this computer (local development) is allowed by Ollama already.
  const servedLocally = loopbackUrl(origin) !== null;

  function saveUrl() {
    const clean = loopbackUrl(draft);
    if (!clean) {
      setDraftError("Use an address on this computer, e.g. http://localhost:11434.");
      return;
    }
    setDraftError(null);
    setDraft(clean);
    onUrlChange(clean);
  }

  return (
    <Card className="mb-5 space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">{TITLES[problem.code] ?? problem.message}</h2>
        <p className="mt-1 text-sm text-ink-2">
          AI categorisation runs on Ollama on your own desktop or laptop. Your transaction text goes from this browser
          to your Ollama and nowhere else. Set it up once:
        </p>
      </div>

      <ol className="list-decimal space-y-3 pl-5 text-sm">
        <li>
          Install Ollama from{" "}
          <a href="https://ollama.com/download" target="_blank" rel="noreferrer" className="font-semibold underline underline-offset-4">
            ollama.com/download
          </a>{" "}
          and start it.
        </li>
        <li>
          Download the embedding model:
          <Code>ollama pull nomic-embed-text</Code>
        </li>
        {!servedLocally && (
          <li>
            Allow this site to use it. Run this, then quit Ollama completely and start it again:
            <div className="mt-2 flex gap-2">
              <Chip active={os === "windows"} onClick={() => setOS("windows")}>Windows</Chip>
              <Chip active={os === "macos"} onClick={() => setOS("macos")}>macOS</Chip>
              <Chip active={os === "linux"} onClick={() => setOS("linux")}>Linux</Chip>
            </div>
            {originCommands(os, origin).map((command) => (
              <Code key={command}>{command}</Code>
            ))}
            <p className="mt-1.5 text-ink-2">
              Already have an OLLAMA_ORIGINS value? Add this site after a comma. Never use <code>*</code>: that lets every
              website use your Ollama.
            </p>
          </li>
        )}
        <li>If your browser asks to let this site access devices on your local network, choose Allow.</li>
      </ol>

      <p className="text-sm text-ink-2">
        Still stuck? Check that Ollama is running, that you restarted it after step {servedLocally ? 2 : 3}, and that your
        browser isn&apos;t blocking local requests (some privacy shields do). Phones can&apos;t run this.
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <Button variant="primary" loading={checking} icon={<RefreshCw size={16} />} onClick={onRetry}>
          {checking ? "Checking…" : "Check again"}
        </Button>
        <details className="text-sm">
          <summary className="cursor-pointer text-ink-2">Ollama on another port?</summary>
          <div className="mt-2 flex items-end gap-2">
            <Field label="Ollama address" error={draftError} className="w-64">
              <Input dense value={draft} placeholder={DEFAULT_OLLAMA_URL} onChange={(e) => setDraft(e.target.value)} />
            </Field>
            <Button size="sm" onClick={saveUrl}>
              Save
            </Button>
          </div>
        </details>
      </div>
    </Card>
  );
}
