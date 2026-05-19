import { useState } from "react";
import cronstrue from "cronstrue";
import { api } from "@/lib/api";
import type { ProjectMaintainer } from "@/lib/types";
import CronInput from "@/components/CronInput";

function safeDescribe(expr: string): string {
  try { return cronstrue.toString(expr, { use24HourTimeFormat: false }); }
  catch { return ""; }
}

const STATUS_COLORS: Record<string, string> = {
  dispatched: "text-lcars-green",
  failed: "text-lcars-red",
  skipped: "text-lcars-amber",
  unknown: "text-lcars-muted",
};

const BLANK_FORM = {
  name: "",
  cron_expr: "0 9 * * *",
  enabled: true,
  log_sources: "",
  detection_instructions: "",
  fix_instructions: "",
  log_ttl_days: 7,
};

interface Props {
  projectId: string;
  maintainers: ProjectMaintainer[];
  onRefresh: () => void;
}

export default function MaintainerTab({ projectId, maintainers, onRefresh }: Props) {
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(BLANK_FORM);
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState<string | null>(null);
  const [triggerResult, setTriggerResult] = useState<Record<string, string>>({});

  function startCreate() {
    setForm(BLANK_FORM);
    setCreating(true);
    setEditingId(null);
  }

  function startEdit(m: ProjectMaintainer) {
    setForm({
      name: m.name,
      cron_expr: m.cron_expr,
      enabled: m.enabled,
      log_sources: m.log_sources,
      detection_instructions: m.detection_instructions,
      fix_instructions: m.fix_instructions,
      log_ttl_days: m.log_ttl_days,
    });
    setEditingId(m.id);
    setCreating(false);
  }

  function cancelForm() {
    setCreating(false);
    setEditingId(null);
  }

  async function saveForm() {
    setSaving(true);
    try {
      if (editingId) {
        await api.updateMaintainer(editingId, form);
      } else {
        await api.createMaintainer({ ...form, project_id: projectId });
      }
      cancelForm();
      onRefresh();
    } catch (e) {
      alert(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function deleteMaintainer(id: string) {
    if (!confirm("Delete this maintainer?")) return;
    try {
      await api.deleteMaintainer(id);
      onRefresh();
    } catch (e) {
      alert(String(e));
    }
  }

  async function runNow(id: string) {
    setTriggering(id);
    try {
      const result = await api.triggerMaintainer(id);
      setTriggerResult((prev) => ({ ...prev, [id]: result.status }));
      setTimeout(() => setTriggerResult((prev) => { const n = {...prev}; delete n[id]; return n; }), 4000);
      onRefresh();
    } catch (e) {
      alert(String(e));
    } finally {
      setTriggering(null);
    }
  }

  const showForm = creating || editingId !== null;
  const fieldCls = "w-full bg-lcars-panel border border-lcars-border text-lcars-text font-mono text-sm px-3 py-2 focus:outline-none focus:border-lcars-orange";
  const textareaCls = fieldCls + " resize-y min-h-[80px]";

  return (
    <div className="space-y-4">
      {!showForm && (
        <button
          onClick={startCreate}
          className="px-4 py-1.5 bg-lcars-orange text-black font-mono text-xs font-bold tracking-widest hover:bg-lcars-amber transition-colors"
        >
          + ADD MAINTAINER
        </button>
      )}

      {showForm && (
        <div className="bg-lcars-panel border border-lcars-border p-4 space-y-3">
          <div className="text-xs font-mono font-bold tracking-widest text-lcars-orange uppercase mb-2">
            {editingId ? "EDIT MAINTAINER" : "NEW MAINTAINER"}
          </div>

          <div>
            <label className="text-xs font-mono text-lcars-muted uppercase tracking-widest block mb-1">Name</label>
            <input className={fieldCls} value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="Daily Log Check" />
          </div>

          <div>
            <label className="text-xs font-mono text-lcars-muted uppercase tracking-widest block mb-1">Schedule</label>
            <CronInput value={form.cron_expr} onChange={(v) => setForm((f) => ({ ...f, cron_expr: v }))} />
          </div>

          <div>
            <label className="text-xs font-mono text-lcars-muted uppercase tracking-widest block mb-1">Log Sources</label>
            <textarea className={textareaCls} value={form.log_sources} onChange={(e) => setForm((f) => ({ ...f, log_sources: e.target.value }))} placeholder="Describe where to find logs: Railway dashboard, /api/logs endpoint, log file at /var/log/app.log, etc." />
          </div>

          <div>
            <label className="text-xs font-mono text-lcars-muted uppercase tracking-widest block mb-1">Detection Instructions</label>
            <textarea className={textareaCls} value={form.detection_instructions} onChange={(e) => setForm((f) => ({ ...f, detection_instructions: e.target.value }))} placeholder="How to determine if something went wrong: look for ERROR lines, 5xx responses, memory usage above 90%, etc." />
          </div>

          <div>
            <label className="text-xs font-mono text-lcars-muted uppercase tracking-widest block mb-1">Fix Instructions</label>
            <textarea className={textareaCls} value={form.fix_instructions} onChange={(e) => setForm((f) => ({ ...f, fix_instructions: e.target.value }))} placeholder="What to do when an issue is found: restart the service, roll back the last commit, send a notification, etc." />
          </div>

          <div>
            <label className="text-xs font-mono text-lcars-muted uppercase tracking-widest block mb-1">Log Retention (days)</label>
            <input type="number" min={1} max={365} className={fieldCls} value={form.log_ttl_days} onChange={(e) => setForm((f) => ({ ...f, log_ttl_days: parseInt(e.target.value) || 7 }))} />
          </div>

          <div className="flex items-center gap-2">
            <input type="checkbox" id="m-enabled" checked={form.enabled} onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))} />
            <label htmlFor="m-enabled" className="text-xs font-mono text-lcars-muted">Enabled</label>
          </div>

          <div className="flex gap-2 pt-1">
            <button onClick={saveForm} disabled={saving || !form.name || !form.cron_expr} className="px-4 py-1.5 bg-lcars-orange text-black font-mono text-xs font-bold tracking-widest hover:bg-lcars-amber transition-colors disabled:opacity-40">
              {saving ? "SAVING..." : "SAVE"}
            </button>
            <button onClick={cancelForm} className="px-4 py-1.5 border border-lcars-border text-lcars-muted font-mono text-xs hover:text-lcars-text transition-colors">
              CANCEL
            </button>
          </div>
        </div>
      )}

      {maintainers.length === 0 && !showForm && (
        <div className="text-lcars-muted font-mono text-sm p-4">
          NO MAINTAINERS CONFIGURED — ADD ONE TO START AUTOMATED LOG CHECKS
        </div>
      )}

      {maintainers.map((m) => (
        <div key={m.id} className="bg-lcars-panel border border-lcars-border p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-lcars-cyan font-medium">{m.name}</span>
                <span className={`text-xs font-mono ${m.enabled ? "text-lcars-green" : "text-lcars-muted"}`}>
                  {m.enabled ? "ENABLED" : "DISABLED"}
                </span>
                <span className={`text-xs font-mono ${STATUS_COLORS[m.last_status]}`}>{m.last_status}</span>
              </div>
              <div className="text-xs font-mono text-lcars-muted mt-1">
                {safeDescribe(m.cron_expr) || m.cron_expr}
                {m.last_run && <span className="ml-3">last run: {new Date(m.last_run).toLocaleString()}</span>}
              </div>
              <div className="text-xs font-mono text-lcars-muted mt-1">
                retention: {m.log_ttl_days}d
              </div>
            </div>
            <div className="flex gap-2 shrink-0">
              {triggerResult[m.id] && (() => {
                const tr = triggerResult[m.id] as string;
                return (
                  <span className={`text-xs font-mono self-center ${STATUS_COLORS[tr] ?? "text-lcars-muted"}`}>
                    {tr}
                  </span>
                );
              })()}
              <button
                onClick={() => runNow(m.id)}
                disabled={triggering === m.id}
                className="px-2 py-1 text-xs font-mono border border-lcars-border text-lcars-cyan hover:border-lcars-cyan transition-colors disabled:opacity-40"
              >
                {triggering === m.id ? "..." : "RUN NOW"}
              </button>
              <button
                onClick={() => startEdit(m)}
                className="px-2 py-1 text-xs font-mono border border-lcars-border text-lcars-muted hover:text-lcars-text transition-colors"
              >
                EDIT
              </button>
              <button
                onClick={() => deleteMaintainer(m.id)}
                className="px-2 py-1 text-xs font-mono border border-lcars-red/40 text-lcars-red hover:border-lcars-red transition-colors"
              >
                DEL
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
