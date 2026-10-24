/**
 * Vehicles.
 *
 * A registration number resolves to exactly one flat, which is what makes the
 * gate useful — so the backend refuses a duplicate plate, and this page
 * surfaces that refusal rather than silently creating a second record.
 *
 * A resident may add and remove their own vehicles. The flat picker therefore
 * shows only the flats they hold; an admin sees every flat.
 */

import { Bike, Car, Plus, Trash2 } from "lucide-react";
import * as React from "react";

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
  NFCardBody,
  NFCardHeader,
  NFEmptyState,
  NFField,
  NFInput,
  NFPageHeader,
  NFSelect,
} from "@/components/nestflow/primitives";
import { ApiError, api, type Page } from "@/services/api";
import { useAppSelector } from "@/store";
import type { Flat, ParkingSlot, Vehicle, VehicleType } from "@/types";
import { formatDate } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const VEHICLE_TYPES: { value: VehicleType; label: string }[] = [
  { value: "FOUR_WHEELER", label: "Four wheeler" },
  { value: "TWO_WHEELER", label: "Two wheeler" },
  { value: "BICYCLE", label: "Bicycle" },
  { value: "OTHER", label: "Other" },
];

const TYPE_LABELS = Object.fromEntries(VEHICLE_TYPES.map((t) => [t.value, t.label]));
const LIMIT = 20;

export default function VehiclesPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const canManage = hasPermission(principal, "vehicle.manage");

  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [type, setType] = React.useState<string>("");
  const [vehicles, setVehicles] = React.useState<Page<Vehicle> | null>(null);
  const [flats, setFlats] = React.useState<Flat[]>([]);
  const [slots, setSlots] = React.useState<ParkingSlot[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [addOpen, setAddOpen] = React.useState(false);
  const [removing, setRemoving] = React.useState<Vehicle | null>(null);
  const [reload, setReload] = React.useState(0);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api
      .get<Page<Vehicle>>(
        "/vehicles",
        { page, limit: LIMIT, q: q || undefined, vehicle_type: type || undefined },
        controller.signal,
      )
      .then(setVehicles)
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, q, type, reload]);

  React.useEffect(() => {
    if (!canManage) return;
    const controller = new AbortController();
    api
      .get<Page<Flat>>("/flats", { limit: 100 }, controller.signal)
      .then((r) => setFlats(r.items))
      .catch(() => undefined);
    api
      .get<Page<ParkingSlot>>("/parking/slots", { limit: 100 }, controller.signal)
      .then((r) => setSlots(r.items))
      .catch(() => undefined);
    return () => controller.abort();
  }, [canManage, reload]);

  const counts = React.useMemo(() => {
    const items = vehicles?.items ?? [];
    return {
      four: items.filter((v) => v.vehicle_type === "FOUR_WHEELER").length,
      two: items.filter((v) => v.vehicle_type === "TWO_WHEELER").length,
    };
  }, [vehicles]);

  const columns: Column<Vehicle>[] = [
    {
      key: "registration",
      header: "Registration",
      render: (v) => (
        <span className="font-mono text-[13px] font-semibold uppercase tracking-wide text-[var(--nf-text)]">
          {v.registration_number}
        </span>
      ),
    },
    { key: "type", header: "Type", render: (v) => TYPE_LABELS[v.vehicle_type] ?? v.vehicle_type },
    {
      key: "vehicle",
      header: "Vehicle",
      hideOnMobile: true,
      render: (v) => [v.make, v.model, v.color].filter(Boolean).join(" · ") || "—",
    },
    { key: "flat", header: "Flat", render: (v) => v.flat_number ?? "—" },
    {
      key: "slot",
      header: "Slot",
      hideOnMobile: true,
      render: (v) => v.parking_slot_number ?? "—",
    },
    {
      key: "added",
      header: "Added",
      hideOnMobile: true,
      render: (v) => formatDate(v.created_at),
    },
    ...(canManage
      ? [
          {
            key: "actions",
            header: "",
            className: "text-right",
            render: (v: Vehicle) => (
              <NFButton
                variant="ghost"
                size="sm"
                aria-label={`Remove ${v.registration_number}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setRemoving(v);
                }}
              >
                <Trash2 />
              </NFButton>
            ),
          },
        ]
      : []),
  ];

  return (
    <>
      <NFPageHeader
        title="Vehicles"
        description={
          canManage
            ? "Every vehicle registered in the society, and the flat it belongs to."
            : "The vehicles registered against your flat."
        }
        actions={
          canManage ? (
            <NFButton onClick={() => setAddOpen(true)}>
              <Plus /> Register vehicle
            </NFButton>
          ) : undefined
        }
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <NFStatCard
          label="Registered"
          value={vehicles?.total ?? 0}
          icon={<Car />}
          loading={loading && !vehicles}
        />
        <NFStatCard
          label="Four wheelers"
          value={counts.four}
          hint="on this page"
          icon={<Car />}
          tone="info"
          loading={loading && !vehicles}
        />
        <NFStatCard
          label="Two wheelers"
          value={counts.two}
          hint="on this page"
          icon={<Bike />}
          tone="success"
          loading={loading && !vehicles}
        />
      </div>

      <NFCard className="mt-6">
        <NFCardHeader
          title="Vehicles"
          action={
            <div className="flex flex-wrap items-center gap-2">
              <NFSelect
                aria-label="Vehicle type"
                value={type}
                onChange={(e) => {
                  setType(e.target.value);
                  setPage(1);
                }}
                className="w-40"
              >
                <option value="">All types</option>
                {VEHICLE_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </NFSelect>
              <NFSearch
                value={q}
                onChange={(value) => {
                  setQ(value);
                  setPage(1);
                }}
                placeholder="Search registration"
              />
            </div>
          }
        />
        <NFCardBody className="px-0 pb-0">
          <NFDataTable
            caption="Registered vehicles"
            columns={columns}
            rows={vehicles?.items ?? []}
            rowKey={(v) => v.id}
            loading={loading}
            empty={
              <div className="px-5 pb-5">
                <NFEmptyState
                  title="No vehicles registered"
                  description={
                    canManage
                      ? "Register a vehicle so the gate can match a plate to a flat."
                      : "No vehicle has been registered against your flat yet."
                  }
                />
              </div>
            }
          />
          {vehicles && vehicles.total > 0 && (
            <div className="px-5 py-4">
              <NFPagination
                page={vehicles.page}
                pages={vehicles.pages}
                total={vehicles.total}
                limit={vehicles.limit}
                onPageChange={setPage}
              />
            </div>
          )}
        </NFCardBody>
      </NFCard>

      {canManage && (
        <>
          <AddVehicleDialog
            open={addOpen}
            onOpenChange={setAddOpen}
            flats={flats}
            slots={slots}
            defaultFlatId={principal?.flat_ids[0] ?? ""}
            onSaved={() => {
              setAddOpen(false);
              setReload((n) => n + 1);
            }}
          />
          <NFConfirmDialog
            open={removing !== null}
            onOpenChange={(open) => !open && setRemoving(null)}
            title="Remove this vehicle?"
            description={
              removing
                ? `${removing.registration_number} will no longer be linked to ${
                    removing.flat_number ?? "this flat"
                  }. Its registration becomes available again.`
                : ""
            }
            confirmLabel="Remove"
            destructive
            onConfirm={async () => {
              if (!removing) return;
              await api.delete(`/vehicles/${removing.id}`);
              setRemoving(null);
              setReload((n) => n + 1);
            }}
          />
        </>
      )}
    </>
  );
}

function AddVehicleDialog({
  open,
  onOpenChange,
  flats,
  slots,
  defaultFlatId,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  flats: Flat[];
  slots: ParkingSlot[];
  defaultFlatId: string;
  onSaved: () => void;
}) {
  const [flatId, setFlatId] = React.useState(defaultFlatId);
  const [registration, setRegistration] = React.useState("");
  const [type, setType] = React.useState<VehicleType>("FOUR_WHEELER");
  const [make, setMake] = React.useState("");
  const [model, setModel] = React.useState("");
  const [color, setColor] = React.useState("");
  const [slotId, setSlotId] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setFlatId(defaultFlatId || flats[0]?.id || "");
    setRegistration("");
    setMake("");
    setModel("");
    setColor("");
    setSlotId("");
    setError(null);
  }, [open, defaultFlatId, flats]);

  // Only slots this flat holds, or free ones — offering a neighbour's slot
  // would produce a refusal the user could not have predicted.
  const usableSlots = slots.filter((s) => s.flat_id === null || s.flat_id === flatId);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await api.post("/vehicles", {
        flat_id: flatId,
        registration_number: registration,
        vehicle_type: type,
        make: make || null,
        model: model || null,
        color: color || null,
        parking_slot_id: slotId || null,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not register this vehicle.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <NFDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Register a vehicle"
      description="A registration number can belong to one flat at a time."
      size="lg"
      footer={
        <div className="flex justify-end gap-2">
          <NFButton variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </NFButton>
          <NFButton
            onClick={submit}
            loading={saving}
            disabled={!flatId || registration.trim().length < 4}
          >
            Register
          </NFButton>
        </div>
      }
    >
      <div className="space-y-4">
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
          >
            {error}
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Flat" htmlFor="v-flat" required>
            <NFSelect id="v-flat" value={flatId} onChange={(e) => setFlatId(e.target.value)}>
              {flats.map((flat) => (
                <option key={flat.id} value={flat.id}>
                  {flat.flat_number}
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField label="Registration number" htmlFor="v-reg" required>
            <NFInput
              id="v-reg"
              value={registration}
              onChange={(e) => setRegistration(e.target.value.toUpperCase())}
              placeholder="MH 12 AB 3456"
              className="font-mono uppercase"
              autoFocus
            />
          </NFField>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Type" htmlFor="v-type">
            <NFSelect
              id="v-type"
              value={type}
              onChange={(e) => setType(e.target.value as VehicleType)}
            >
              {VEHICLE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField label="Parking slot" htmlFor="v-slot" hint="Optional">
            <NFSelect id="v-slot" value={slotId} onChange={(e) => setSlotId(e.target.value)}>
              <option value="">No slot</option>
              {usableSlots.map((slot) => (
                <option key={slot.id} value={slot.id}>
                  {slot.slot_number}
                  {slot.flat_id === null ? " · available" : ""}
                </option>
              ))}
            </NFSelect>
          </NFField>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <NFField label="Make" htmlFor="v-make" hint="Optional">
            <NFInput id="v-make" value={make} onChange={(e) => setMake(e.target.value)} />
          </NFField>
          <NFField label="Model" htmlFor="v-model" hint="Optional">
            <NFInput id="v-model" value={model} onChange={(e) => setModel(e.target.value)} />
          </NFField>
          <NFField label="Colour" htmlFor="v-color" hint="Optional">
            <NFInput id="v-color" value={color} onChange={(e) => setColor(e.target.value)} />
          </NFField>
        </div>
      </div>
    </NFDialog>
  );
}
