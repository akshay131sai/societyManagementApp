/**
 * Route tree.
 *
 * Every page is `React.lazy`, so a Flat Owner never downloads the platform
 * module, the Bill Builder or the chart library. Only the login screen and the
 * shell are in the entry chunk.
 */

import * as React from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import AppShell from "@/layouts/AppShell";
import {
  FullPageLoader,
  RedirectIfAuthenticated,
  RequireAuth,
  RequirePermission,
  RequireSociety,
  RequireSuperAdmin,
} from "@/routes/guards";
import { useAppSelector } from "@/store";
import { hasPermission, homePathFor } from "@/utils/permissions";

/* --- Auth (small; eager so sign-in never waits on a chunk) ---------------- */
const LoginPage = React.lazy(() => import("@/features/auth/LoginPage"));

/* --- Blocked states ------------------------------------------------------ */
const Blocked = () => import("@/features/auth/BlockedPages");
const SubscriptionExpiredPage = React.lazy(() =>
  Blocked().then((m) => ({ default: m.SubscriptionExpiredPage })),
);
const SocietyLockedPage = React.lazy(() =>
  Blocked().then((m) => ({ default: m.SocietyLockedPage })),
);
const ProvisioningPage = React.lazy(() => Blocked().then((m) => ({ default: m.ProvisioningPage })));
const UnauthorizedPage = React.lazy(() => Blocked().then((m) => ({ default: m.UnauthorizedPage })));
const NotFoundPage = React.lazy(() => Blocked().then((m) => ({ default: m.NotFoundPage })));

/* --- Platform (SUPER_ADMIN only) ----------------------------------------- */
const PlatformDashboard = React.lazy(() => import("@/features/societies/PlatformDashboard"));
const SocietyListPage = React.lazy(() => import("@/features/societies/SocietyListPage"));
const CreateSocietyPage = React.lazy(() => import("@/features/societies/CreateSocietyPage"));
const SocietyDetailPage = React.lazy(() => import("@/features/societies/SocietyDetailPage"));
const PlansPage = React.lazy(() => import("@/features/platform/PlansPage"));
const SubscriptionsPage = React.lazy(() => import("@/features/platform/SubscriptionsPage"));
const PlatformUsersPage = React.lazy(() => import("@/features/platform/PlatformUsersPage"));
const AuditLogsPage = React.lazy(() => import("@/features/platform/AuditLogsPage"));
const PlatformSettingsPage = React.lazy(() => import("@/features/platform/PlatformSettingsPage"));

/* --- Society scope -------------------------------------------------------- */
const SocietyDashboard = React.lazy(() => import("@/features/dashboard/SocietyDashboard"));
const UsersPage = React.lazy(() => import("@/features/dashboard/UsersPage"));
const AppearancePage = React.lazy(() => import("@/features/dashboard/AppearancePage"));
const SettingsPage = React.lazy(() => import("@/features/dashboard/SettingsPage"));
const ProfilePage = React.lazy(() => import("@/features/dashboard/ProfilePage"));

/* --- Structure (Phase 2) -------------------------------------------------- */
const StructurePage = React.lazy(() => import("@/features/structure/StructurePage"));
const FlatsPage = React.lazy(() => import("@/features/structure/FlatsPage"));
const ResidentsPage = React.lazy(() => import("@/features/structure/ResidentsPage"));
const FamilyPage = React.lazy(() => import("@/features/residents/FamilyPage"));

/* --- Billing (Phase 3) ---------------------------------------------------- */
const TemplatesPage = React.lazy(() => import("@/features/billing/TemplatesPage"));
const BillBuilderPage = React.lazy(() => import("@/features/billing/BillBuilderPage"));
const BillsPage = React.lazy(() => import("@/features/billing/BillsPage"));
const PaymentsPage = React.lazy(() => import("@/features/billing/PaymentsPage"));

/* --- Utilities and assets (Phase 4) --------------------------------------- */
const ResidentDashboard = React.lazy(() => import("@/features/dashboard/ResidentDashboard"));
const UtilityPage = React.lazy(() => import("@/features/utilities/UtilityPage"));
const ParkingPage = React.lazy(() => import("@/features/utilities/ParkingPage"));
const VehiclesPage = React.lazy(() => import("@/features/utilities/VehiclesPage"));
const PetsPage = React.lazy(() => import("@/features/utilities/PetsPage"));

/* --- Operations and community (Phase 5) ----------------------------------- */
const ComplaintsPage = React.lazy(() => import("@/features/operations/ComplaintsPage"));
const WorkPage = React.lazy(() => import("@/features/operations/WorkPage"));
const SecurityPage = React.lazy(() => import("@/features/security/SecurityPage"));
const VisitorsPage = React.lazy(() => import("@/features/security/VisitorsPage"));
const NoticesPage = React.lazy(() => import("@/features/community/NoticesPage"));
const AmenitiesPage = React.lazy(() => import("@/features/community/AmenitiesPage"));

/* --- Reports (Phase 6) ---------------------------------------------------- */
const ReportsPage = React.lazy(() => import("@/features/reports/ReportsPage"));

function Suspended({ children }: { children: React.ReactNode }) {
  return <React.Suspense fallback={<FullPageLoader />}>{children}</React.Suspense>;
}

/**
 * A resident's home is not an administrator's home.
 *
 * The split is on capability, not on role: someone who can administer the
 * society sees the society, and someone whose data is scoped to their own
 * flats sees their own flats. A committee member holding both gets the
 * society view, which is the superset.
 */
function DashboardHome() {
  const principal = useAppSelector((s) => s.auth.principal);
  const isResident =
    !hasPermission(principal, "user.read") && (principal?.flat_ids.length ?? 0) > 0;
  return isResident ? <ResidentDashboard /> : <SocietyDashboard />;
}

function RootRedirect() {
  const principal = useAppSelector((s) => s.auth.principal);
  return <Navigate to={homePathFor(principal)} replace />;
}

export default function AppRoutes() {
  return (
    <Suspended>
      <Routes>
        {/* Public */}
        <Route element={<RedirectIfAuthenticated />}>
          <Route path="/login" element={<LoginPage />} />
        </Route>

        {/* Blocked states — reachable while signed in but refused */}
        <Route path="/subscription-expired" element={<SubscriptionExpiredPage />} />
        <Route path="/society-locked" element={<SocietyLockedPage />} />
        <Route path="/provisioning" element={<ProvisioningPage />} />

        {/* Authenticated */}
        <Route element={<RequireAuth />}>
          <Route path="/" element={<RootRedirect />} />

          {/* Platform */}
          <Route element={<RequireSuperAdmin />}>
            <Route path="/admin" element={<AppShell />}>
              <Route index element={<Navigate to="/admin/dashboard" replace />} />
              <Route path="dashboard" element={<PlatformDashboard />} />
              <Route path="societies" element={<SocietyListPage />} />
              <Route path="societies/new" element={<CreateSocietyPage />} />
              <Route path="societies/:societyId" element={<SocietyDetailPage />} />
              {/* The platform API guards these itself; a SUPER_ADMIN holds every
                  platform permission, so the route guard above is sufficient. */}
              <Route path="plans" element={<PlansPage />} />
              <Route path="subscriptions" element={<SubscriptionsPage />} />
              <Route path="users" element={<PlatformUsersPage />} />
              <Route path="audit-logs" element={<AuditLogsPage />} />
              <Route path="settings" element={<PlatformSettingsPage />} />
              <Route path="unauthorized" element={<UnauthorizedPage />} />
            </Route>
          </Route>

          {/* Society */}
          <Route element={<RequireSociety />}>
            <Route path="/app" element={<AppShell />}>
              <Route index element={<Navigate to="/app/dashboard" replace />} />
              <Route path="dashboard" element={<DashboardHome />} />
              <Route path="profile" element={<ProfilePage />} />

              <Route
                path="buildings"
                element={
                  <RequirePermission permission="building.read">
                    <StructurePage />
                  </RequirePermission>
                }
              />
              {/* Blocks and floors are managed inside Structure, not as
                  separate screens; these keep old links working. */}
              <Route path="blocks" element={<Navigate to="/app/buildings" replace />} />
              <Route path="floors" element={<Navigate to="/app/buildings" replace />} />
              <Route
                path="flats"
                element={
                  <RequirePermission permission="flat.read">
                    <FlatsPage />
                  </RequirePermission>
                }
              />
              <Route
                path="residents"
                element={
                  <RequirePermission permission="resident.read">
                    <ResidentsPage />
                  </RequirePermission>
                }
              />
              <Route
                path="family"
                element={
                  <RequirePermission permission="family.manage">
                    <FamilyPage />
                  </RequirePermission>
                }
              />
              <Route
                path="bill-templates"
                element={
                  <RequirePermission permission="billing.manage_template">
                    <TemplatesPage />
                  </RequirePermission>
                }
              />
              <Route
                path="bill-builder"
                element={
                  <RequirePermission permission="billing.manage_template">
                    <BillBuilderPage />
                  </RequirePermission>
                }
              />
              <Route
                path="bill-builder/:templateId"
                element={
                  <RequirePermission permission="billing.manage_template">
                    <BillBuilderPage />
                  </RequirePermission>
                }
              />
              <Route
                path="bills"
                element={
                  <RequirePermission permission="billing.read">
                    <BillsPage />
                  </RequirePermission>
                }
              />
              <Route
                path="payments"
                element={
                  <RequirePermission permission="payment.read">
                    <PaymentsPage />
                  </RequirePermission>
                }
              />
              {/* One component, two routes: water and electricity differ only
                  in unit, endpoint and whether an amount is passed through. */}
              <Route
                path="water"
                element={
                  <RequirePermission permission="water.read">
                    <UtilityPage utility="water" />
                  </RequirePermission>
                }
              />
              <Route
                path="electricity"
                element={
                  <RequirePermission permission="electricity.read">
                    <UtilityPage utility="electricity" />
                  </RequirePermission>
                }
              />
              <Route
                path="parking"
                element={
                  <RequirePermission permission="parking.read">
                    <ParkingPage />
                  </RequirePermission>
                }
              />
              <Route
                path="vehicles"
                element={
                  <RequirePermission permission="vehicle.read">
                    <VehiclesPage />
                  </RequirePermission>
                }
              />
              <Route
                path="pets"
                element={
                  <RequirePermission permission="pet.read">
                    <PetsPage />
                  </RequirePermission>
                }
              />
              <Route
                path="complaints"
                element={
                  <RequirePermission permission="complaint.read">
                    <ComplaintsPage />
                  </RequirePermission>
                }
              />
              {/* One component, two routes: maintenance and housekeeping differ
                  only in department, permission set and wording. */}
              <Route
                path="maintenance"
                element={
                  <RequirePermission permission="maintenance.read">
                    <WorkPage department="MAINTENANCE" />
                  </RequirePermission>
                }
              />
              <Route
                path="housekeeping"
                element={
                  <RequirePermission permission="housekeeping.read">
                    <WorkPage department="HOUSEKEEPING" />
                  </RequirePermission>
                }
              />
              <Route
                path="security"
                element={
                  <RequirePermission permission="security.read">
                    <SecurityPage />
                  </RequirePermission>
                }
              />
              <Route
                path="visitors"
                element={
                  <RequirePermission permission="visitor.read">
                    <VisitorsPage />
                  </RequirePermission>
                }
              />
              <Route
                path="notices"
                element={
                  <RequirePermission permission="notice.read">
                    <NoticesPage />
                  </RequirePermission>
                }
              />
              <Route
                path="amenities"
                element={
                  <RequirePermission permission="amenity.read">
                    <AmenitiesPage />
                  </RequirePermission>
                }
              />
              {/* The reports catalogue is filtered server-side, so a principal
                  who can run any report reaches the screen and sees only those
                  they may open. */}
              <Route
                path="reports"
                element={
                  <RequirePermission permission="report.read">
                    <ReportsPage />
                  </RequirePermission>
                }
              />
              <Route
                path="users"
                element={
                  <RequirePermission permission="user.read">
                    <UsersPage />
                  </RequirePermission>
                }
              />
              <Route
                path="appearance"
                element={
                  <RequirePermission permission="theme.update">
                    <AppearancePage />
                  </RequirePermission>
                }
              />
              <Route
                path="settings"
                element={
                  <RequirePermission permission="society.settings.manage">
                    <SettingsPage />
                  </RequirePermission>
                }
              />
            </Route>
          </Route>

          <Route path="/unauthorized" element={<UnauthorizedPage />} />
        </Route>

        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Suspended>
  );
}
