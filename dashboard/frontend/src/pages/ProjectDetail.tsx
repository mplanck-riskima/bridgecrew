import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import StatusBadge from "@/components/StatusBadge";
import { api } from "@/lib/api";
import type { ActivityEntry, Feature, Project, PromptTemplate } from "@/lib/types";
import { formatCurrency, formatDate } from "@/lib/utils";

type Tab = "features" | "activity" | "costs";

function LcarsPanel({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="bg-lcars-panel border border-lcars-border">
      <div className="px-3 py-1 border-b border-lcars-border">
        <span className="text-lcars-orange text-xs font-mono tracking-[0.2em] uppercase">{label}</span>
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("features");
  const [project, setProject] = useState<Project | null>(null);
  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [confirmDeleteProject, setConfirmDeleteProject] = useState(false);
  const [savingPrompt, setSavingPrompt] = useState(false);

  useEffect(() => {
    load();
  }, [id]);

  async function load() {
    if (!id) return;
    try {
      setLoading(true);
      setError(null);
      const [p, ps, acts] = await Promise.all([
        api.getProject(id),
        api.getPrompts(),
        api.getProjectActivity(id),
      ]);
      setProject(p);
      setPrompts(ps);
      setActivity(acts);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  // Poll activity every 30 s when that tab is active
  useEffect(() => {
    if (tab !== "activity" || !id) return;
    const interval = setInterval(async () => {
      try {
        const acts = await api.getProjectActivity(id);
        setActivity(acts);
      } catch {
        // ignore polling errors
      }
    }, 30_000);
    return () => clearInterval(interval);
  }, [tab, id]);


  async function assignPrompt(promptTemplateId: string) {
    if (!id || !project) return;
    setSavingPrompt(true);
    try {
      const updated = await api.updateProject(id, { prompt_template_id: promptTemplateId || null });
      setProject(updated);
    } catch (e) {
      alert(String(e));
    } finally {
      setSavingPrompt(false);
    }
  }

  async function handleDeleteFeature(featureId: string) {
    try {
      await api.deleteFeature(featureId);
      setConfirmDelete(null);
      await load();
    } catch (e) {
      alert(String(e));
    }
  }

  async function handleDeleteProject() {
    if (!id) return;
    try {
      await api.deleteProject(id);
      navigate("/projects");
    } catch (e) {
      alert(String(e));
    }
  }

  if (loading) return <div className="text-lcars-muted font-mono text-sm animate-pulse p-4">── RETRIEVING DATA ──</div>;
  if (error) return <div className="text-lcars-red font-mono text-sm p-4">{error}</div>;
  if (!project) return <div className="text-lcars-red font-mono text-sm p-4">PROJECT NOT FOUND</div>;

  const p = project;
  const features: Feature[] = p.features ?? [];

  const tabs: { key: Tab; label: string }[] = [
    { key: "features", label: `FEATURES (${features.length})` },
    { key: "activity", label: `ACTIVITY (${activity.length})` },
    { key: "costs", label: "COSTS" },
  ];

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <Link to="/projects" className="text-lcars-cyan hover:text-lcars-amber font-mono text-xs tracking-widest transition-colors">
          ◂ MISSION REGISTRY
        </Link>
        <div className="flex items-start justify-between mt-3">
          <div className="flex items-center gap-3">
            <div className="w-1 h-6 bg-lcars-orange" />
            <h1 className="text-lcars-orange font-mono text-xs tracking-[0.3em] uppercase">{p.name}</h1>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {confirmDeleteProject ? (
              <>
                <span className="text-xs font-mono text-lcars-muted tracking-widest">CONFIRM DELETION?</span>
                <button
                  onClick={handleDeleteProject}
                  className="text-xs font-mono bg-lcars-red text-white px-2 py-1 hover:opacity-80"
                >
                  CONFIRM
                </button>
                <button
                  onClick={() => setConfirmDeleteProject(false)}
                  className="text-xs font-mono text-lcars-muted hover:text-lcars-text"
                >
                  ABORT
                </button>
              </>
            ) : (
              <button
                onClick={() => setConfirmDeleteProject(true)}
                className="text-xs text-lcars-border hover:text-lcars-red px-1 transition-colors"
              >
                ✕ DELETE
              </button>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 mt-2">
          <StatusBadge status={p.status} />
          <span className="text-lcars-muted font-mono text-xs">{formatDate(p.created_at)}</span>
          {p.total_cost_usd !== undefined && (
            <span className="text-lcars-green font-mono text-xs">{formatCurrency(p.total_cost_usd)}</span>
          )}
        </div>
        {p.description && <p className="text-lcars-muted text-sm mt-2">{p.description}</p>}

        {/* Persona assignment */}
        <div className="mt-4 flex items-center gap-3">
          <label className="text-xs font-mono tracking-widest text-lcars-muted uppercase">Persona:</label>
          <select
            className="bg-lcars-panel border border-lcars-border text-lcars-text font-mono text-xs px-3 py-1.5 focus:outline-none focus:border-lcars-orange"
            value={p.prompt_template_id ?? ""}
            onChange={(e) => assignPrompt(e.target.value)}
            disabled={savingPrompt}
          >
            <option value="">None (default)</option>
            {prompts.map((pt) => (
              <option key={pt.id} value={pt.id}>{pt.name}</option>
            ))}
          </select>
          {savingPrompt && <span className="text-xs font-mono text-lcars-muted animate-pulse">SAVING...</span>}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-0 border-b border-lcars-border">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-xs font-mono font-bold tracking-widest border-b-2 transition-colors ${
              tab === t.key
                ? "border-lcars-orange text-lcars-orange"
                : "border-transparent text-lcars-muted hover:text-lcars-cyan"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "features" && (
        <div className="space-y-3">
          {features.length === 0 && (
            <div className="text-lcars-muted font-mono text-sm p-4">
              NO FEATURES ON RECORD — USE /START-FEATURE IN THE DISCORD PROJECT THREAD
            </div>
          )}
          {features.map((f) => (
            <div key={f.feature_id} className="bg-lcars-panel border border-lcars-border p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-lcars-cyan font-medium">{f.name}</span>
                    <StatusBadge status={f.status} />
                    {f.git_branch && (
                      <span className="text-xs font-mono bg-lcars-border/40 text-lcars-muted px-1.5 py-0.5">
                        {f.git_branch}
                      </span>
                    )}
                  </div>
                  {f.description && (
                    <p className="text-sm text-lcars-muted mt-1">{f.description}</p>
                  )}
                  {f.summary && (
                    <p className="text-sm text-lcars-muted mt-1 italic">{f.summary}</p>
                  )}
                  <div className="flex items-center gap-3 text-xs font-mono text-lcars-muted mt-2">
                    {f.total_cost_usd > 0 && (
                      <span className="text-lcars-green">{formatCurrency(f.total_cost_usd)}</span>
                    )}
                    {f.subdir && <span>in {f.subdir}/</span>}
                    <span>{formatDate(f.created_at)}</span>
                    {f.completed_at && <span>→ {formatDate(f.completed_at)}</span>}
                  </div>
                </div>
                <div className="shrink-0">
                  {confirmDelete === f.feature_id ? (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleDeleteFeature(f.feature_id)}
                        className="text-xs font-mono bg-lcars-red text-white px-2 py-1 hover:opacity-80"
                      >
                        CONFIRM
                      </button>
                      <button
                        onClick={() => setConfirmDelete(null)}
                        className="text-xs font-mono text-lcars-muted hover:text-lcars-text"
                      >
                        ABORT
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setConfirmDelete(f.feature_id)}
                      className="text-xs text-lcars-border hover:text-lcars-red px-1 transition-colors"
                    >
                      ✕
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === "activity" && (
        <div className="space-y-2">
          {activity.length > 0 && (
            <div className="flex items-center gap-2 px-1 pb-1 border-b border-lcars-border">
              <span className="text-xs font-mono font-bold text-lcars-accent tracking-widest uppercase">&#8595; Most Recent First</span>
            </div>
          )}
          {activity.length === 0 && (
            <div className="text-lcars-muted font-mono text-sm p-4">
              NO ACTIVITY IN THE LAST 24 HOURS — MESSAGES APPEAR HERE ONCE THE BOT IS ACTIVE
            </div>
          )}
          {[...activity].reverse().map((entry) => {
            const isUser = entry.role === "user";
            return (
              <div
                key={entry.activity_id}
                className={`flex gap-3 ${isUser ? "" : "flex-row-reverse"}`}
              >
                {/* Avatar */}
                <div
                  className={`w-8 h-8 flex items-center justify-center text-xs font-mono font-bold shrink-0 ${
                    isUser
                      ? "bg-lcars-blue/20 border border-lcars-blue text-lcars-blue"
                      : "bg-lcars-purple/20 border border-lcars-purple text-lcars-purple"
                  }`}
                >
                  {isUser ? entry.author.slice(0, 2).toUpperCase() : "AI"}
                </div>

                {/* Bubble */}
                <div className={`max-w-[75%] ${isUser ? "" : "items-end flex flex-col"}`}>
                  <div className="flex items-baseline gap-2 mb-1">
                    <span className="text-xs font-mono text-lcars-muted">{entry.author}</span>
                    {entry.feature_name && (
                      <span className="text-xs font-mono text-lcars-amber">{entry.feature_name}</span>
                    )}
                    <span className="text-xs font-mono text-lcars-muted">{formatDate(entry.created_at)}</span>
                  </div>
                  <div
                    className={`px-3 py-2 text-sm whitespace-pre-wrap break-words border ${
                      isUser
                        ? "bg-lcars-panel border-lcars-border text-lcars-text"
                        : "bg-lcars-purple/10 border-lcars-purple/30 text-lcars-text"
                    }`}
                  >
                    {entry.content.length > 500
                      ? entry.content.slice(0, 500) + "…"
                      : entry.content}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {tab === "costs" && (
        <LcarsPanel label="Resource Expenditure">
          <div className="text-4xl font-mono text-lcars-amber">
            {formatCurrency(p.total_cost_usd ?? 0)}
          </div>
          <div className="text-lcars-muted font-mono text-xs mt-1">total project cost</div>
        </LcarsPanel>
      )}
    </div>
  );
}
