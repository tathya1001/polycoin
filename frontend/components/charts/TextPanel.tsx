import { Fragment, type ReactNode } from "react";
import { parseMarkdown, type Block, type Inline } from "@/lib/markdown";

function inline(nodes: Inline[]): ReactNode {
  return nodes.map((node, index) => {
    if (node.kind === "text") return <Fragment key={index}>{node.text}</Fragment>;
    if (node.kind === "code") {
      return (
        <code key={index} className="rounded-sm bg-wash px-1 py-0.5 font-mono text-[0.9em]">
          {node.text}
        </code>
      );
    }
    if (node.kind === "bold") return <strong key={index} className="font-semibold">{inline(node.children)}</strong>;
    return <em key={index}>{inline(node.children)}</em>;
  });
}

const HEADINGS = {
  1: "text-xl font-semibold tracking-tight",
  2: "text-lg font-semibold tracking-tight",
  3: "text-base font-semibold",
} as const;

function block(item: Block, index: number): ReactNode {
  if (item.kind === "heading") {
    const Tag = `h${item.level}` as "h1" | "h2" | "h3";
    return <Tag key={index} className={HEADINGS[item.level]}>{inline(item.children)}</Tag>;
  }
  if (item.kind === "list") {
    return (
      <ul key={index} className="list-disc space-y-0.5 pl-5">
        {item.items.map((entry, i) => (
          <li key={i}>{inline(entry)}</li>
        ))}
      </ul>
    );
  }
  return <p key={index} className="whitespace-pre-line">{inline(item.children)}</p>;
}

// A note on the dashboard. The words become React elements and text nodes only, never HTML: see
// lib/markdown.ts for the few things that are interpreted.
export default function TextPanel({ text }: { text: string }) {
  const blocks = parseMarkdown(text);
  if (blocks.length === 0) {
    return (
      <div className="flex h-full items-center justify-center p-2 text-center text-sm text-muted">
        An empty note. Edit the panel to write something.
      </div>
    );
  }
  return <div className="h-full space-y-2 overflow-auto px-1 text-sm leading-relaxed">{blocks.map(block)}</div>;
}
