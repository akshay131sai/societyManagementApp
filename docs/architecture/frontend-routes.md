# Frontend Route Plan & Code Splitting

## 1. Principles

1. **Route-level code splitting everywhere.** Every page is `React.lazy`.
2. **Role determines the bundle.** A Flat Owner must never download the Bill
   Builder, Recharts, dnd-kit, or any admin module.
3. **Permission-gated routes**, not role-gated. `<RequirePermission perm="...">`.
4. **One bootstrap call.** `/auth/me` returns principal + society + theme + nav;
   the shell renders once, with no waterfall.

## 2. Route tree

```
/                                   -> redirect by role
/login                              [public, eager]
/forgot-password                    [public, eager]
/unauthorized                       [public, eager]
/subscription-expired               [public-ish, eager]  billing wall
/provisioning                       [eager]              society not ready yet

/admin                              SUPER_ADMIN            (PlatformLayout)
  /admin/dashboard
  /admin/societies
  /admin/societies/new
  /admin/societies/:id
  /admin/plans
  /admin/subscriptions
  /admin/society-admins
  /admin/users
  /admin/audit-logs
  /admin/settings

/app                                society-scoped         (SocietyLayout)
  /app/dashboard                    role-aware home
  /app/buildings                    building.read      [P2]
  /app/blocks                       block.read         [P2]
  /app/floors                       floor.read         [P2]
  /app/flats                        flat.read          [P2]
  /app/residents                    resident.read      [P2]
  /app/users                        user.read          [P1]
  /app/bill-builder                 billing.manage_template  [P3]  <-- heaviest chunk
  /app/bill-templates               billing.manage_template  [P3]
  /app/bills                        billing.read       [P3]
  /app/bills/:id                    billing.read       [P3]
  /app/payments                     payment.read       [P4]
  /app/water                        water.read         [P4]
  /app/electricity                  electricity.read   [P4]
  /app/parking                      parking.read       [P4]
  /app/vehicles                     vehicle.read       [P4]
  /app/pets                         pet.read           [P4]
  /app/complaints                   complaint.read     [P5]
  /app/maintenance                  maintenance.read   [P5]  <-- one component,
  /app/housekeeping                 housekeeping.read  [P5]      two routes
  /app/security                     security.read      [P5]
  /app/visitors                     visitor.read       [P5]
  /app/notices                      notice.read        [P5]
  /app/amenities                    amenity.read       [P5]
  /app/reports                      report.read        [P6]
  /app/appearance                   theme.update       [P1]
  /app/settings                     society.settings.manage [P1]
  /app/profile                      authenticated      [P1]
```

Every `/app/*` route above now has a real screen. Three of them are one
component mounted twice, because the pairs differ only in an endpoint prefix, a
permission set and the words on the page:

| Component | Routes |
|---|---|
| `UtilityPage` | `/app/water`, `/app/electricity` |
| `WorkPage` | `/app/maintenance`, `/app/housekeeping` |

Writing each twice would mean fixing every bug twice.

`ReportsPage` is a fourth case of the same idea taken further: it renders *any*
report from the `columns`/`rows` envelope the server sends, so adding a report
to the backend puts it on this screen with no frontend release at all.

## 3. Guard composition

```tsx
<Route element={<RequireAuth />}>                    {/* token present + /auth/me resolved */}
  <Route element={<RequireSuperAdmin />}>
    <Route path="/admin" element={<PlatformLayout />}>...</Route>
  </Route>

  <Route element={<RequireSociety />}>               {/* ACTIVE + subscription valid */}
    <Route path="/app" element={<SocietyLayout />}>
      <Route path="bills" element={
        <RequirePermission perm="billing.read"><Bills /></RequirePermission>
      }/>
    </Route>
  </Route>
</Route>
```

`RequireSociety` redirects to `/subscription-expired` on a 402 and
`/provisioning` while the tenant DB is still being built. The frontend guard is
**convenience only** — the backend refuses regardless, per the API contract.

## 4. Chunking strategy

| Chunk | Contents | Loaded when |
|---|---|---|
| `index` | React, Router, Redux, API client, theme, shell, NF primitives | always (target < 180 KB gzip) |
| `login` | auth screens + Firebase Auth SDK | unauthenticated only |
| `platform` | all `/admin/*` | SUPER_ADMIN only |
| `society-core` | dashboard, users, settings, appearance | society users |
| `structure` | buildings/blocks/floors/flats/residents | on navigation |
| `billing` | bills, bill detail | on navigation |
| `bill-builder` | dnd-kit + builder + node editors | `billing.manage_template` only |
| `charts` | Recharts (414 KB / 117 KB gzip) | first chart *render*, not first chart route |
| `operations` | complaints, maintenance, housekeeping | on navigation |
| `security` | security board, visitors | on navigation |
| `community` | notices, amenities | on navigation |
| `reports` | the report renderer + CSV export | on navigation |

Manual `manualChunks` in `vite.config.ts` pins `react-vendor`, `charts`
(recharts) and `dnd` (dnd-kit) so they cannot be accidentally pulled into the
entry chunk by a stray static import. `rollup-plugin-visualizer` writes
`dist/stats.html` on every production build, and a CI size budget fails the build
if the entry chunk regresses.

Lucide icons are imported individually (`import { Home } from "lucide-react"`) —
the barrel import costs hundreds of KB.

**The chart chunk loads later than its route.** `features/utilities/Charts.tsx`
is the only module that imports Recharts, and every page reaches it through
`LazyCharts.tsx`, which wraps each chart in `React.lazy`. The resident
dashboard — the busiest screen in the product — therefore paints its figures
immediately and fills the charts in behind them, rather than waiting on a
414 KB library before showing someone what they owe.

Measured on the Phase 6 build: entry `176 KB / 57.7 KB gzip`, `charts`
`414 KB / 117 KB gzip` in its own chunk, `bill-builder` `27 KB` in another. A
Flat Owner who opens only Bills and Payments downloads neither.

The entry chunk grew by 2 KB gzipped in Phase 6, and all of it is the
notification bell. It is *not* lazy: it lives in the shell, its badge is the
first thing a signed-in user looks at, and a suspense boundary there would
flash on every page load. Each Phase 5 screen is between 9 and 16 KB in its own
chunk.

## 5. Layouts

**PlatformLayout / SocietyLayout (desktop ≥ 1024px)**
```
+----------------------------------------------------------+
| Sidebar   |  Topbar: breadcrumb · search · notif · avatar |
| (256px)   +-----------------------------------------------+
| logo      |                                               |
| nav       |   <Outlet />   max-w-[1440px]  p-6            |
| collapse  |                                               |
+----------------------------------------------------------+
```

**Tablet (768–1023px)** — sidebar collapses to a 64px icon rail; labels on hover.

**Mobile (< 768px)** — sidebar becomes a `Sheet` drawer from the hamburger;
`NFMobileNavigation` renders a bottom bar. Flat Owner bottom nav:
`Home · Bills · Visitors · Utilities · More`, with `More` opening a sheet
containing the remaining items.

Breakpoints: 320 / 375 / 768 / 1024 / 1440. Content uses `min-w-0` and tables
scroll inside their own container so the page body never scrolls horizontally.

## 6. State

Redux Toolkit holds **small, session-shaped** state only:

```
auth      { status, principal, permissions, error }
society   { society, settings, subscription }
theme     { mode, colors, radius, logoUrl, resolvedTokens }
ui        { sidebarCollapsed, activeSheet, toasts }
filters   { [routeKey]: { page, limit, q, sort, ... } }
```

Server data is **not** kept in Redux. Lists are fetched per page through the
API client with a small in-memory cache keyed by the request URL. Residents,
bills and visitors are server-paginated; a 10,000-row list never enters the
store.

## 7. NestFlow component layer

ShadCN generates primitives into `components/ui/`. Those are **never imported by
feature code**. Feature code imports `components/nestflow/`:

```
NFButton  NFInput  NFSelect  NFCard  NFStatCard  NFChartCard
NFDataTable  NFStatusBadge  NFPageHeader  NFEmptyState
NFConfirmDialog  NFThemePicker  NFBillNode  NFBillBuilder
NFMobileNavigation  NFSkeleton  NFCurrency  NFDateTime
```

This keeps a ShadCN re-generation from rippling into 200 files, and means
`NFCurrency` (Indian grouping — ₹12,45,000, not ₹1,245,000) and `NFDateTime`
(`Asia/Kolkata`) are applied consistently rather than reinvented per screen.

## 8. Accessibility

- Radix (via ShadCN) supplies focus trapping, `aria-*` and escape handling for
  dialogs, sheets, dropdowns and tooltips.
- Visible focus rings via `--nf-ring`; never `outline: none` without a
  replacement.
- The Bill Builder ships a **keyboard-first alternative** to drag and drop: a
  tree view where nodes are added, moved and nested with keyboard commands. The
  drag surface is an enhancement, not the only path.
- Forms use React Hook Form with `aria-invalid` + `aria-describedby` bound to
  the error node.
- `NFDataTable` renders semantic `<table>` with `<caption>` and scope-correct
  headers.

## 9. Realtime

`useRealtime` opens one WebSocket per signed-in tab and the notification bell is
its only consumer. Three rules keep it out of the way:

- **It only ever invalidates.** An incoming event refetches
  `/notifications/feed` rather than splicing a notification into local state. A
  list built by merging pushes drifts from the server the first time one is
  missed; this one cannot.
- **Reconnection backs off** from 1s to 30s and resets on a successful open, so
  a backend restart does not become 300 tabs reconnecting every second.
- **A hidden tab holds no socket.** The connection drops on
  `visibilitychange` and is re-established on return, which also refetches and
  closes the gap.

When the socket is down the bell falls back to a 60-second poll, and its status
dot says which mode it is in — a badge nobody can trust is worse than a stale
one that admits it.
