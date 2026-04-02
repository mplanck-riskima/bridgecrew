import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import MemoryInspector from "@/components/MemoryInspector";
import { api } from "@/lib/api";

type MemoryType = "short-term" | "long-term" | "search";

export default function Memory() {
  const [type, setType] = useState<MemoryType>("short-term");
  const [agent, setAgent] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  const agents = useQuery({ queryKey: ["agents"], queryFn: api.getAgents });

  const shortTerm = useQuery({
    queryKey: ["shortTerm", agent],
    queryFn: () => {
      const params: Record<string, string> = {};
      if (agent) {
        params.agent = agent;
      }
      return api.getShortTermMemories(params);
    },
    enabled: type === "short-term",
  });

  const longTerm = useQuery({
    queryKey: ["longTerm", agent],
    queryFn: () => {
      const params: Record<string, string> = {};
      if (agent) {
        params.agent = agent;
      }
      return api.getLongTermMemories(params);
    },
    enabled: type === "long-term",
  });

  const search = useQuery({
    queryKey: ["memorySearch", searchQuery],
    queryFn: () => api.searchMemories(searchQuery),
    enabled: type === "search" && searchQuery.length > 0,
  });

  const items =
    type === "short-term"
      ? (shortTerm.data?.items ?? [])
      : type === "long-term"
        ? (longTerm.data?.items ?? [])
        : (search.data?.items ?? []);

  const isLoading =
    type === "short-term"
      ? shortTerm.isLoading
      : type === "long-term"
        ? longTerm.isLoading
        : search.isLoading;

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Memory</h1>

      {/* Filters */}
      <div className="flex items-center gap-4 mb-4">
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
          {(["short-term", "long-term", "search"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setType(t)}
              className={`px-3 py-1 text-sm rounded ${
                type === t
                  ? "bg-white shadow font-medium"
                  : "text-gray-600 hover:text-gray-800"
              }`}
            >
              {t === "short-term"
                ? "Short-term"
                : t === "long-term"
                  ? "Long-term"
                  : "Search"}
            </button>
          ))}
        </div>

        {type !== "search" && (
          <select
            value={agent}
            onChange={(e) => setAgent(e.target.value)}
            className="border rounded px-2 py-1 text-sm"
          >
            <option value="">All agents</option>
            {agents.data?.map((a) => (
              <option key={a.persona_name} value={a.persona_name}>
                {a.persona_name}
              </option>
            ))}
          </select>
        )}

        {type === "search" && (
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search memories..."
            className="border rounded px-3 py-1 text-sm flex-1 max-w-md"
          />
        )}
      </div>

      {/* Results */}
      {isLoading ? (
        <div className="text-gray-400">Loading...</div>
      ) : (
        <MemoryInspector items={items as Record<string, unknown>[]} />
      )}
    </div>
  );
}
