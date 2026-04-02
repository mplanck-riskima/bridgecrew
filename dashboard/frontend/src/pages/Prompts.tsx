import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { PromptTemplate } from "../lib/types";

export default function Prompts() {
  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<PromptTemplate | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", content: "" });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setLoading(true);
      setError(null);
      setPrompts(await api.getPrompts());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function openCreate() {
    setForm({ name: "", description: "", content: "" });
    setCreating(true);
    setEditing(null);
  }

  function openEdit(p: PromptTemplate) {
    setForm({ name: p.name, description: p.description, content: p.content });
    setEditing(p);
    setCreating(false);
  }

  function cancel() {
    setCreating(false);
    setEditing(null);
  }

  async function save() {
    setSaving(true);
    try {
      if (creating) {
        await api.createPrompt(form);
      } else if (editing) {
        await api.updatePrompt(editing.id, form);
      }
      cancel();
      await load();
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function remove(p: PromptTemplate) {
    if (!confirm(`Delete prompt "${p.name}"?`)) return;
    try {
      await api.deletePrompt(p.id);
      await load();
    } catch (e) {
      alert(String(e));
    }
  }

  const showForm = creating || editing !== null;

  const inputCls = "w-full bg-lcars-panel border border-lcars-border text-lcars-text font-mono text-sm px-3 py-2 focus:outline-none focus:border-lcars-orange placeholder:text-lcars-muted";
  const labelCls = "block text-xs font-mono tracking-widest text-lcars-muted uppercase mb-1";

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-1 h-6 bg-lcars-orange" />
          <h1 className="text-lcars-orange font-mono text-xs tracking-[0.3em] uppercase">
            Crew Personas
          </h1>
        </div>
        {!showForm && (
          <button
            onClick={openCreate}
            className="px-4 py-1.5 text-xs font-mono font-bold tracking-widest uppercase bg-lcars-orange text-black hover:bg-lcars-amber transition-colors"
          >
            + New Template
          </button>
        )}
      </div>

      {showForm && (
        <div className="bg-lcars-panel border border-lcars-border">
          <div className="px-3 py-1 border-b border-lcars-border">
            <span className="text-lcars-orange text-xs font-mono tracking-[0.2em] uppercase">
              {creating ? "New Prompt Template" : `Edit: ${editing?.name}`}
            </span>
          </div>
          <div className="p-4 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelCls}>Name</label>
                <input
                  className={inputCls}
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. scotty, tech-lead"
                />
              </div>
              <div>
                <label className={labelCls}>Description</label>
                <input
                  className={inputCls}
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  placeholder="Short description"
                />
              </div>
            </div>
            <div>
              <label className={labelCls}>Persona Content</label>
              <textarea
                className={`${inputCls} resize-y`}
                rows={10}
                value={form.content}
                onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
                placeholder="Write the persona/system prompt text here. This will be injected into Claude sessions via --append-system-prompt-file."
              />
            </div>
            <div className="flex gap-3">
              <button
                onClick={save}
                disabled={saving || !form.name || !form.content}
                className="px-4 py-1.5 text-xs font-mono font-bold tracking-widest uppercase bg-lcars-orange text-black hover:bg-lcars-amber disabled:opacity-40 transition-colors"
              >
                {saving ? "SAVING..." : "SAVE"}
              </button>
              <button
                onClick={cancel}
                className="px-4 py-1.5 text-xs font-mono font-bold tracking-widest uppercase border border-lcars-border text-lcars-muted hover:text-lcars-text hover:border-lcars-muted transition-colors"
              >
                CANCEL
              </button>
            </div>
          </div>
        </div>
      )}

      {loading && (
        <div className="text-lcars-muted font-mono text-sm animate-pulse p-4">── RETRIEVING ──</div>
      )}
      {error && <div className="text-lcars-red font-mono text-sm p-4">{error}</div>}

      {!loading && prompts.length === 0 && !showForm && (
        <div className="text-lcars-muted font-mono text-sm p-4">NO TEMPLATES ON RECORD</div>
      )}

      <div className="space-y-3">
        {prompts.map((p) => (
          <div key={p.id} className="bg-lcars-panel border border-lcars-border">
            <div className="px-3 py-1 border-b border-lcars-border flex items-center justify-between">
              <span className="text-lcars-cyan font-mono text-xs font-bold tracking-widest uppercase">{p.name}</span>
              <div className="flex gap-3">
                <button
                  onClick={() => openEdit(p)}
                  className="text-xs font-mono text-lcars-amber hover:text-lcars-orange transition-colors tracking-widest"
                >
                  EDIT
                </button>
                <button
                  onClick={() => remove(p)}
                  className="text-xs font-mono text-lcars-border hover:text-lcars-red transition-colors tracking-widest"
                >
                  DELETE
                </button>
              </div>
            </div>
            <div className="p-4">
              {p.description && (
                <div className="text-lcars-muted text-sm mb-2">{p.description}</div>
              )}
              <pre className="text-xs text-lcars-muted bg-lcars-bg border border-lcars-border p-3 whitespace-pre-wrap font-mono max-h-40 overflow-auto">
                {p.content}
              </pre>
              <div className="text-xs font-mono text-lcars-muted mt-2 tracking-widest">
                UPDATED {new Date(p.updated_at).toLocaleString().toUpperCase()}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
