import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import ActivityFeed from "@/components/ActivityFeed";
import AgentCard from "@/components/AgentCard";
import { api } from "@/lib/api";

export default function Agents() {
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.getAgents });
  const [selected, setSelected] = useState<string | null>(null);

  const activity = useQuery({
    queryKey: ["agentActivity", selected],
    queryFn: () => api.getAgentActivity(selected!, 30),
    enabled: selected !== null,
  });

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Agents</h1>

      {agents.isLoading ? (
        <div className="text-gray-400">Loading...</div>
      ) : (
        <div className="grid grid-cols-3 gap-4 mb-6">
          {agents.data?.map((agent) => (
            <div
              key={agent.persona_name}
              className={`cursor-pointer rounded-lg ${
                selected === agent.persona_name
                  ? "ring-2 ring-blue-500"
                  : ""
              }`}
              onClick={() =>
                setSelected(
                  selected === agent.persona_name
                    ? null
                    : agent.persona_name,
                )
              }
            >
              <AgentCard agent={agent} />
            </div>
          ))}
        </div>
      )}

      {selected && (
        <div>
          <h2 className="text-lg font-semibold mb-3">
            Activity: {selected}
          </h2>
          <div className="bg-white rounded-lg border p-4 max-h-96 overflow-auto">
            {activity.isLoading ? (
              <div className="text-gray-400">Loading...</div>
            ) : (
              <ActivityFeed
                items={(activity.data ?? []) as unknown as Record<string, unknown>[]}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
