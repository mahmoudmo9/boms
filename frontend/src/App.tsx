import { type ComponentType, lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, Route, Routes } from "react-router";

import { Loading } from "./design/components";
import { useAuth } from "./lib/auth";
import { WORKSPACES } from "./lib/nav";
import { LockScreen, LoginPage, NoUserPage } from "./pages/LoginPage";
import { NotFoundPage, PlaceholderPage } from "./pages/PlaceholderPage";
import { devMode } from "./pages/system/devMode";
import { AppShell } from "./shell/AppShell";

/** v0.10.1 section 0.3.4: every page is its own chunk, loaded when its route is opened (the login, lock and shell
 * stay in the first load). */
function page<K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K) {
  return lazy(() => load().then((m) => ({ default: m[name] })));
}
const BaseDataPage = page(() => import("./pages/basedata/BaseDataPage"), "BaseDataPage");
const DocumentDetailPage = page(() => import("./pages/documents/DocumentDetailPage"), "DocumentDetailPage");
const DocumentsPage = page(() => import("./pages/documents/DocumentsPage"), "DocumentsPage");
const EventLogPage = page(() => import("./pages/events/EventLogPage"), "EventLogPage");
const CommandCenterPage = page(() => import("./pages/parties/CommandCenterPage"), "CommandCenterPage");
const FunnelsPage = page(() => import("./pages/parties/FunnelsPage"), "FunnelsPage");
const PartiesPage = page(() => import("./pages/parties/PartiesPage"), "PartiesPage");
const PartyDetailPage = page(() => import("./pages/parties/PartyDetailPage"), "PartyDetailPage");
const CaseDetailPage = page(() => import("./pages/cases/CaseDetailPage"), "CaseDetailPage");
const CasesPage = page(() => import("./pages/cases/CasesPage"), "CasesPage");
const SettingsPage = page(() => import("./pages/settings/SettingsPage"), "SettingsPage");
const CostingSettingsPage = page(() => import("./pages/settings/CostingSettingsPage"), "CostingSettingsPage");
const LetterheadPage = page(() => import("./pages/settings/LetterheadPage"), "LetterheadPage");
const SetadSettingsPage = page(() => import("./pages/settings/SetadSettingsPage"), "SetadSettingsPage");
const TendersSettingsPage = page(() => import("./pages/settings/TendersSettingsPage"), "TendersSettingsPage");
const CompanyDocumentsPage = page(() => import("./pages/settings/CompanyDocumentsPage"), "CompanyDocumentsPage");
const ExecutionSettingsPage = page(() => import("./pages/settings/ExecutionSettingsPage"), "ExecutionSettingsPage");
const AiSettingsPage = page(() => import("./pages/settings/AiSettingsPage"), "AiSettingsPage");
const CodingSettingsPage = page(() => import("./pages/settings/CodingSettingsPage"), "CodingSettingsPage");
const ReferenceDataPage = page(() => import("./pages/settings/ReferenceDataPage"), "ReferenceDataPage");
const VerifyDocumentPage = page(() => import("./pages/documents/VerifyDocumentPage"), "VerifyDocumentPage");
const ExecutionPage = page(() => import("./pages/cases/ExecutionPage"), "ExecutionPage");
const GuaranteesPage = page(() => import("./pages/cases/GuaranteesPage"), "GuaranteesPage");
const CatalogPage = page(() => import("./pages/sourcing/CatalogPage"), "CatalogPage");
const ProductPage = page(() => import("./pages/sourcing/CatalogPage"), "ProductPage");
const InquiriesPage = page(() => import("./pages/sourcing/InquiriesPage"), "InquiriesPage");
const InquiryDetailPage = page(() => import("./pages/sourcing/InquiryDetailPage"), "InquiryDetailPage");
const TemplatesPage = page(() => import("./pages/sourcing/TemplatesPage"), "TemplatesPage");
const SystemPage = page(() => import("./pages/system/SystemPage"), "SystemPage");
const DesignPage = page(() => import("./pages/system/DesignPage"), "DesignPage");
const ListingsPage = page(() => import("./pages/tenders/ListingsPage"), "ListingsPage");
const TriagePage = page(() => import("./pages/tenders/TriagePage"), "TriagePage");
const TasksPage = page(() => import("./pages/tasks/TasksPage"), "TasksPage");
const FinancePage = page(() => import("./pages/finance/FinancePage"), "FinancePage");


/** `/design` exists only in developer mode (Settings → System); the switch is read when the route renders. */
function DesignRoute() {
  return devMode() ? <DesignPage /> : <NotFoundPage />;
}

export function App() {
  const { status } = useAuth();
  if (status === "loading") return <Loading />;
  if (status === "error") return <NoBackend />;
  if (status === "nouser") return <NoUserPage />;
  if (status === "anon") return <LoginPage />;
  if (status === "locked") return <LockScreen />;

  return (
    <Suspense fallback={<Loading />}>
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/documents" replace />} />
        {WORKSPACES.filter((w) => w.phase).map((w) => (
          <Route key={w.key} path={w.path.slice(1)} element={<PlaceholderPage workspace={w} />} />
        ))}
        <Route path="command-center" element={<CommandCenterPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="finance" element={<FinancePage />} />
        <Route path="tenders" element={<ListingsPage />} />
        <Route path="tenders/triage" element={<TriagePage />} />
        <Route path="parties" element={<PartiesPage />} />
        <Route path="parties/funnels" element={<FunnelsPage />} />
        <Route path="parties/:id" element={<PartyDetailPage />} />
        <Route path="sourcing" element={<InquiriesPage />} />
        <Route path="sourcing/inquiries/:id" element={<InquiryDetailPage />} />
        <Route path="sourcing/catalog" element={<CatalogPage />} />
        <Route path="sourcing/catalog/:id" element={<ProductPage />} />
        <Route path="sourcing/templates" element={<TemplatesPage />} />
        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/guarantees" element={<GuaranteesPage />} />
        <Route path="cases/:id" element={<CaseDetailPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="documents/verify" element={<VerifyDocumentPage />} />
        <Route path="documents/:id" element={<DocumentDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/basedata" element={<Navigate to="/settings/basedata/countries" replace />} />
        <Route path="settings/basedata/:kind" element={<BaseDataPage />} />
        <Route path="settings/events" element={<EventLogPage />} />
        <Route path="settings/system" element={<SystemPage />} />
        <Route path="design" element={<DesignRoute />} />
        <Route path="settings/costing" element={<CostingSettingsPage />} />
        <Route path="settings/letterhead" element={<LetterheadPage />} />
        <Route path="settings/setad" element={<SetadSettingsPage />} />
        <Route path="settings/tenders" element={<TendersSettingsPage />} />
        <Route path="settings/company-documents" element={<CompanyDocumentsPage />} />
        <Route path="settings/execution" element={<ExecutionSettingsPage />} />
        <Route path="settings/ai" element={<AiSettingsPage />} />
        <Route path="settings/coding" element={<CodingSettingsPage />} />
        <Route path="settings/reference" element={<ReferenceDataPage />} />
        <Route path="execution" element={<ExecutionPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
    </Suspense>
  );
}

function NoBackend() {
  const { t } = useTranslation();
  return <div className="p-8 text-center text-sm text-danger">{t("errors.backendDown")}</div>;
}
