// Data sources: loading them, and how a formula writes a source's name. Pure apart from the fetch.

import { apiFetch } from "@/lib/api";
import type { DataSource } from "@/lib/types";

export const SOURCES_URL = "/api/data-sources/";
export const MAX_SOURCE_NAME = 40; // datasources.models.MAX_SOURCE_NAME

const BARE_NAME = /^[A-Za-z_][A-Za-z_0-9]*$/;

export async function loadSources(): Promise<DataSource[]> {
  const res = await apiFetch(SOURCES_URL);
  return res.ok ? res.json() : [];
}

// A source's name as a formula writes it: in brackets unless it is one plain word (formula.source_ref).
export function sourceRef(name: string, keywords: string[]): string {
  const plain = BARE_NAME.test(name) && !keywords.includes(name.toUpperCase());
  return plain ? name : `[${name}]`;
}

// The ids that still exist. A saved filter can name a source deleted since.
export function knownSources(ids: string[], sources: DataSource[]): string[] {
  return ids.filter((id) => sources.some((source) => source.id === id));
}

export function sourceName(id: string, sources: DataSource[]): string {
  return sources.find((source) => source.id === id)?.name ?? "";
}
