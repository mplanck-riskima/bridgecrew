import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import PersonaEditor from "@/components/PersonaEditor";
import StatusBadge from "@/components/StatusBadge";
import { api } from "@/lib/api";

export default function Personas() {
  const personas = useQuery({
    queryKey: ["personas"],
    queryFn: api.getPersonas,
  });
  const [selected, setSelected] = useState<string | null>(null);

  const selectedPersona = personas.data?.find(
    (p) => p.persona_name === selected,
  );

  // Auto-select first persona.
  if (!selected && personas.data && personas.data.length > 0) {
    setSelected(personas.data[0]!.persona_name);
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">Personas</h1>

      <div className="flex gap-6">
        {/* Sidebar */}
        <div className="w-56 shrink-0 space-y-1">
          {personas.isLoading ? (
            <div className="text-gray-400">Loading...</div>
          ) : (
            personas.data?.map((p) => (
              <button
                key={p.persona_name}
                onClick={() => setSelected(p.persona_name)}
                className={`w-full text-left px-3 py-2 rounded text-sm flex items-center justify-between ${
                  selected === p.persona_name
                    ? "bg-blue-50 text-blue-700 font-medium"
                    : "hover:bg-gray-100 text-gray-700"
                }`}
              >
                <span>{p.persona_name}</span>
                <StatusBadge status={p.enabled ? "active" : "archived"} />
              </button>
            ))
          )}
        </div>

        {/* Editor */}
        <div className="flex-1 bg-white rounded-lg border p-6">
          {selectedPersona ? (
            <PersonaEditor persona={selectedPersona} />
          ) : (
            <div className="text-gray-400">Select a persona</div>
          )}
        </div>
      </div>
    </div>
  );
}
