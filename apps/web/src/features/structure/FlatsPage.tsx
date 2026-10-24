import { DoorOpen, Pencil, Plus, Sparkles, Trash2, Users } from "lucide-react";
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
import type {
  Block,
  Building,
  Flat,
  FlatBulkResult,
  Floor,
  StructureSummary,
} from "@/types";
import { formatNumber } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const OCCUPANCY_LABELS: Record<string, string> = {
  OWNER_OCCUPIED: "Owner occupied",
  RENTED: "Rented",
  VACANT: "Vacant",
};

export default function FlatsPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const canManage = hasPermission(principal, "flat.manage");
  // A resident holds no building.read. Both the building filter and the
  // society-wide totals depend on it, so they are hidden rather than
  // firing requests that would be refused on every load.
  const canSeeSocietyTotals = hasPermission(principal, "building.read");

  const [data, setData] = React.useState<Page<Flat> | null>(null);
  const [summary, setSummary] = React.useState<StructureSummary | null>(null);
  const [buildings, setBuildings] = React.useState<Building[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [buildingId, setBuildingId] = React.useState("");
  const [occupancy, setOccupancy] = React.useState("");
  const [refreshKey, setRefreshKey] = React.useState(0);

  const [editing, setEditing] = React.useState<Flat | null | "new">(null);
  const [bulkOpen, setBulkOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<Flat | null>(null);
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
  }, [refreshKey, canSeeSocietyTotals]);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    Promise.all([
      api.get<Page<Flat>>(
        "/flats",
        { page, limit: 25, q: debouncedQ, building_id: buildingId, occupancy_status: occupancy },
        controller.signal,
      ),
      canSeeSocietyTotals
        ? api.get<StructureSummary>("/structure/summary", undefined, controller.signal)
        : Promise.resolve(null),
    ])
      .then(([flats, s]) => {
        setData(flats);
        setSummary(s);
      })
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setData(null);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, debouncedQ, buildingId, occupancy, refreshKey, canSeeSocietyTotals]);

  async function runDelete() {
    if (!deleting) return;
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/flats/${deleting.id}`);
      setDeleting(null);
      refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "This flat could not be deleted.");
      setDeleting(null);
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<Flat>[] = [
    {
      key: "number",
      header: "Flat",
      render: (f) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--nf-text)]">{f.flat_number}</p>
          <p className="truncate text-xs text-[var(--nf-text-muted)]">
            {f.building_name} · {f.floor_name}
          </p>
        </div>
      ),
    },
    {
      key: "type",
      header: "Type",
      hideOnMobile: true,
      render: (f) =>
        f.flat_type ? (
          <span className="rounded-full bg-[var(--nf-primary-subtle)] px-2 py-0.5 text-[11px] font-medium text-[var(--nf-primary)]">
            {f.flat_type}
          </span>
        ) : (
          <span className="text-[var(--nf-text-subtle)]">—</span>
        ),
    },
    {
      key: "area",
      header: "Area",
      className: "tabular-nums",
      render: (f) => (
        <span>
          {formatNumber(Number(f.area_sqft))}
          <span className="ml-1 text-xs text-[var(--nf-text-muted)]">sqft</span>
        </span>
      ),
    },
    {
      key: "occupancy",
      header: "Occupancy",
      render: (f) => (
        <NFStatusBadge
          status={f.occupancy_status}
          tone={
            f.occupancy_status === "VACANT"
              ? "neutral"
              : f.occupancy_status === "RENTED"
                ? "info"
                : "success"
          }
        />
      ),
    },
    {
      key: "residents",
      header: "Residents",
      hideOnMobile: true,
      className: "tabular-nums",
      render: (f) => f.resident_count,
    },
    ...(canManage
      ? [
          {
            key: "actions",
            header: "",
            headerClassName: "w-20",
            render: (f: Flat) => (
              <div className="flex items-center gap-1">
                <NFButton
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Edit ${f.flat_number}`}
                  onClick={() => setEditing(f)}
                >
                  <Pencil />
                </NFButton>
                <NFButton
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Delete ${f.flat_number}`}
                  onClick={() => setDeleting(f)}
                >
                  <Trash2 />
                </NFButton>
              </div>
            ),
          },
        ]
      : []),
  ];

  const noStructure = canSeeSocietyTotals && buildings.length === 0;

  return (
    <>
      <NFPageHeader
        title="Flats"
        description={
          canSeeSocietyTotals
            ? "Every flat in the society, with its area, type and occupancy."
            : "Your flat, with its area, type and occupancy."
        }
        actions={
          canManage && !noStructure ? (
            <div className="flex items-center gap-2">
              <NFButton variant="secondary" onClick={() => setBulkOpen(true)}>
                <Sparkles /> Generate
              </NFButton>
              <NFButton onClick={() => setEditing("new")}>
                <Plus /> Add flat
              </NFButton>
            </div>
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

      {summary && summary.flats > 0 && (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <NFStatCard label="Total flats" value={formatNumber(summary.flats)} icon={<DoorOpen />} />
          <NFStatCard
            label="Owner occupied"
            value={formatNumber(summary.occupancy.OWNER_OCCUPIED ?? 0)}
            icon={<Users />}
            tone="success"
          />
          <NFStatCard
            label="Rented"
            value={formatNumber(summary.occupancy.RENTED ?? 0)}
            icon={<Users />}
            tone="info"
          />
          <NFStatCard
            label="Vacant"
            value={formatNumber(summary.occupancy.VACANT ?? 0)}
            icon={<DoorOpen />}
            tone="warning"
          />
        </div>
      )}

      <NFCard>
        <div className="flex flex-wrap items-center gap-3 border-b border-[var(--nf-border)] p-4">
          <NFSearch value={q} onChange={setQ} placeholder="Search flat number…" />
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
            value={occupancy}
            onChange={(e) => {
              setOccupancy(e.target.value);
              setPage(1);
            }}
            aria-label="Filter by occupancy"
            className="sm:w-44"
          >
            <option value="">All occupancy</option>
            {Object.entries(OCCUPANCY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </NFSelect>
        </div>

        <NFDataTable
          caption="Flats in this society"
          columns={columns}
          rows={data?.items ?? []}
          rowKey={(f) => f.id}
          loading={loading}
          empty={
            <NFEmptyState
              icon={<DoorOpen />}
              title={
                noStructure
                  ? "Add a building first"
                  : q || buildingId || occupancy
                    ? "No matching flats"
                    : "No flats yet"
              }
              description={
                noStructure
                  ? "Flats belong to a floor, so the structure has to exist before they can be added."
                  : q || buildingId || occupancy
                    ? "Try a different search term or clear the filters."
                    : "Generate a whole block's flats from a numbering pattern, rather than adding them one at a time."
              }
              action={
                canManage && !noStructure && !q && !buildingId && !occupancy ? (
                  <NFButton onClick={() => setBulkOpen(true)}>
                    <Sparkles /> Generate flats
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

      <FlatDialog
        open={editing !== null}
        flat={editing === "new" ? undefined : (editing ?? undefined)}
        onClose={() => setEditing(null)}
        onSaved={refresh}
      />
      <BulkGenerateDialog
        open={bulkOpen}
        buildings={buildings}
        onClose={() => setBulkOpen(false)}
        onSaved={refresh}
      />
      <NFConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete flat ${deleting?.flat_number ?? ""}?`}
        description="This cannot be undone. A flat with active residents cannot be deleted."
        confirmLabel="Delete flat"
        destructive
        loading={busy}
        onConfirm={runDelete}
      />
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* Single flat                                                                */
/* -------------------------------------------------------------------------- */

function FlatDialog({
  open,
  flat,
  onClose,
  onSaved,
}: {
  open: boolean;
  flat?: Flat;
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = !!flat;
  const [floors, setFloors] = React.useState<Floor[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<{
    floor_id: string;
    flat_number: string;
    flat_type: string;
    area_sqft: string;
    carpet_area_sqft: string;
    occupancy_status: string;
  }>();

  React.useEffect(() => {
    if (!open) return;
    api.get<Floor[]>("/floors").then(setFloors).catch(() => setFloors([]));
    reset({
      floor_id: flat?.floor_id ?? "",
      flat_number: flat?.flat_number ?? "",
      flat_type: flat?.flat_type ?? "",
      area_sqft: flat?.area_sqft ?? "",
      carpet_area_sqft: flat?.carpet_area_sqft ?? "",
      occupancy_status: flat?.occupancy_status ?? "VACANT",
    });
    setError(null);
  }, [open, flat, reset]);

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    const body = {
      floor_id: values.floor_id,
      flat_number: values.flat_number,
      flat_type: values.flat_type || null,
      area_sqft: values.area_sqft,
      carpet_area_sqft: values.carpet_area_sqft || null,
      occupancy_status: values.occupancy_status,
    };
    try {
      if (editing) await api.patch(`/flats/${flat!.id}`, body);
      else await api.post("/flats", body);
      onClose();
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save this flat.");
    }
  });

  return (
    <NFDialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={editing ? `Edit ${flat!.flat_number}` : "Add a flat"}
      footer={
        <>
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton onClick={onSubmit} loading={isSubmitting}>
            {editing ? "Save changes" : "Add flat"}
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

        <NFField
          label="Floor"
          htmlFor="fl-floor"
          error={errors.floor_id?.message}
          required
          className="sm:col-span-2"
        >
          <NFSelect
            id="fl-floor"
            invalid={!!errors.floor_id}
            {...register("floor_id", { required: "Choose a floor." })}
          >
            <option value="">Select a floor…</option>
            {floors.map((f) => (
              <option key={f.id} value={f.id}>
                {f.building_name} · {f.block_name} · {f.display_name}
              </option>
            ))}
          </NFSelect>
        </NFField>

        <NFField
          label="Flat number"
          htmlFor="fl-number"
          error={errors.flat_number?.message}
          hint="Unique within its building"
          required
        >
          <NFInput
            id="fl-number"
            placeholder="A-101"
            invalid={!!errors.flat_number}
            {...register("flat_number", { required: "Enter the flat number." })}
          />
        </NFField>

        <NFField label="Type" htmlFor="fl-type" hint="e.g. 2BHK">
          <NFInput id="fl-type" placeholder="2BHK" maxLength={20} {...register("flat_type")} />
        </NFField>

        <NFField
          label="Built-up area"
          htmlFor="fl-area"
          error={errors.area_sqft?.message}
          hint="Square feet"
          required
        >
          <NFInput
            id="fl-area"
            type="number"
            step="0.01"
            min={1}
            invalid={!!errors.area_sqft}
            {...register("area_sqft", { required: "Enter the built-up area." })}
          />
        </NFField>

        <NFField label="Carpet area" htmlFor="fl-carpet" hint="Optional">
          <NFInput
            id="fl-carpet"
            type="number"
            step="0.01"
            min={1}
            {...register("carpet_area_sqft")}
          />
        </NFField>

        <NFField
          label="Occupancy"
          htmlFor="fl-occ"
          hint="Recalculated automatically from residents"
          className="sm:col-span-2"
        >
          <NFSelect id="fl-occ" {...register("occupancy_status")}>
            {Object.entries(OCCUPANCY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </NFSelect>
        </NFField>
      </form>
    </NFDialog>
  );
}

/* -------------------------------------------------------------------------- */
/* Bulk generator                                                             */
/* -------------------------------------------------------------------------- */

function BulkGenerateDialog({
  open,
  buildings,
  onClose,
  onSaved,
}: {
  open: boolean;
  buildings: Building[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [blocks, setBlocks] = React.useState<Block[]>([]);
  const [preview, setPreview] = React.useState<FlatBulkResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<{
    building_id: string;
    block_id: string;
    from_floor: string;
    to_floor: string;
    flats_per_floor: string;
    pattern: string;
    start_index: string;
    area_sqft: string;
    flat_type: string;
  }>({
    defaultValues: {
      from_floor: "1",
      to_floor: "10",
      flats_per_floor: "4",
      pattern: "{block}-{floor}{index:02d}",
      start_index: "1",
      area_sqft: "1100",
      flat_type: "2BHK",
    },
  });

  const buildingId = watch("building_id");

  React.useEffect(() => {
    if (open) {
      reset({
        building_id: buildings[0]?.id ?? "",
        block_id: "",
        from_floor: "1",
        to_floor: "10",
        flats_per_floor: "4",
        pattern: "{block}-{floor}{index:02d}",
        start_index: "1",
        area_sqft: "1100",
        flat_type: "2BHK",
      });
      setPreview(null);
      setError(null);
    }
  }, [open, buildings, reset]);

  React.useEffect(() => {
    if (!buildingId) {
      setBlocks([]);
      return;
    }
    api
      .get<Block[]>("/blocks", { building_id: buildingId })
      .then(setBlocks)
      .catch(() => setBlocks([]));
  }, [buildingId]);

  const total =
    (Number(watch("to_floor")) - Number(watch("from_floor")) + 1) *
    Number(watch("flats_per_floor"));

  function buildBody(values: Record<string, string>, dryRun: boolean) {
    return {
      block_id: values.block_id,
      from_floor: Number(values.from_floor),
      to_floor: Number(values.to_floor),
      flats_per_floor: Number(values.flats_per_floor),
      pattern: values.pattern,
      start_index: Number(values.start_index),
      area_sqft: values.area_sqft,
      flat_type: values.flat_type || null,
      create_missing_floors: true,
      dry_run: dryRun,
    };
  }

  const onPreview = handleSubmit(async (values) => {
    setError(null);
    setSaving(true);
    try {
      setPreview(await api.post<FlatBulkResult>("/flats/bulk", buildBody(values, true)));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not generate a preview.");
      setPreview(null);
    } finally {
      setSaving(false);
    }
  });

  const onCreate = handleSubmit(async (values) => {
    setError(null);
    setSaving(true);
    try {
      await api.post<FlatBulkResult>("/flats/bulk", buildBody(values, false));
      onClose();
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create these flats.");
    } finally {
      setSaving(false);
    }
  });

  return (
    <NFDialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Generate flats"
      description="Create a whole block's flats from a numbering pattern, instead of one at a time."
      size="lg"
      footer={
        <>
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton variant="outline" onClick={onPreview} loading={saving && !preview}>
            Preview
          </NFButton>
          <NFButton onClick={onCreate} loading={saving && !!preview}>
            Create {total > 0 ? `${total} flat(s)` : "flats"}
          </NFButton>
        </>
      }
    >
      <form onSubmit={onPreview} className="grid gap-4 sm:grid-cols-2" noValidate>
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)] sm:col-span-2"
          >
            {error}
          </p>
        )}

        <NFField label="Building" htmlFor="bg-building" required>
          <NFSelect id="bg-building" {...register("building_id", { required: true })}>
            {buildings.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </NFSelect>
        </NFField>

        <NFField label="Block" htmlFor="bg-block" error={errors.block_id?.message} required>
          <NFSelect
            id="bg-block"
            invalid={!!errors.block_id}
            {...register("block_id", { required: "Choose a block." })}
          >
            <option value="">Select a block…</option>
            {blocks.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name} ({b.code})
              </option>
            ))}
          </NFSelect>
        </NFField>

        <NFField label="From floor" htmlFor="bg-from" hint="0 = ground">
          <NFInput id="bg-from" type="number" min={-10} max={200} {...register("from_floor")} />
        </NFField>

        <NFField label="To floor" htmlFor="bg-to">
          <NFInput id="bg-to" type="number" min={-10} max={200} {...register("to_floor")} />
        </NFField>

        <NFField label="Flats per floor" htmlFor="bg-per">
          <NFInput id="bg-per" type="number" min={1} max={50} {...register("flats_per_floor")} />
        </NFField>

        <NFField label="First flat number" htmlFor="bg-start" hint="Usually 1">
          <NFInput id="bg-start" type="number" min={0} max={99} {...register("start_index")} />
        </NFField>

        <NFField
          label="Numbering pattern"
          htmlFor="bg-pattern"
          hint="Placeholders: {building} {block} {floor} {index}"
          className="sm:col-span-2"
        >
          <NFInput id="bg-pattern" className="font-mono" {...register("pattern")} />
        </NFField>

        <NFField label="Built-up area" htmlFor="bg-area" hint="Square feet, per flat" required>
          <NFInput id="bg-area" type="number" step="0.01" min={1} {...register("area_sqft")} />
        </NFField>

        <NFField label="Type" htmlFor="bg-type">
          <NFInput id="bg-type" placeholder="2BHK" maxLength={20} {...register("flat_type")} />
        </NFField>

        {preview && (
          <div className="sm:col-span-2">
            <div className="rounded-[var(--nf-radius)] border border-[var(--nf-border)] bg-[var(--nf-background)] p-3.5">
              <p className="text-[13px] font-medium text-[var(--nf-text)]">
                Preview — {preview.preview.length} number(s) generated
                {preview.conflicts.length > 0 &&
                  `, ${preview.conflicts.length} already exist and will be skipped`}
              </p>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {preview.preview.slice(0, 24).map((n) => (
                  <span
                    key={n}
                    className="rounded-full bg-[var(--nf-primary-subtle)] px-2 py-0.5 font-mono text-[11px] text-[var(--nf-primary)]"
                  >
                    {n}
                  </span>
                ))}
                {preview.preview.length > 24 && (
                  <span className="px-1 text-[11px] text-[var(--nf-text-muted)]">
                    +{preview.preview.length - 24} more
                  </span>
                )}
              </div>
              {preview.conflicts.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5 border-t border-[var(--nf-border)] pt-3">
                  {preview.conflicts.slice(0, 12).map((n) => (
                    <span
                      key={n}
                      className="rounded-full bg-[var(--nf-warning-subtle)] px-2 py-0.5 font-mono text-[11px] text-[var(--nf-warning)]"
                    >
                      {n}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </form>
    </NFDialog>
  );
}
