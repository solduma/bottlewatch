"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import { listThesis, saveThesis, deleteThesis } from "../lib/api";
import type { ThesisRow } from "../lib/api";

// ---------------------------------------------------------------------------
// Tiny ProseMirror JSON -> markdown serializer.
//
// The thesis body is stored in a `body_md` column on the backend,
// but TipTap's API is HTML (editor.getHTML) or ProseMirror JSON
// (editor.getJSON). Using getText() drops all formatting; using
// getHTML() doesn't match the column type. A markdown serializer
// walks the JSON tree and emits markdown for the StarterKit node
// set we actually use (doc, paragraph, heading, text, bold, italic,
// bulletList, orderedList, listItem, codeBlock, blockquote,
// hardBreak, horizontalRule).
//
// We don't pull in `@tiptap/extension-markdown` (yet) because it
// pulls ProseMirror markdown deps; the below is ~40 lines and
// covers all the formatting the toolbar exposes.
// ---------------------------------------------------------------------------

interface PMNode {
  type: string;
  text?: string;
  marks?: { type: string }[];
  content?: PMNode[];
}

function escapeMdText(s: string): string {
  return s.replace(/([\\`*_{}\[\]<>])/g, "\\$1");
}

function serializeText(node: PMNode): string {
  if (!node.text) return "";
  let s = escapeMdText(node.text);
  if (node.marks) {
    for (const m of node.marks) {
      if (m.type === "bold") s = `**${s}**`;
      else if (m.type === "italic") s = `*${s}*`;
      else if (m.type === "code") s = `\`${s}\``;
    }
  }
  return s;
}

function serializeInline(nodes: PMNode[] | undefined): string {
  if (!nodes) return "";
  return nodes.map(n => (n.type === "text" ? serializeText(n) : serializeNode(n))).join("");
}

function serializeNode(node: PMNode): string {
  switch (node.type) {
    case "doc":
      return (node.content ?? []).map(serializeNode).join("\n\n");
    case "paragraph":
      return serializeInline(node.content);
    case "heading": {
      const level = Math.max(1, Math.min(6, (node as PMNode & { attrs?: { level?: number } }).attrs?.level ?? 1));
      return `${"#".repeat(level)} ${serializeInline(node.content)}`;
    }
    case "bulletList":
      return (node.content ?? []).map(item => `- ${serializeInline(item.content)}`).join("\n");
    case "orderedList":
      return (node.content ?? [])
        .map((item, i) => `${i + 1}. ${serializeInline(item.content)}`)
        .join("\n");
    case "listItem":
      return serializeInline(node.content);
    case "codeBlock":
      return "```\n" + serializeInline(node.content) + "\n```";
    case "blockquote":
      return (node.content ?? []).map(serializeNode).join("\n\n").replace(/^/gm, "> ");
    case "horizontalRule":
      return "---";
    case "hardBreak":
      return "  \n";
    default:
      return serializeInline(node.content);
  }
}

function editorJsonToMarkdown(editor: { getJSON: () => unknown }): string {
  return serializeNode(editor.getJSON() as PMNode).trim();
}

const SEGMENTS = [
  "advanced_node_fabs", "advanced_packaging", "cooling_water", "data_center_shell",
  "gpu_asic_silicon", "hbm_memory", "networking_interconnect",
  "power_generation_oem", "systems_rack_scale", "transformers_tnd",
];

function ThesisCard({ thesis, onDelete }: { thesis: ThesisRow; onDelete: (id: number) => void }) {
  return (
    <div className="rounded border border-gray-200 bg-white p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Link
            href={`/segment/${thesis.segment}`}
            className="font-mono text-xs font-medium text-blue-700 hover:underline"
          >
            {thesis.segment}
          </Link>
          {thesis.ticker && (
            <span className="font-mono text-xs text-gray-500">{thesis.ticker}</span>
          )}
          {thesis.side && (
            <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${
              thesis.side === "long" ? "bg-blue-100 text-blue-800" : "bg-green-100 text-green-800"
            }`}>
              {thesis.side}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">
            {new Date(thesis.updated_at).toLocaleDateString()}
          </span>
          <button
            onClick={() => onDelete(thesis.id)}
            className="text-xs text-red-400 hover:text-red-600"
          >
            Delete
          </button>
        </div>
      </div>
      <div className="prose prose-sm max-w-none text-gray-700">
        {thesis.body_md}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Thesis editor (TipTap)
// ---------------------------------------------------------------------------

interface EditorProps {
  segment: string;
  ticker?: string;
  side?: string;
  editId?: number;
  initialBody?: string;
  onSave: () => void;
  onCancel: () => void;
}

function ThesisEditor({ segment, ticker, side, initialBody = "", onSave, onCancel }: EditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Placeholder.configure({ placeholder: "Write your thesis here…" }),
    ],
    content: initialBody,
    editorProps: {
      attributes: {
        class: "prose prose-sm max-w-none focus:outline-none min-h-[120px] px-3 py-2",
      },
    },
  });

  const handleSave = useCallback(async () => {
    if (!editor) return;
    const body_md = editorJsonToMarkdown(editor);
    if (!body_md.trim()) return;
    await saveThesis({ segment, ticker, side: side || null, body_md });
    onSave();
  }, [editor, segment, ticker, side, onSave]);

  return (
    <div className="rounded border border-blue-200 bg-blue-50 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Link href={`/segment/${segment}`} className="font-mono text-xs font-medium text-blue-700 hover:underline">
          {segment}
        </Link>
        {ticker && <span className="font-mono text-xs text-gray-500">{ticker}</span>}
        {side && (
          <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${
            side === "long" ? "bg-blue-200 text-blue-900" : "bg-green-200 text-green-900"
          }`}>
            {side}
          </span>
        )}
      </div>
      <div className="mb-3 rounded border border-gray-300 bg-white">
        <div className="flex gap-1 border-b border-gray-200 bg-gray-50 px-2 py-1">
          <button
            onClick={() => editor?.chain().focus().toggleBold().run()}
            className={`rounded px-1.5 py-0.5 text-sm font-bold ${editor?.isActive("bold") ? "bg-blue-100 text-blue-800" : "text-gray-600"}`}
          >
            B
          </button>
          <button
            onClick={() => editor?.chain().focus().toggleItalic().run()}
            className={`rounded px-1.5 py-0.5 text-sm italic ${editor?.isActive("italic") ? "bg-blue-100 text-blue-800" : "text-gray-600"}`}
          >
            I
          </button>
          <button
            onClick={() => editor?.chain().focus().toggleBulletList().run()}
            className="rounded px-1.5 py-0.5 text-sm text-gray-600"
          >
            •
          </button>
        </div>
        <EditorContent editor={editor} />
      </div>
      <div className="flex justify-end gap-2">
        <button onClick={onCancel} className="rounded border border-gray-300 bg-white px-3 py-1 text-sm text-gray-600 hover:bg-gray-50">
          Cancel
        </button>
        <button
          onClick={handleSave}
          className="rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700"
        >
          Save note
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ThesisPage() {
  const [notes, setNotes] = useState<ThesisRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [showEditor, setShowEditor] = useState(false);
  const [editSegment, setEditSegment] = useState(SEGMENTS[0]);
  const [editTicker, setEditTicker] = useState("");
  const [editSide, setEditSide] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setNotes(await listThesis());
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleDelete = useCallback(async (id: number) => {
    await deleteThesis(id);
    setNotes(prev => prev.filter(n => n.id !== id));
  }, []);

  const handleSave = useCallback(() => {
    setShowEditor(false);
    load();
  }, [load]);

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Thesis notes</h1>
        <Link href="/" className="text-sm text-blue-700 hover:underline">← Back to quadrant</Link>
      </div>

      <p className="mb-4 text-sm text-gray-600">
        Override-audit-trail for the conviction basket. A thesis note linked
        to a RESOLVING segment surfaces your contrary view when the hard guard fires.
      </p>

      <div className="mb-6">
        {!showEditor ? (
          <button
            onClick={() => setShowEditor(true)}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            + New thesis note
          </button>
        ) : (
          <div className="mb-4 space-y-3">
            <div className="flex flex-wrap gap-2">
              <select
                value={editSegment}
                onChange={e => setEditSegment(e.target.value)}
                className="rounded border border-gray-200 bg-white px-2 py-1 text-sm"
              >
                {SEGMENTS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
              <input
                value={editTicker}
                onChange={e => setEditTicker(e.target.value)}
                placeholder="Ticker (optional)"
                className="rounded border border-gray-200 bg-white px-2 py-1 text-sm font-mono"
              />
              <div className="flex gap-1 rounded border border-gray-200 bg-white p-1 text-sm">
                {["", "long", "short"].map(s => (
                  <button
                    key={s}
                    onClick={() => setEditSide(s)}
                    className={`rounded px-2 py-0.5 ${editSide === s ? "bg-blue-100 text-blue-800 font-medium" : "text-gray-600"}`}
                  >
                    {s || "neutral"}
                  </button>
                ))}
              </div>
            </div>
            <ThesisEditor
              segment={editSegment}
              ticker={editTicker || undefined}
              side={editSide || undefined}
              onSave={handleSave}
              onCancel={() => setShowEditor(false)}
            />
          </div>
        )}
      </div>

      {loading ? (
        <div className="text-sm text-gray-500">Loading…</div>
      ) : notes.length === 0 ? (
        <div className="rounded border border-dashed border-gray-200 bg-gray-50 p-8 text-center text-sm text-gray-400 italic">
          No thesis notes yet. Add one above.
        </div>
      ) : (
        <div className="space-y-3">
          {notes.map(n => (
            <ThesisCard key={n.id} thesis={n} onDelete={handleDelete} />
          ))}
        </div>
      )}
    </section>
  );
}