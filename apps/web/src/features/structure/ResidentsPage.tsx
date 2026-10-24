import { Pencil, Plus, Star, Trash2, UserPlus, Users } from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";

import {
  NFConfirmDialog,
  NFDataTable,
  NFDialog,
  NFPagination,
  NFSearch,
  NFStatCard,
  type Column,
} from "@/components/nestflow/data";
import {
  NFAvatar,
  NFButton,
  NFCard,
  NFEmptyState,
  NFField,
  NFInput,
  NFPageHeader,
  NFSelect,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { ApiError, api, type Page } from "@/services/api";
import { useAppSelector } from "@/store";
import {
  FAMILY_RELATIONSHIPS,
  type Building,
  type FamilyRelationship,
  type Flat,
  type Resident,
  type ResidentDetail,
  type StructureSummary,
  type TenantUser,
} from "@/types";
import { formatDate, formatNumber, formatPhone } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

export default function ResidentsPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const canManage = hasPermission(principal, "resident.manage");
  // See FlatsPage: society-wide totals and the building filter both need
  // building.read, which a resident does not hold.
  const canSeeSocietyTotals = hasPermission(principal, "building.read");

  const [data, setData] = React.useState<Page<Resident> | null>(null);
  const [summary, setSummary] = React.useState<StructureSummary | null>(null);
  const [buildings, setBuildings] = React.useState<Building[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [buildingId, setBuildingId] = React.useState("");
  const [residentType, setResidentType] = React.useState("");
  const [refreshKey, setRefreshKey] = React.useState(0);

  const [editing, setEditing] = React.useState<Resident | null | "new">(null);
  const [viewing, setViewing] = React.useState<string | null>(null);
  const [deleting, setDeleting] = React.useState<Resident | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const [debouncedQ, setDebouncedQ] = React.useState("");
  React.useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQ(q);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  const refresh = React.useCallback(() => setRefreshKey((k) => k + 1), []);

  React.useEffect(() => {
    if (!canSeeSocietyTotals) return;
    api.get<Building[]>("/buildings").then(setBuildings).catch(() => setBuildings([]));
  }, [canSeeSocietyTotals]);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    Promise.all([
      api.get<Page<Resident>>(
        "/residents",
        { page, limit: 25, q: debouncedQ, building_id: buildingId, resident_type: residentType },
        controller.signal,
      ),
      canSeeSocietyTotals
        ? api.get<StructureSummary>("/structure/summary", undefined, controller.signal)
        : Promise.resolve(null),
    ])
      .then(([residents, s]) => {
        setData(residents);
        setSummary(s);
      })
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setData(null);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, debouncedQ, buildingId, residentType, refreshKey, canSeeSocietyTotals]);

  async function runDelete() {
    if (!deleting) return;
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/residents/${deleting.id}`);
      setDeleting(null);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "This resident could not be removed.");
      setDeleting(null);
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<Resident>[] = [
    {
      key: "person",
      header: "Resident",
      render: (r) => (
        <div className="flex min-w-0 items-center gap-3">
          <NFAvatar name={r.full_name} size={34} />
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 truncate font-medium text-[var(--nf-text)]">
              {r.full_name}
              {r.is_primary && (
                <Star
                  className="size-3 shrink-0 fill-[var(--nf-warning)] text-[var(--nf-warning)]"
                  aria-label="Primary contact"
                />
              )}
            </p>
            <p className="truncate text-xs text-[var(--nf-text-muted)]">
              {r.email ?? formatPhone(r.phone)}
            </p>
          </div>
        </div>
      ),
    },
    {
      key: "flat",
      header: "Flat",
      render: (r) => <span className="font-medium">{r.flat_number ?? "—"}</span>,
    },
    {
      key: "type",
      header: "Type",
      render: (r) => (
        <NFStatusBadge
          status={r.resident_type}
          tone={r.resident_type === "OWNER" ? "success" : "info"}
        />
      ),
    },
    {
      key: "phone",
      header: "Phone",
      hideOnMobile: true,
      render: (r) => (
        <span className="text-[var(--nf-text-muted)]">{formatPhone(r.phone)}</span>
      ),
    },
    {
      key: "moved_in",
      header: "Moved in",
      hideOnMobile: true,
      render: (r) => (
        <span className="text-[var(--nf-text-muted)]">
          {r.move_in_date ? formatDate(r.move_in_date) : "—"}
        </span>
      ),
    },
    ...(canManage
      ? [
          {
            key: "actions",
            header: "",
            headerClassName: "w-20",
            render: (r: Resident) => (
              <div className="flex items-center gap-1">
                <NFButton
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Edit ${r.full_name}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setEditing(r);
                  }}
                >
                  <Pencil />
                </NFButton>
                <NFButton
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Remove ${r.full_name}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleting(r);
                  }}
                >
                  <Trash2 />
                </NFButton>
              </div>
            ),
          },
        ]
      : []),
  ];

  const noFlats = (summary?.flats ?? 0) === 0;

  return (
    <>
      <NFPageHeader
        title="Residents"
        description={
          canSeeSocietyTotals
            ? "Owners and tenants, their flats and their families."
            : "Everyone living in your flat, and their families."
        }
        actions={
          canManage && !noFlats ? (
            <NFButton onClick={() => setEditing("new")}>
              <Plus /> Add resident
            </NFButton>
          ) : undefined
        }
      />

      {error && (
        <div
          role="alert"
          className="mb-5 rounded-[var(--nf-radius)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] p-3.5 text-sm text-[var(--nf-text)]"
        >
          {error}
        </div>
      )}

      {summary && summary.residents > 0 && (
        <div className="mb-6 grid gap-4 sm:grid-cols-3">
          <NFStatCard
            label="Total residents"
            value={formatNumber(summary.residents)}
            icon={<Users />}
          />
          <NFStatCard
            label="Owners"
            value={formatNumber(summary.resident_types.OWNER ?? 0)}
            icon={<Users />}
            tone="success"
          />
          <NFStatCard
            label="Tenants"
            value={formatNumber(summary.resident_types.TENANT ?? 0)}
            icon={<Users />}
            tone="info"
          />
        </div>
      )}

      <NFCard>
        <div className="flex flex-wrap items-center gap-3 border-b border-[var(--nf-border)] p-4">
          <NFSearch value={q} onChange={setQ} placeholder="Search name, email or phone…" />
          {canSeeSocietyTotals && (
            <NFSelect
              value={buildingId}
              onChange={(e) => {
                setBuildingId(e.target.value);
                setPage(1);
              }}
              aria-label="Filter by building"
              className="sm:w-48"
            >
              <option value="">All buildings</option>
              {buildings.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </NFSelect>
          )}
          <NFSelect
            value={residentType}
            onChange={(e) => {
              setResidentType(e.target.value);
              setPage(1);
            }}
            aria-label="Filter by type"
            className="sm:w-40"
          >
            <option value="">All types</option>
            <option value="OWNER">Owners</option>
            <option value="TENANT">Tenants</option>
          </NFSelect>
        </div>

        <NFDataTable
          caption="Residents of this society"
          columns={columns}
          rows={data?.items ?? []}
          rowKey={(r) => r.id}
          loading={loading}
          onRowClick={(r) => setViewing(r.id)}
          empty={
            <NFEmptyState
              icon={<Users />}
              title={
                noFlats
                  ? "Add flats first"
                  : q || buildingId || residentType
                    ? "No matching residents"
                    : "No residents yet"
              }
              description={
                noFlats
                  ? "A resident lives in a flat, so the flats have to exist before they can be added."
                  : q || buildingId || residentType
                    ? "Try a different search term or clear the filters."
                    : "Add the owners and tenants living in this society."
              }
              action={
                canManage && !noFlats && !q && !buildingId && !residentType ? (
                  <NFButton onClick={() => setEditing("new")}>
                    <Plus /> Add the first resident
                  </NFButton>
                ) : undefined
              }
            />
          }
        />

        {data && (
          <NFPagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            limit={data.limit}
            onPageChange={setPage}
          />
        )}
      </NFCard>

      <ResidentDialog
        open={editing !== null}
        resident={editing === "new" ? undefined : (editing ?? undefined)}
        onClose={() => setEditing(null)}
        onSaved={refresh}
      />
      <ResidentDetailDialog
        residentId={viewing}
        canManage={canManage}
        onClose={() => setViewing(null)}
        onChanged={refresh}
      />
      <NFConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Remove ${deleting?.full_name ?? ""}?`}
        description="Their family members are removed too, and the flat's occupancy is recalculated."
        confirmLabel="Remove resident"
        destructive
        loading={busy}
        onConfirm={runDelete}
      />
    </>
  );
}

/* -------------------------------------------------------------------------- */

function ResidentDialog({
  open,
  resident,
  onClose,
  onSaved,
}: {
  open: boolean;
  resident?: Resident;
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = !!resident;
  const [flats, setFlats] = React.useState<Flat[]>([]);
  const [users, setUsers] = React.useState<TenantUser[]>([]);
  const [error, setError] = React.useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<{
    flat_id: string;
    full_name: string;
    email: string;
    phone: string;
    resident_type: string;
    is_primary: boolean;
    move_in_date: string;
    user_id: string;
  }>();

  React.useEffect(() => {
    if (!open) return;
    api
      .get<Page<Flat>>("/flats", { limit: 100 })
      .then((p) => setFlats(p.items))
      .catch(() => setFlats([]));
    api
      .get<Page<TenantUser>>("/users", { limit: 100 })
      .then((p) => setUsers(p.items))
      .catch(() => setUsers([]));

    reset({
      flat_id: resident?.flat_id ?? "",
      full_name: resident?.full_name ?? "",
      email: resident?.email ?? "",
      phone: resident?.phone ?? "",
      resident_type: resident?.resident_type ?? "OWNER",
      is_primary: resident?.is_primary ?? false,
      move_in_date: resident?.move_in_date ?? "",
      user_id: resident?.user_id ?? "",
    });
    setError(null);
  }, [open, resident, reset]);

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    const body = {
      flat_id: values.flat_id,
      full_name: values.full_name,
      email: values.email || null,
      phone: values.phone || null,
      resident_type: values.resident_type,
      is_primary: values.is_primary,
      move_in_date: values.move_in_date || null,
      user_id: values.user_id || null,
    };
    try {
      if (editing) await api.patch(`/residents/${resident!.id}`, body);
      else await api.post("/residents", body);
      onClose();
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save this resident.");
    }
  });

  return (
    <NFDialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={editing ? `Edit ${resident!.full_name}` : "Add a resident"}
      footer={
        <>
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton onClick={onSubmit} loading={isSubmitting}>
            {editing ? "Save changes" : "Add resident"}
          </NFButton>
        </>
      }
    >
      <form onSubmit={onSubmit} className="grid gap-4 sm:grid-cols-2" noValidate>
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)] sm:col-span-2"
          >
            {error}
          </p>
        )}

        <NFField label="Flat" htmlFor="r-flat" error={errors.flat_id?.message} required>
          <NFSelect
            id="r-flat"
            invalid={!!errors.flat_id}
            {...register("flat_id", { required: "Choose a flat." })}
          >
            <option value="">Select a flat…</option>
            {flats.map((f) => (
              <option key={f.id} value={f.id}>
                {f.flat_number} · {f.building_name}
              </option>
            ))}
          </NFSelect>
        </NFField>

        <NFField label="Type" htmlFor="r-type" required>
          <NFSelect id="r-type" {...register("resident_type", { required: true })}>
            <option value="OWNER">Owner</option>
            <option value="TENANT">Tenant</option>
          </NFSelect>
        </NFField>

        <NFField
          label="Full name"
          htmlFor="r-name"
          error={errors.full_name?.message}
          required
          className="sm:col-span-2"
        >
          <NFInput
            id="r-name"
            placeholder="Sneha Kulkarni"
            invalid={!!errors.full_name}
            {...register("full_name", { required: "Enter their name." })}
          />
        </NFField>

        <NFField label="Email" htmlFor="r-email" error={errors.email?.message}>
          <NFInput
            id="r-email"
            type="email"
            invalid={!!errors.email}
            {...register("email", {
              pattern: { value: /^\S+@\S+\.\S+$/, message: "Not a valid email address." },
            })}
          />
        </NFField>

        <NFField label="Phone" htmlFor="r-phone" error={errors.phone?.message}>
          <NFInput
            id="r-phone"
            inputMode="tel"
            maxLength={10}
            placeholder="9822012345"
            invalid={!!errors.phone}
            {...register("phone", {
              pattern: { value: /^[6-9][0-9]{9}$/, message: "Ten digits, starting with 6–9." },
            })}
          />
        </NFField>

        <NFField label="Moved in" htmlFor="r-movein">
          <NFInput id="r-movein" type="date" {...register("move_in_date")} />
        </NFField>

        <NFField
          label="App login"
          htmlFor="r-user"
          hint="Links this person to a society login so they see their own flat"
        >
          <NFSelect id="r-user" {...register("user_id")}>
            <option value="">Not linked</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name} ({u.email})
              </option>
            ))}
          </NFSelect>
        </NFField>

        <label className="flex cursor-pointer items-center gap-2.5 sm:col-span-2">
          <input
            type="checkbox"
            className="size-4 rounded accent-[var(--nf-primary)]"
            {...register("is_primary")}
          />
          <span className="text-sm text-[var(--nf-text)]">
            Primary contact for this flat
            <span className="ml-1.5 text-[var(--nf-text-muted)]">
              — replaces the current primary, if any
            </span>
          </span>
        </label>
      </form>
    </NFDialog>
  );
}

/* -------------------------------------------------------------------------- */

function ResidentDetailDialog({
  residentId,
  canManage,
  onClose,
  onChanged,
}: {
  residentId: string | null;
  canManage: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [resident, setResident] = React.useState<ResidentDetail | null>(null);
  const [adding, setAdding] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<{
    full_name: string;
    relationship_to_resident: FamilyRelationship | "";
    date_of_birth: string;
  }>();

  const load = React.useCallback(async () => {
    if (!residentId) return;
    try {
      setResident(await api.get<ResidentDetail>(`/residents/${residentId}`));
    } catch {
      setResident(null);
    }
  }, [residentId]);

  React.useEffect(() => {
    setAdding(false);
    setError(null);
    void load();
  }, [load]);

  const onAdd = handleSubmit(async (values) => {
    if (!residentId) return;
    setError(null);
    try {
      await api.post("/family-members", {
        resident_id: residentId,
        full_name: values.full_name,
        relationship_to_resident: values.relationship_to_resident,
        date_of_birth: values.date_of_birth || null,
      });
      reset({ full_name: "", relationship_to_resident: "", date_of_birth: "" });
      setAdding(false);
      await load();
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not add this family member.");
    }
  });

  async function removeMember(id: string) {
    await api.delete(`/family-members/${id}`).catch(() => undefined);
    await load();
  }

  return (
    <NFDialog
      open={residentId !== null}
      onOpenChange={(o) => !o && onClose()}
      title={resident?.full_name ?? "Resident"}
      description={
        resident ? `${resident.resident_type === "OWNER" ? "Owner" : "Tenant"} · Flat ${resident.flat_number}` : undefined
      }
      footer={
        <NFButton variant="secondary" onClick={onClose}>
          Close
        </NFButton>
      }
    >
      {resident ? (
        <div className="space-y-5">
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            {[
              ["Email", resident.email ?? "—"],
              ["Phone", formatPhone(resident.phone)],
              ["Moved in", resident.move_in_date ? formatDate(resident.move_in_date) : "—"],
              ["App login", resident.user_id ? "Linked" : "Not linked"],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-[var(--nf-text-muted)]">{label}</dt>
                <dd className="mt-0.5 text-[var(--nf-text)]">{value}</dd>
              </div>
            ))}
          </dl>

          <div className="border-t border-[var(--nf-border)] pt-4">
            <div className="mb-3 flex items-center justify-between">
              <h4 className="text-[13px] font-semibold text-[var(--nf-text)]">
                Family members ({resident.family_members.length})
              </h4>
              {canManage && !adding && (
                <NFButton variant="ghost" size="sm" onClick={() => setAdding(true)}>
                  <UserPlus /> Add
                </NFButton>
              )}
            </div>

            {error && (
              <p
                role="alert"
                className="mb-3 rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
              >
                {error}
              </p>
            )}

            {resident.family_members.length === 0 && !adding ? (
              <p className="text-[13px] text-[var(--nf-text-muted)]">
                No family members recorded.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {resident.family_members.map((m) => (
                  <li
                    key={m.id}
                    className="flex items-center justify-between rounded-[var(--nf-radius-sm)] border border-[var(--nf-border)] px-3 py-2"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-[13px] font-medium text-[var(--nf-text)]">
                        {m.full_name}
                      </p>
                      <p className="text-xs text-[var(--nf-text-muted)]">
                        {FAMILY_RELATIONSHIPS.find((r) => r.value === m.relationship_to_resident)
                          ?.label ?? m.relationship_to_resident}
                        {m.date_of_birth ? ` · born ${formatDate(m.date_of_birth)}` : ""}
                      </p>
                    </div>
                    {canManage && (
                      <NFButton
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Remove ${m.full_name}`}
                        onClick={() => removeMember(m.id)}
                      >
                        <Trash2 />
                      </NFButton>
                    )}
                  </li>
                ))}
              </ul>
            )}

            {adding && (
              <form onSubmit={onAdd} className="mt-3 space-y-3" noValidate>
                <NFField label="Name" htmlFor="fm-name" error={errors.full_name?.message} required>
                  <NFInput
                    id="fm-name"
                    invalid={!!errors.full_name}
                    {...register("full_name", { required: "Enter their name." })}
                  />
                </NFField>
                <div className="grid grid-cols-2 gap-3">
                  <NFField
                    label="Relationship"
                    htmlFor="fm-rel"
                    error={errors.relationship_to_resident?.message}
                    required
                  >
                    <NFSelect
                      id="fm-rel"
                      invalid={!!errors.relationship_to_resident}
                      {...register("relationship_to_resident", { required: "Required." })}
                    >
                      <option value="">Select…</option>
                      {FAMILY_RELATIONSHIPS.map((r) => (
                        <option key={r.value} value={r.value}>
                          {r.label}
                        </option>
                      ))}
                    </NFSelect>
                  </NFField>
                  <NFField label="Date of birth" htmlFor="fm-dob">
                    <NFInput id="fm-dob" type="date" {...register("date_of_birth")} />
                  </NFField>
                </div>
                <div className="flex justify-end gap-2">
                  <NFButton
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => setAdding(false)}
                  >
                    Cancel
                  </NFButton>
                  <NFButton type="submit" size="sm" loading={isSubmitting}>
                    Add member
                  </NFButton>
                </div>
              </form>
            )}
          </div>
        </div>
      ) : (
        <p className="text-sm text-[var(--nf-text-muted)]">Loading…</p>
      )}
    </NFDialog>
  );
}
