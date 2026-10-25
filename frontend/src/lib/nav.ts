/** The 12 workspaces, in sidebar order. ``phase`` set = not built yet (placeholder page). */
export interface Workspace {
  key: string;
  path: string;
  icon: string;
  phase?: string;
  children?: { key: string; path: string }[];
}

export const WORKSPACES: Workspace[] = [
  { key: "commandCenter", path: "/command-center", icon: "gauge", phase: "3" },
  { key: "market", path: "/market", icon: "globe", phase: "2" },
  { key: "parties", path: "/parties", icon: "users", phase: "3" },
  { key: "outreach", path: "/outreach", icon: "megaphone", phase: "4" },
  { key: "sourcing", path: "/sourcing", icon: "search", phase: "5" },
  { key: "cases", path: "/cases", icon: "folder", phase: "5–6" },
  { key: "tenders", path: "/tenders", icon: "gavel", phase: "7" },
  { key: "execution", path: "/execution", icon: "truck", phase: "8" },
  { key: "finance", path: "/finance", icon: "coins", phase: "9" },
  { key: "documents", path: "/documents", icon: "file" },
  { key: "reports", path: "/reports", icon: "chart", phase: "10" },
  {
    key: "settings",
    path: "/settings",
    icon: "settings",
    children: [
      { key: "general", path: "/settings" },
      { key: "basedata", path: "/settings/basedata/countries" },
      { key: "events", path: "/settings/events" },
      { key: "system", path: "/settings/system" },
    ],
  },
];
