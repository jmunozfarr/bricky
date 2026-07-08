const STORAGE_PREFIX = "bricky:builder-steps:";

/**
 * Per-model builder progress: the last selected step for every build task
 * (occurrence) the user visited. Storage failures (private browsing, quota)
 * degrade to in-session memory only.
 */
export function loadStepMemory(modelId: string): Map<string, number> {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + modelId);
    if (raw === null) return new Map();
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return new Map();
    const entries = Object.entries(parsed).filter(
      (entry): entry is [string, number] =>
        typeof entry[1] === "number" && Number.isInteger(entry[1]) && entry[1] >= 1,
    );
    return new Map(entries);
  } catch {
    return new Map();
  }
}

export function saveStepMemory(modelId: string, steps: Map<string, number>): void {
  try {
    window.localStorage.setItem(
      STORAGE_PREFIX + modelId,
      JSON.stringify(Object.fromEntries(steps)),
    );
  } catch {
    // Progress persistence is best-effort.
  }
}
