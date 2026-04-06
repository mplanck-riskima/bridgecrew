import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { PromptTemplate, ScheduledTask } from "../lib/types";

const STATUS_COLORS: Record<string, string> = {
  dispatched: "text-lcars-green",
  failed: "text-lcars-red",
  skipped: "text-lcars-amber",
  unknown: "text-lcars-muted",
};

export default function Schedules() {
  const [schedules, setSchedules] = useState<ScheduledTask[]>([]);
  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    name: "",
    project_id: "",
    prompt: "",
    prompt_template_id: "",
    discord_channel_id: "",
    cron_expr: "",
    enabled: true,
  });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState<string | null>(null);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setLoading(true);
      setError(null);
      const [s, p] = await Promise.all([api.getSchedules(), api.getPrompts()]);
      setSchedules(s);
      setPrompts(p);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function startEdit(s: ScheduledTask) {
    setForm({
      name: s.name,
      project_id: s.project_id ?? "",
      prompt: s.prompt ?? "",
      prompt_template_id: s.prompt_template_id ?? "",
      discord_channel_id: s.discord_channel_id ?? "",
      cron_expr: s.cron_expr,
      enabled: s.enabled,
    });
    setEditingId(s.id);
    setCreating(false);
  }

  function cancelForm() {
    setCreating(false);
    setEditingId(null);
    setForm({ name: "", project_id: "", prompt: "", prompt_template_id: "", discord_channel_id: "", cron_expr: "", enabled: true });
  }

  async function save() {
    setSaving(true);
    try {
      if (editingId) {
        await api.updateSchedule(editingId, form);
        setEditingId(null);
      } else {
        await api.createSchedule(form);
        setCreating(false);
      }
      setForm({ name: "", project_id: "", prompt: "", prompt_template_id: "", discord_channel_id: "", cron_expr: "", enabled: true });
      await load();
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function toggle(s: ScheduledTask) {
    try {
      await api.updateSchedule(s.id, { enabled: !s.enabled });
      await load();
    } catch (e) {
      alert(String(e));
    }
  }

  async function trigger(s: ScheduledTask) {
    setTriggering(s.id);
    try {
      const result = await api.triggerSchedule(s.id);
      alert(`Dispatched: ${result.status}`);
      await load();
    } catch (e) {
      alert(String(e));
    } finally {
      setTriggering(null);
    }
  }

  async function remove(s: ScheduledTask) {
    if (!confirm(`Delete schedule "${s.name}"?`)) return;
    try {
      await api.deleteSchedule(s.id);
      await load();
    } catch (e) {
      alert(String(e));
    }
  }

  const promptName = (id: string) => prompts.find((p) => p.id === id)?.name ?? id;

  const inputCls = "w-full bg-lcars-panel border border-lcars-border text-lcars-text font-mono text-sm px-3 py-2 focus:outline-none focus:border-lcars-orange placeholder:text-lcars-muted";
  const labelCls = "block text-xs font-mono tracking-widest text-lcars-muted uppercase mb-1";

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-1 h-6 bg-lcars-orange" />
          <h1 className="text-lcars-orange font-mono text-xs tracking-[0.3em] uppercase">
            Standing Orders
          </h1>
        </div>
        {!creating && !editingId && (
          <button
            onClick={() => setCreating(true)}
            className="px-4 py-1.5 text-xs font-mono font-bold tracking-widest uppercase bg-lcars-orange text-black hover:bg-lcars-amber transition-colors"
          >
            + New Order
          </button>
        )}
      </div>

      {(creating || editingId) && (
        <div className="bg-lcars-panel border border-lcars-border">
          <div className="px-3 py-1 border-b border-lcars-border">
            <span className="text-lcars-orange text-xs font-mono tracking-[0.2em] uppercase">
              {editingId ? "Edit Scheduled Task" : "New Scheduled Task"}
            </span>
          </div>
          <div className="p-4 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className={labelCls}>Name</label>
                <input
                  className={inputCls}
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. Daily health check"
                />
              </div>
              <div>
                <label className={labelCls}>Cron Expression</label>
                <input
                  className={inputCls}
                  value={form.cron_expr}
                  onChange={(e) => setForm((f) => ({ ...f, cron_expr: e.target.value }))}
                  placeholder="0 9 * * *"
                />
              </div>
              <div>
                <label className={labelCls}>Persona (optional)</label>
                <select
                  className={inputCls}
                  value={form.prompt_template_id}
                  onChange={(e) => setForm((f) => ({ ...f, prompt_template_id: e.target.value }))}
                >
                  <option value="">No persona</option>
                  {prompts.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className={labelCls}>Discord Channel ID (optional — defaults to main channel)</label>
                <input
                  className={inputCls}
                  value={form.discord_channel_id}
                  onChange={(e) => setForm((f) => ({ ...f, discord_channel_id: e.target.value }))}
                  placeholder="Leave blank to use default channel"
                />
              </div>
            </div>
            <div>
              <label className={labelCls}>Prompt</label>
              <textarea
                className={inputCls}
                rows={4}
                value={form.prompt}
                onChange={(e) => setForm((f) => ({ ...f, prompt: e.target.value }))}
                placeholder="The message to send to the Discord channel..."
              />
            </div>
            <div className="flex gap-3">
              <button
                onClick={save}
                disabled={saving || !form.name || !form.prompt || !form.cron_expr}
                className="px-4 py-1.5 text-xs font-mono font-bold tracking-widest uppercase bg-lcars-orange text-black hover:bg-lcars-amber disabled:opacity-40 transition-colors"
              >
                {saving ? "SAVING..." : "SAVE"}
              </button>
              <button
                onClick={cancelForm}
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

      {!loading && schedules.length === 0 && !creating && (
        <div className="text-lcars-muted font-mono text-sm p-4">NO SCHEDULED TASKS ON RECORD</div>
      )}

      <div className="space-y-3">
        {schedules.map((s) => (
          <div
            key={s.id}
            className={`bg-lcars-panel border border-lcars-border ${!s.enabled ? "opacity-50" : ""}`}
          >
            <div className="px-3 py-1 border-b border-lcars-border flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
              <div className="flex items-center gap-3">
                <span className="text-lcars-cyan font-mono text-xs font-bold tracking-widest uppercase">{s.name}</span>
                <span className={`text-xs font-mono font-bold tracking-widest ${s.enabled ? "text-lcars-green" : "text-lcars-muted"}`}>
                  {s.enabled ? "ENABLED" : "DISABLED"}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => trigger(s)}
                  disabled={triggering === s.id}
                  className="text-xs font-mono bg-lcars-blue/20 border border-lcars-blue text-lcars-cyan px-3 py-1 hover:bg-lcars-blue/30 disabled:opacity-50 transition-colors"
                >
                  {triggering === s.id ? "TRIGGERING..." : "TRIGGER NOW"}
                </button>
                <button
                  onClick={() => startEdit(s)}
                  className="text-xs font-mono text-lcars-muted hover:text-lcars-text tracking-widest transition-colors"
                >
                  EDIT
                </button>
                <button
                  onClick={() => toggle(s)}
                  className="text-xs font-mono text-lcars-muted hover:text-lcars-text tracking-widest transition-colors"
                >
                  {s.enabled ? "DISABLE" : "ENABLE"}
                </button>
                <button
                  onClick={() => remove(s)}
                  className="text-xs font-mono text-lcars-border hover:text-lcars-red tracking-widest transition-colors"
                >
                  DELETE
                </button>
              </div>
            </div>
            <div className="p-4">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs font-mono">
                <div>
                  <span className="text-lcars-muted tracking-widest">CRON</span>
                  <div className="text-lcars-amber mt-0.5">{s.cron_expr}</div>
                </div>
                <div>
                  <span className="text-lcars-muted tracking-widest">PERSONA</span>
                  <div className="text-lcars-text mt-0.5">{s.prompt_template_id ? promptName(s.prompt_template_id) : "—"}</div>
                </div>
                <div>
                  <span className="text-lcars-muted tracking-widest">CHANNEL</span>
                  <div className="text-lcars-text mt-0.5">{s.discord_channel_id || "default"}</div>
                </div>
              </div>
              {s.prompt && (
                <div className="mt-3 text-xs font-mono">
                  <span className="text-lcars-muted tracking-widest">PROMPT</span>
                  <div className="text-lcars-text mt-0.5 whitespace-pre-wrap line-clamp-3">{s.prompt}</div>
                </div>
              )}
              <div className="mt-2 text-xs font-mono text-lcars-muted">
                LAST RUN:{" "}
                <span className="text-lcars-text">
                  {s.last_run ? new Date(s.last_run).toLocaleString().toUpperCase() : "NEVER"}
                </span>
                {" — "}
                <span className={STATUS_COLORS[s.last_status] ?? "text-lcars-muted"}>
                  {s.last_status.toUpperCase()}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
