/** The 12 workspaces, in sidebar order. ``phase`` set = not built yet (placeholder page). */
export interface Workspace {
  key: string;
  path: string;
  icon: string;
  phase?: string;
  children?: { key: string; path: string }[];
}

export const WORKSPACES: Workspace[] = [
  {
    key: "commandCenter",
    path: "/command-center",
    icon: "gauge",
    children: [
      { key: "commandCenterHome", path: "/command-center" },
      { key: "myTasks", path: "/tasks" },
    ],
  },
  { key: "market", path: "/market", icon: "globe", phase: "2" },
  {
    key: "parties",
    path: "/parties",
    icon: "users",
    children: [
      { key: "partiesList", path: "/parties" },
      { key: "funnels", path: "/parties/funnels" },
    ],
  },
  { key: "outreach", path: "/outreach", icon: "megaphone", phase: "4" },
  {
    key: "sourcing",
    path: "/sourcing",
    icon: "search",
    children: [
      { key: "inquiries", path: "/sourcing" },
      { key: "catalog", path: "/sourcing/catalog" },
      { key: "templates", path: "/sourcing/templates" },
    ],
  },
  {
    key: "cases",
    path: "/cases",
    icon: "folder",
    children: [
      { key: "casesList", path: "/cases" },
      { key: "guarantees", path: "/cases/guarantees" },
    ],
  },
  { key: "tenders", path: "/tenders", icon: "gavel" },
  { key: "execution", path: "/execution", icon: "truck" },
  { key: "finance", path: "/finance", icon: "coins" },
  {
    key: "documents",
    path: "/documents",
    icon: "file",
    children: [
      { key: "documentsList", path: "/documents" },
      { key: "verifyDocument", path: "/documents/verify" },
    ],
  },
  { key: "reports", path: "/reports", icon: "chart", phase: "10" },
  {
    key: "settings",
    path: "/settings",
    icon: "settings",
    children: [
      { key: "general", path: "/settings" },
      { key: "costing", path: "/settings/costing" },
      { key: "letterhead", path: "/settings/letterhead" },
      { key: "setad", path: "/settings/setad" },
      { key: "tenderSettings", path: "/settings/tenders" },
      { key: "companyDocuments", path: "/settings/company-documents" },
      { key: "executionSettings", path: "/settings/execution" },
      { key: "aiSettings", path: "/settings/ai" },
      { key: "codingSettings", path: "/settings/coding" },
      { key: "referenceData", path: "/settings/reference" },
      { key: "basedata", path: "/settings/basedata/countries" },
      { key: "events", path: "/settings/events" },
      { key: "system", path: "/settings/system" },
    ],
  },
];
