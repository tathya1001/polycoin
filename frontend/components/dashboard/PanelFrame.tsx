"use client";

import { useState, type ReactNode } from "react";

type Props = {
  title: string;
  editing: boolean; // Edit mode: show the grip and the ⋯ menu
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  children: ReactNode;
};

// The box around one chart: a header and, in Edit mode, a ⋯ menu. The grid lays an
// invisible move handle over the header, so dragging the title moves the panel.
export default function PanelFrame({ title, editing, onEdit, onDuplicate, onDelete, children }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);

  function closeMenu() {
    setMenuOpen(false);
    setConfirming(false);
  }

  return (
    <section className="flex h-full flex-col overflow-hidden rounded-lg border border-gray-200 bg-background shadow-sm dark:border-gray-800">
      <header className="flex items-center gap-2 border-b border-gray-100 px-3 py-1.5 dark:border-gray-900">
        <h2
          className={`min-w-0 flex-1 truncate text-sm font-medium ${editing ? "select-none" : ""}`}
          title={title}
        >
          {editing && <span className="mr-1.5 text-gray-400" aria-hidden>⠿</span>}
          {title || <span className="text-gray-400">Untitled</span>}
        </h2>
        {editing && (
          <div className="relative">
            <button
              onClick={() => (menuOpen ? closeMenu() : setMenuOpen(true))}
              className="rounded px-1.5 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-900"
              aria-label="Panel menu"
              aria-expanded={menuOpen}
            >
              ⋯
            </button>
            {menuOpen && (
              <div className="absolute right-0 top-7 z-30 w-40 rounded-md border border-gray-200 bg-background py-1 text-sm shadow-lg dark:border-gray-800">
                {confirming ? (
                  <div className="flex flex-col gap-2 px-3 py-2">
                    <p>Delete this panel?</p>
                    <div className="flex gap-3">
                      <button className="text-red-600 underline" onClick={() => { closeMenu(); onDelete(); }}>
                        Delete
                      </button>
                      <button className="underline" onClick={closeMenu}>Cancel</button>
                    </div>
                  </div>
                ) : (
                  <>
                    <MenuItem onClick={() => { closeMenu(); onEdit(); }}>Edit…</MenuItem>
                    <MenuItem onClick={() => { closeMenu(); onDuplicate(); }}>Duplicate</MenuItem>
                    <MenuItem onClick={() => setConfirming(true)} danger>Delete…</MenuItem>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </header>
      <div className="min-h-0 flex-1 p-2">{children}</div>
    </section>
  );
}

function MenuItem({ children, onClick, danger }: { children: ReactNode; onClick: () => void; danger?: boolean }) {
  return (
    <button
      onClick={onClick}
      className={`block w-full px-3 py-1.5 text-left hover:bg-gray-100 dark:hover:bg-gray-900 ${danger ? "text-red-600" : ""}`}
    >
      {children}
    </button>
  );
}
