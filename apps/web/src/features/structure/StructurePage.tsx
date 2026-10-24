/**
 * Structure — buildings, blocks and floors in one tree.
 *
 * Three sibling nav items for three levels of one hierarchy reads worse than a
 * tree the admin can expand, so blocks and floors are managed here rather than
 * on their own screens.
 */

import {
  Building2,
  ChevronRight,
  DoorOpen,
  Layers,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";

import { NFConfirmDialog, NFDialog, NFStatCard } from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFEmptyState,
  NFField,
  NFInput,
  NFPageHeader,
  NFSkeleton,
  NFTextarea,
} from "@/components/nestflow/primitives";
import { ApiError, api } from "@/services/api";
import { useAppSelector } from "@/store";
import type { Block, Building, Floor, StructureSummary } from "@/types";
import { cn } from "@/utils/cn";
import { formatNumber } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

type Dialog =
  | { kind: "building"; building?: Building }
  | { kind: "block"; buildingId: string; block?: Block }
  | { kind: "floors"; blockId: string }
  | null;

type Confirm =
  | { kind: "building"; id: string; label: string }
  | { kind: "block"; id: string; label: string }
  | { kind: "floor"; id: string; label: string }
  | null;

export default function StructurePage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const canManage = hasPermission(principal, "building.manage");

  const [summary, setSummary] = React.useState<StructureSummary | null>(null);
  const [buildings, setBuildings] = React.useState<Building[]>([]);
  const [blocks, setBlocks] = React.useState<Block[]>([]);
  const [floors, setFloors] = React.useState<Floor[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const [dialog, setDialog] = React.useState<Dialog>(null);
  const [confirm, setConfirm] = React.useState<Confirm>(null);
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [s, b, bl, fl] = await Promise.all([
        api.get<StructureSummary>("/structure/summary"),
        api.get<Building[]>("/buildings"),
        api.get<Block[]>("/blocks"),
        api.get<Floor[]>("/floors"),
      ]);
      setSummary(s);
      setBuildings(b);
      setBlocks(bl);
      setFloors(fl);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the structure.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  // Expand the first building on first load, so the page is never a wall of
  // collapsed rows.
  React.useEffect(() => {
    if (buildings.length && expanded.size === 0) {
      setExpanded(new Set([buildings[0].id]));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildings.length]);

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function runDelete() {
    if (!confirm) return;
    setBusy(true);
    setError(null);
    try {
      const path = { building: "buildings", block: "blocks", floor: "floors" }[confirm.kind];
      await api.delete(`/${path}/${confirm.id}`);
      setConfirm(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That could not be deleted.");
      setConfirm(null);
    } finally {
      setBusy(false);
    }
  }

  const blocksFor = (buildingId: string) => blocks.filter((b) => b.building_id === buildingId);
  const floorsFor = (blockId: string) => floors.filter((f) => f.block_id === blockId);

  return (
    <>
      <NFPageHeader
        title="Structure"
        description="Buildings, blocks and floors. Flats are managed on the Flats page."
        actions={
          canManage ? (
            <NFButton onClick={() => setDialog({ kind: "building" })}>
              <Plus /> Add building
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

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <NFStatCard
          label="Buildings"
          value={formatNumber(summary?.buildings ?? 0)}
          icon={<Building2 />}
          loading={loading}
        />
        <NFStatCard
          label="Floors"
          value={formatNumber(summary?.floors ?? 0)}
          hint={summary ? `${summary.blocks} block(s)` : undefined}
          icon={<Layers />}
          tone="info"
          loading={loading}
        />
        <NFStatCard
          label="Flats"
          value={formatNumber(summary?.flats ?? 0)}
          icon={<DoorOpen />}
          tone="success"
          loading={loading}
        />
        <NFStatCard
          label="Total area"
          value={`${formatNumber(Math.round(summary?.total_area_sqft ?? 0))} sqft`}
          hint={summary?.flats ? `avg ${Math.round(summary.total_area_sqft / summary.flats)} sqft` : undefined}
          icon={<Layers />}
          tone="primary"
          loading={loading}
        />
      </div>

      <NFCard className="mt-6">
        <NFCardHeader
          title="Hierarchy"
          description="Expand a building to manage its blocks and floors."
        />

        {loading ? (
          <NFCardBody className="space-y-2">
            {[0, 1, 2].map((i) => (
              <NFSkeleton key={i} className="h-14" />
            ))}
          </NFCardBody>
        ) : buildings.length === 0 ? (
          <NFEmptyState
            icon={<Building2 />}
            title="No buildings yet"
            description="Add the first building. A default 'Main' block is created with it, so you can go straight to adding floors and flats."
            action={
              canManage ? (
                <NFButton onClick={() => setDialog({ kind: "building" })}>
                  <Plus /> Add the first building
                </NFButton>
              ) : undefined
            }
          />
        ) : (
          <ul className="divide-y divide-[var(--nf-border)]">
            {buildings.map((building) => {
              const open = expanded.has(building.id);
              return (
                <li key={building.id}>
                  <div className="flex flex-wrap items-center gap-3 px-5 py-3.5">
                    <button
                      onClick={() => toggle(building.id)}
                      aria-expanded={open}
                      className="flex min-w-0 flex-1 items-center gap-3 text-left"
                    >
                      <ChevronRight
                        className={cn(
                          "size-4 shrink-0 text-[var(--nf-text-subtle)] transition-transform",
                          open && "rotate-90",
                        )}
                        aria-hidden
                      />
                      <span
                        className="flex size-9 shrink-0 items-center justify-center rounded-[var(--nf-radius-sm)] bg-[var(--nf-primary-subtle)] text-[var(--nf-primary)]"
                        aria-hidden
                      >
                        <Building2 className="size-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-[var(--nf-text)]">
                          {building.name}
                          <span className="ml-2 font-mono text-xs text-[var(--nf-text-subtle)]">
                            {building.code}
                          </span>
                        </span>
                        <span className="block text-xs text-[var(--nf-text-muted)]">
                          {building.block_count} block(s) · {building.floor_count} floor(s) ·{" "}
                          {building.flat_count} flat(s)
                        </span>
                      </span>
                    </button>

                    {canManage && (
                      <div className="flex shrink-0 items-center gap-1">
                        <NFButton
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Edit ${building.name}`}
                          onClick={() => setDialog({ kind: "building", building })}
                        >
                          <Pencil />
                        </NFButton>
                        <NFButton
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Delete ${building.name}`}
                          onClick={() =>
                            setConfirm({
                              kind: "building",
                              id: building.id,
                              label: building.name,
                            })
                          }
                        >
                          <Trash2 />
                        </NFButton>
                      </div>
                    )}
                  </div>

                  {open && (
                    <div className="space-y-2 border-t border-[var(--nf-border)] bg-[var(--nf-background)] px-5 py-4 sm:pl-14">
                      {blocksFor(building.id).map((block) => (
                        <div
                          key={block.id}
                          className="rounded-[var(--nf-radius)] border border-[var(--nf-border)] bg-[var(--nf-surface)] p-3.5"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="min-w-0">
                              <p className="truncate text-[13px] font-medium text-[var(--nf-text)]">
                                {block.name}
                                <span className="ml-2 font-mono text-[11px] text-[var(--nf-text-subtle)]">
                                  {block.code}
                                </span>
                              </p>
                              <p className="text-xs text-[var(--nf-text-muted)]">
                                {block.floor_count} floor(s) · {block.flat_count} flat(s)
                              </p>
                            </div>
                            {canManage && (
                              <div className="flex items-center gap-1">
                                <NFButton
                                  variant="secondary"
                                  size="sm"
                                  onClick={() => setDialog({ kind: "floors", blockId: block.id })}
                                >
                                  <Plus /> Floors
                                </NFButton>
                                <NFButton
                                  variant="ghost"
                                  size="icon-sm"
                                  aria-label={`Edit ${block.name}`}
                                  onClick={() =>
                                    setDialog({ kind: "block", buildingId: building.id, block })
                                  }
                                >
                                  <Pencil />
                                </NFButton>
                                <NFButton
                                  variant="ghost"
                                  size="icon-sm"
                                  aria-label={`Delete ${block.name}`}
                                  onClick={() =>
                                    setConfirm({ kind: "block", id: block.id, label: block.name })
                                  }
                                >
                                  <Trash2 />
                                </NFButton>
                              </div>
                            )}
                          </div>

                          {floorsFor(block.id).length > 0 && (
                            <div className="mt-3 flex flex-wrap gap-1.5 border-t border-[var(--nf-border)] pt-3">
                              {floorsFor(block.id).map((floor) => (
                                <span
                                  key={floor.id}
                                  className="group inline-flex items-center gap-1.5 rounded-full border border-[var(--nf-border)] bg-[var(--nf-background)] py-1 pl-2.5 pr-1.5 text-[11px] text-[var(--nf-text)]"
                                >
                                  {floor.display_name}
                                  <span className="text-[var(--nf-text-subtle)]">
                                    {floor.flat_count}
                                  </span>
                                  {canManage && (
                                    <button
                                      aria-label={`Delete ${floor.display_name}`}
                                      onClick={() =>
                                        setConfirm({
                                          kind: "floor",
                                          id: floor.id,
                                          label: floor.display_name,
                                        })
                                      }
                                      className="rounded-full p-0.5 text-[var(--nf-text-subtle)] hover:bg-[var(--nf-danger-subtle)] hover:text-[var(--nf-danger)]"
                                    >
                                      <Trash2 className="size-3" />
                                    </button>
                                  )}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}

                      {canManage && (
                        <NFButton
                          variant="ghost"
                          size="sm"
                          onClick={() => setDialog({ kind: "block", buildingId: building.id })}
                        >
                          <Plus /> Add block
                        </NFButton>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </NFCard>

      {summary && summary.flats === 0 && summary.floors > 0 && (
        <NFCard className="mt-5">
          <NFCardBody className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-[var(--nf-text)]">
                Floors are ready — now add the flats
              </p>
              <p className="mt-0.5 text-[13px] text-[var(--nf-text-muted)]">
                Generate a whole block's flats from a numbering pattern in one step.
              </p>
            </div>
            <NFButton asChild variant="secondary">
              <Link to="/app/flats">
                <DoorOpen /> Go to Flats
              </Link>
            </NFButton>
          </NFCardBody>
        </NFCard>
      )}

      <BuildingDialog
        open={dialog?.kind === "building"}
        building={dialog?.kind === "building" ? dialog.building : undefined}
        onClose={() => setDialog(null)}
        onSaved={load}
      />
      <BlockDialog
        open={dialog?.kind === "block"}
        buildingId={dialog?.kind === "block" ? dialog.buildingId : ""}
        block={dialog?.kind === "block" ? dialog.block : undefined}
        onClose={() => setDialog(null)}
        onSaved={load}
      />
      <FloorRangeDialog
        open={dialog?.kind === "floors"}
        blockId={dialog?.kind === "floors" ? dialog.blockId : ""}
        onClose={() => setDialog(null)}
        onSaved={load}
      />

      <NFConfirmDialog
        open={confirm !== null}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={`Delete ${confirm?.label ?? ""}?`}
        description="Anything inside it is removed too. This cannot be undone."
        confirmLabel="Delete"
        destructive
        loading={busy}
        onConfirm={runDelete}
      />
    </>
  );
}

/* -------------------------------------------------------------------------- */

function BuildingDialog({
  open,
  building,
  onClose,
  onSaved,
}: {
  open: boolean;
  building?: Building;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const editing = !!building;
  const [error, setError] = React.useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<{ name: string; code: string; description: string; total_floors: string }>();

  React.useEffect(() => {
    if (open) {
      reset({
        name: building?.name ?? "",
        code: building?.code ?? "",
        description: building?.description ?? "",
        total_floors: building?.total_floors ? String(building.total_floors) : "",
      });
      setError(null);
    }
  }, [open, building, reset]);

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    const body = {
      name: values.name,
      description: values.description || null,
      total_floors: values.total_floors ? Number(values.total_floors) : null,
      ...(editing ? {} : { code: values.code }),
    };
    try {
      if (editing) await api.patch(`/buildings/${building!.id}`, body);
      else await api.post("/buildings", body);
      onClose();
      await onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save this building.");
    }
  });

  return (
    <NFDialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={editing ? "Edit building" : "Add a building"}
      description={
        editing ? undefined : "A default 'Main' block is created with it, ready for floors."
      }
      footer={
        <>
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton onClick={onSubmit} loading={isSubmitting}>
            {editing ? "Save changes" : "Add building"}
          </NFButton>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
          >
            {error}
          </p>
        )}

        <NFField label="Name" htmlFor="b-name" error={errors.name?.message} required>
          <NFInput
            id="b-name"
            placeholder="Tower A"
            invalid={!!errors.name}
            {...register("name", { required: "Enter the building name." })}
          />
        </NFField>

        {!editing && (
          <NFField
            label="Code"
            htmlFor="b-code"
            error={errors.code?.message}
            hint="Short prefix used in flat numbers, e.g. A"
            required
          >
            <NFInput
              id="b-code"
              placeholder="A"
              maxLength={20}
              className="font-mono uppercase"
              invalid={!!errors.code}
              {...register("code", {
                required: "Enter a code.",
                pattern: {
                  value: /^[A-Za-z0-9][A-Za-z0-9-]{0,19}$/,
                  message: "Letters, numbers and hyphens only.",
                },
              })}
            />
          </NFField>
        )}

        <NFField label="Total floors" htmlFor="b-floors" hint="Optional — for reference only">
          <NFInput id="b-floors" type="number" min={1} max={200} {...register("total_floors")} />
        </NFField>

        <NFField label="Description" htmlFor="b-desc">
          <NFTextarea id="b-desc" {...register("description")} />
        </NFField>
      </form>
    </NFDialog>
  );
}

/* -------------------------------------------------------------------------- */

function BlockDialog({
  open,
  buildingId,
  block,
  onClose,
  onSaved,
}: {
  open: boolean;
  buildingId: string;
  block?: Block;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const editing = !!block;
  const [error, setError] = React.useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<{ name: string; code: string }>();

  React.useEffect(() => {
    if (open) {
      reset({ name: block?.name ?? "", code: block?.code ?? "" });
      setError(null);
    }
  }, [open, block, reset]);

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      if (editing) await api.patch(`/blocks/${block!.id}`, { name: values.name });
      else
        await api.post("/blocks", {
          building_id: buildingId,
          name: values.name,
          code: values.code,
        });
      onClose();
      await onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save this block.");
    }
  });

  return (
    <NFDialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={editing ? "Edit block" : "Add a block"}
      description={editing ? undefined : "A wing or section within this building."}
      size="sm"
      footer={
        <>
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton onClick={onSubmit} loading={isSubmitting}>
            {editing ? "Save changes" : "Add block"}
          </NFButton>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
          >
            {error}
          </p>
        )}

        <NFField label="Name" htmlFor="bl-name" error={errors.name?.message} required>
          <NFInput
            id="bl-name"
            placeholder="East Wing"
            invalid={!!errors.name}
            {...register("name", { required: "Enter the block name." })}
          />
        </NFField>

        {!editing && (
          <NFField label="Code" htmlFor="bl-code" error={errors.code?.message} required>
            <NFInput
              id="bl-code"
              placeholder="E"
              maxLength={20}
              className="font-mono uppercase"
              invalid={!!errors.code}
              {...register("code", {
                required: "Enter a code.",
                pattern: {
                  value: /^[A-Za-z0-9][A-Za-z0-9-]{0,19}$/,
                  message: "Letters, numbers and hyphens only.",
                },
              })}
            />
          </NFField>
        )}
      </form>
    </NFDialog>
  );
}

/* -------------------------------------------------------------------------- */

function FloorRangeDialog({
  open,
  blockId,
  onClose,
  onSaved,
}: {
  open: boolean;
  blockId: string;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [error, setError] = React.useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<{ from_number: string; to_number: string }>({
    defaultValues: { from_number: "1", to_number: "10" },
  });

  React.useEffect(() => {
    if (open) {
      reset({ from_number: "1", to_number: "10" });
      setError(null);
    }
  }, [open, reset]);

  const from = Number(watch("from_number"));
  const to = Number(watch("to_number"));
  const count = Number.isFinite(from) && Number.isFinite(to) && to >= from ? to - from + 1 : 0;

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await api.post("/floors/range", {
        block_id: blockId,
        from_number: Number(values.from_number),
        to_number: Number(values.to_number),
      });
      onClose();
      await onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create these floors.");
    }
  });

  return (
    <NFDialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Add floors"
      description="Creates every floor in the range. Existing floors are left alone."
      size="sm"
      footer={
        <>
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton onClick={onSubmit} loading={isSubmitting} disabled={count === 0}>
            Add {count > 0 ? `${count} floor(s)` : "floors"}
          </NFButton>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
          >
            {error}
          </p>
        )}

        <div className="grid grid-cols-2 gap-4">
          <NFField
            label="From"
            htmlFor="f-from"
            error={errors.from_number?.message}
            hint="0 = ground, −1 = basement"
          >
            <NFInput
              id="f-from"
              type="number"
              min={-10}
              max={200}
              invalid={!!errors.from_number}
              {...register("from_number", { required: true })}
            />
          </NFField>
          <NFField label="To" htmlFor="f-to" error={errors.to_number?.message}>
            <NFInput
              id="f-to"
              type="number"
              min={-10}
              max={200}
              invalid={!!errors.to_number}
              {...register("to_number", { required: true })}
            />
          </NFField>
        </div>

        {count > 0 && (
          <p className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-primary-subtle)] px-3 py-2 text-[13px] text-[var(--nf-primary)]">
            {count} floor{count === 1 ? "" : "s"} will be created.
          </p>
        )}
      </form>
    </NFDialog>
  );
}
