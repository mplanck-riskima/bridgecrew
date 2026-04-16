import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import ProjectForm from "@/components/ProjectForm";
import StatusBadge from "@/components/StatusBadge";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export default function Projects() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: api.getProjects,
  });

  const createMutation = useMutation({
    mutationFn: api.createProject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      setShowForm(false);
    },
  });

  return (
    <div className="space-y-3 md:space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-1 h-6 bg-lcars-orange" />
          <h1 className="text-lcars-orange font-mono text-xs tracking-[0.3em] uppercase">
            Mission Registry
          </h1>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="px-4 py-1.5 text-xs font-mono font-bold tracking-widest uppercase bg-lcars-orange text-black hover:bg-lcars-amber transition-colors"
        >
          + New Mission
        </button>
      </div>

      {showForm && (
        <ProjectForm
          onSubmit={(data) => createMutation.mutate(data)}
          onCancel={() => setShowForm(false)}
        />
      )}

      {projects.isLoading ? (
        <div className="text-lcars-muted font-mono text-sm animate-pulse p-4">── RETRIEVING DATA ──</div>
      ) : (
        <div className="bg-lcars-panel border border-lcars-border overflow-hidden">
          {/* Header row */}
          <div className="hidden md:grid grid-cols-[1fr_auto_auto_auto_auto] gap-4 px-4 py-2 bg-lcars-border/40 border-b border-lcars-border">
            {["DESIGNATION", "STATUS", "FEATURES", "STARDATE", "DESCRIPTION"].map((h) => (
              <span key={h} className="text-lcars-muted font-mono text-xs tracking-widest">{h}</span>
            ))}
          </div>
          {projects.data?.length === 0 && (
            <div className="px-4 py-8 text-center text-lcars-muted font-mono text-sm">
              NO MISSIONS ON RECORD
            </div>
          )}
          {projects.data?.map((project) => (
            <Link
              key={project.project_id}
              to={`/projects/${encodeURIComponent(project.name)}`}
              className="grid grid-cols-[1fr_auto] md:grid-cols-[1fr_auto_auto_auto_auto] gap-2 md:gap-4 items-center px-4 py-3 border-b border-lcars-border/50 last:border-0 hover:bg-lcars-border/20 transition-colors group"
            >
              <span className="text-lcars-cyan group-hover:text-lcars-amber font-medium transition-colors truncate">
                {project.name}
              </span>
              <StatusBadge status={project.status} />
              <span className="hidden md:inline text-lcars-amber font-mono text-sm">{project.feature_count ?? 0}</span>
              <span className="hidden md:inline text-lcars-muted font-mono text-xs">{formatDate(project.created_at)}</span>
              <span className="hidden md:inline text-lcars-muted text-sm truncate max-w-48">{project.description}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
