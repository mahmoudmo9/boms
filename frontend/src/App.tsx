import { useTranslation } from "react-i18next";
import { Navigate, Route, Routes } from "react-router";

import { Loading } from "./components/ui";
import { useAuth } from "./lib/auth";
import { WORKSPACES } from "./lib/nav";
import { BaseDataPage } from "./pages/basedata/BaseDataPage";
import { DocumentDetailPage } from "./pages/documents/DocumentDetailPage";
import { DocumentsPage } from "./pages/documents/DocumentsPage";
import { EventLogPage } from "./pages/events/EventLogPage";
import { LockScreen, LoginPage, NoUserPage } from "./pages/LoginPage";
import { CommandCenterPage } from "./pages/parties/CommandCenterPage";
import { FunnelsPage } from "./pages/parties/FunnelsPage";
import { PartiesPage } from "./pages/parties/PartiesPage";
import { PartyDetailPage } from "./pages/parties/PartyDetailPage";
import { CaseDetailPage } from "./pages/cases/CaseDetailPage";
import { CasesPage } from "./pages/cases/CasesPage";
import { NotFoundPage, PlaceholderPage } from "./pages/PlaceholderPage";
import { SettingsPage } from "./pages/settings/SettingsPage";
import { CostingSettingsPage } from "./pages/settings/CostingSettingsPage";
import { LetterheadPage } from "./pages/settings/LetterheadPage";
import { CatalogPage, ProductPage } from "./pages/sourcing/CatalogPage";
import { InquiriesPage } from "./pages/sourcing/InquiriesPage";
import { InquiryDetailPage } from "./pages/sourcing/InquiryDetailPage";
import { TemplatesPage } from "./pages/sourcing/TemplatesPage";
import { SystemPage } from "./pages/system/SystemPage";
import { AppShell } from "./shell/AppShell";

export function App() {
  const { status } = useAuth();
  if (status === "loading") return <Loading />;
  if (status === "error") return <NoBackend />;
  if (status === "nouser") return <NoUserPage />;
  if (status === "anon") return <LoginPage />;
  if (status === "locked") return <LockScreen />;

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/documents" replace />} />
        {WORKSPACES.filter((w) => w.phase).map((w) => (
          <Route key={w.key} path={w.path.slice(1)} element={<PlaceholderPage workspace={w} />} />
        ))}
        <Route path="command-center" element={<CommandCenterPage />} />
        <Route path="parties" element={<PartiesPage />} />
        <Route path="parties/funnels" element={<FunnelsPage />} />
        <Route path="parties/:id" element={<PartyDetailPage />} />
        <Route path="sourcing" element={<InquiriesPage />} />
        <Route path="sourcing/inquiries/:id" element={<InquiryDetailPage />} />
        <Route path="sourcing/catalog" element={<CatalogPage />} />
        <Route path="sourcing/catalog/:id" element={<ProductPage />} />
        <Route path="sourcing/templates" element={<TemplatesPage />} />
        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/:id" element={<CaseDetailPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="documents/:id" element={<DocumentDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/basedata" element={<Navigate to="/settings/basedata/countries" replace />} />
        <Route path="settings/basedata/:kind" element={<BaseDataPage />} />
        <Route path="settings/events" element={<EventLogPage />} />
        <Route path="settings/system" element={<SystemPage />} />
        <Route path="settings/costing" element={<CostingSettingsPage />} />
        <Route path="settings/letterhead" element={<LetterheadPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

function NoBackend() {
  const { t } = useTranslation();
  return <div className="p-8 text-center text-sm text-danger">{t("errors.backendDown")}</div>;
}
