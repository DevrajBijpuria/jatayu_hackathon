// Plain-language access levels. Keys are the Keycloak access groups (GROUP_TO_ACCESS on the API).
export const ACCESS_GROUPS = [
  { group: "tg-employees", label: "Employee", canSee: "everyday policies" },
  { group: "tg-compliance", label: "Compliance", canSee: "everyday policies + compliance documents" },
  { group: "tg-board", label: "Board", canSee: "everyday policies + compliance documents + board documents" },
] as const;

export function accessGroupInfo(group: string | null) {
  return ACCESS_GROUPS.find((a) => a.group === group) ?? null;
}

// For the header: name the highest level in the user's access_levels from /me.
export function accessLabel(levels: string[]): string {
  if (levels.includes("board")) return "Board";
  if (levels.includes("compliance")) return "Compliance";
  if (levels.includes("all")) return "Employee";
  return "No document access";
}
