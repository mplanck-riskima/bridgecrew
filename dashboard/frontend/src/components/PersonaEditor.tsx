import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { PersonaDefinition } from "@/lib/types";
import { api } from "@/lib/api";

const MODELS = [
  "claude-opus-4-6",
  "claude-sonnet-4-5-20250929",
  "claude-haiku-4-5-20251001",
];

const ALL_TOOLS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"];

interface Props {
  persona: PersonaDefinition;
}

export default function PersonaEditor({ persona }: Props) {
  const queryClient = useQueryClient();
  const [prompt, setPrompt] = useState(persona.system_prompt);
  const [model, setModel] = useState(persona.model);
  const [tools, setTools] = useState<string[]>(persona.allowed_tools);
  const [budget, setBudget] = useState(String(persona.max_budget_usd));
  const [enabled, setEnabled] = useState(persona.enabled);

  // Sync state when persona selection changes.
  useEffect(() => {
    setPrompt(persona.system_prompt);
    setModel(persona.model);
    setTools(persona.allowed_tools);
    setBudget(String(persona.max_budget_usd));
    setEnabled(persona.enabled);
  }, [persona]);

  const updateMutation = useMutation({
    mutationFn: (data: Partial<PersonaDefinition>) =>
      api.updatePersona(persona.persona_name, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["personas"] });
    },
  });

  const resetMutation = useMutation({
    mutationFn: () => api.resetPersona(persona.persona_name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["personas"] });
    },
  });

  function handleSave() {
    updateMutation.mutate({
      system_prompt: prompt,
      model,
      allowed_tools: tools,
      max_budget_usd: parseFloat(budget) || 2.0,
      enabled,
    });
  }

  function toggleTool(tool: string) {
    setTools((prev) =>
      prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool],
    );
  }

  const isDirty =
    prompt !== persona.system_prompt ||
    model !== persona.model ||
    JSON.stringify(tools) !== JSON.stringify(persona.allowed_tools) ||
    parseFloat(budget) !== persona.max_budget_usd ||
    enabled !== persona.enabled;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{persona.persona_name}</h2>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            Enabled
          </label>
        </div>
      </div>

      {/* Model */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Model
        </label>
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="border rounded px-2 py-1 text-sm w-full"
        >
          {MODELS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>

      {/* Tools */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Allowed Tools
        </label>
        <div className="flex flex-wrap gap-2">
          {ALL_TOOLS.map((tool) => (
            <label key={tool} className="flex items-center gap-1 text-sm">
              <input
                type="checkbox"
                checked={tools.includes(tool)}
                onChange={() => toggleTool(tool)}
              />
              {tool}
            </label>
          ))}
        </div>
      </div>

      {/* Budget */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Max Budget (USD)
        </label>
        <input
          type="number"
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
          step="0.50"
          min="0"
          className="border rounded px-2 py-1 text-sm w-32"
        />
      </div>

      {/* System prompt */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          System Prompt
        </label>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={16}
          className="w-full border rounded px-3 py-2 text-sm font-mono"
        />
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={!isDirty || updateMutation.isPending}
          className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {updateMutation.isPending ? "Saving..." : "Save Changes"}
        </button>
        <button
          onClick={() => resetMutation.mutate()}
          disabled={resetMutation.isPending}
          className="px-3 py-1.5 text-sm text-red-600 border border-red-300 rounded hover:bg-red-50"
        >
          Reset to Defaults
        </button>
        {updateMutation.isSuccess && (
          <span className="text-sm text-green-600">Saved</span>
        )}
      </div>
    </div>
  );
}
