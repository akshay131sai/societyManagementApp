/**
 * Parking slots.
 *
 * A slot is a shared society resource, so allotment is an admin action even
 * though the vehicle standing in it belongs to a resident. A resident opening
 * this page sees only the slots allotted to their own flat — the backend
 * narrows the list, and the page simply offers no allotment controls.
 */

import { CircleParking, Plus, SquareParking } from "lucide-react";
import * as React from "react";

import { NFDataTable, NFDialog, NFPagination, NFSearch, NFStatCard, type Column } from "@/components/nestflow/data";
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
import type { Flat, ParkingSlot, ParkingSummary, SlotType } from "@/types";
import { formatCurrency } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const SLOT_TYPES: { value: SlotType; label: string }[] = [
  { value: "FOUR_WHEELER", label: "Four wheeler" },
  { value: "TWO_WHEELER", label: "Two wheeler" },
  { value: "VISITOR", label: "Visitor" },
  { value: "HANDICAPPED", label: "Accessible" },
];

const TYPE_LABELS = Object.fromEntries(SLOT_TYPES.map((t) => [t.value, t.label]));
const LIMIT = 20;

export default function ParkingPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const canManage = hasPermission(principal, "parking.manage");

  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [unallottedOnly, setUnallottedOnly] = React.useState(false);
  const [slots, setSlots] = React.useState<Page<ParkingSlot> | null>(null);
  const [summary, setSummary] = React.useState<ParkingSummary | null>(null);
  const [flats, setFlats] = React.useState<Flat[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [allotting, setAllotting] = React.useState<ParkingSlot | null>(null);
  const [reload, setReload] = React.useState(0);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api
      .get<Page<ParkingSlot>>(
        "/parking/slots",
        { page, limit: LIMIT, q: q || undefined, unallotted_only: unallottedOnly || undefined },
        controller.signal,
      )
      .then(setSlots)
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, q, unallottedOnly, reload]);

  React.useEffect(() => {
    if (!canManage) return;
    const controller = new AbortController();
    api
      .get<ParkingSummary>("/parking/summary", undefined, controller.signal)
      .then(setSummary)
      .catch(() => undefined);
    api
      .get<Page<Flat>>("/flats", { limit: 100 }, controller.signal)
      .then((r) => setFlats(r.items))
      .catch(() => undefined);
    return () => controller.abort();
  }, [canManage, reload]);

  const columns: Column<ParkingSlot>[] = [
    {
      key: "slot",
      header: "Slot",
      render: (s) => (
        <span className="font-semibold text-[var(--nf-text)]">{s.slot_number}</span>
      ),
    },
    { key: "type", header: "Type", render: (s) => TYPE_LABELS[s.slot_type] ?? s.slot_type },
    { key: "level", header: "Level", hideOnMobile: true, render: (s) => s.level ?? "—" },
    {
      key: "flat",
      header: "Allotted to",
      render: (s) =>
        s.flat_number ? (
          <span className="text-[var(--nf-text)]">{s.flat_number}</span>
        ) : (
          <span className="text-[var(--nf-text-subtle)]">Available</span>
        ),
    },
    {
      key: "charge",
      header: "Monthly",
      hideOnMobile: true,
      className: "text-right tabular-nums",
      headerClassName: "text-right",
      render: (s) => formatCurrency(s.monthly_charge),
    },
    ...(canManage
      ? [
          {
            key: "actions",
            header: "",
            className: "text-right",
            render: (s: ParkingSlot) => (
              <NFButton
                variant="ghost"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  setAllotting(s);
                }}
              >
                {s.flat_id ? "Reallot" : "Allot"}
              </NFButton>
            ),
          },
        ]
      : []),
  ];

  return (
    <>
      <NFPageHeader
        title="Parking"
        description={
          canManage
            ? "Slots, their monthly charge and which flat holds each one."
            : "The parking allotted to your flat."
        }
        actions={
          canManage ? (
            <NFButton onClick={() => setCreateOpen(true)}>
              <Plus /> Add slot
            </NFButton>
          ) : undefined
        }
      />

      {canManage && (
        <div className="grid gap-4 sm:grid-cols-3">
          <NFStatCard
            label="Total slots"
            value={summary?.total ?? 0}
            icon={<SquareParking />}
            loading={!summary}
          />
          <NFStatCard
            label="Allotted"
            value={summary?.allotted ?? 0}
            hint={summary ? `${summary.total - summary.allotted} free` : undefined}
            icon={<CircleParking />}
            tone="success"
            loading={!summary}
          />
          <NFStatCard
            label="Available"
            value={summary?.available ?? 0}
            icon={<CircleParking />}
            tone={summary && summary.available === 0 ? "warning" : "info"}
            loading={!summary}
          />
        </div>
      )}

      <NFCard className={canManage ? "mt-6" : ""}>
        <NFCardHeader
          title="Slots"
          action={
            <div className="flex flex-wrap items-center gap-2">
              {canManage && (
                <label className="flex items-center gap-2 text-[13px] text-[var(--nf-text-muted)]">
                  <input
                    type="checkbox"
                    className="size-3.5 accent-[var(--nf-primary)]"
                    checked={unallottedOnly}
                    onChange={(e) => {
                      setUnallottedOnly(e.target.checked);
                      setPage(1);
                    }}
                  />
                  Available only
                </label>
              )}
              <NFSearch
                value={q}
                onChange={(value) => {
                  setQ(value);
                  setPage(1);
                }}
                placeholder="Search slot number"
              />
            </div>
          }
        />
        <NFCardBody className="px-0 pb-0">
          <NFDataTable
            caption="Parking slots"
            columns={columns}
            rows={slots?.items ?? []}
            rowKey={(s) => s.id}
            loading={loading}
            empty={
              <div className="px-5 pb-5">
                <NFEmptyState
                  title="No parking slots"
                  description={
                    canManage
                      ? "Add the society's slots so they can be allotted to flats."
                      : "No slot has been allotted to your flat yet."
                  }
                />
              </div>
            }
          />
          {slots && slots.total > 0 && (
            <div className="px-5 py-4">
              <NFPagination
                page={slots.page}
                pages={slots.pages}
                total={slots.total}
                limit={slots.limit}
                onPageChange={setPage}
              />
            </div>
          )}
        </NFCardBody>
      </NFCard>

      {canManage && (
        <>
          <CreateSlotDialog
            open={createOpen}
            onOpenChange={setCreateOpen}
            onSaved={() => {
              setCreateOpen(false);
              setReload((n) => n + 1);
            }}
          />
          <AllotDialog
            slot={allotting}
            flats={flats}
            onClose={() => setAllotting(null)}
            onSaved={() => {
              setAllotting(null);
              setReload((n) => n + 1);
            }}
          />
        </>
      )}
    </>
  );
}

function CreateSlotDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const [slotNumber, setSlotNumber] = React.useState("");
  const [level, setLevel] = React.useState("");
  const [slotType, setSlotType] = React.useState<SlotType>("FOUR_WHEELER");
  const [charge, setCharge] = React.useState("0");
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setSlotNumber("");
      setLevel("");
      setCharge("0");
      setError(null);
    }
  }, [open]);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await api.post("/parking/slots", {
        slot_number: slotNumber,
        level: level || null,
        slot_type: slotType,
        monthly_charge: charge || "0",
      });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create this slot.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <NFDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add a parking slot"
      description="Slot numbers are unique across the society."
      footer={
        <div className="flex justify-end gap-2">
          <NFButton variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </NFButton>
          <NFButton onClick={submit} loading={saving} disabled={!slotNumber.trim()}>
            Add slot
          </NFButton>
        </div>
      }
    >
      <div className="space-y-4">
        <NFField label="Slot number" htmlFor="slot-number" required error={error ?? undefined}>
          <NFInput
            id="slot-number"
            value={slotNumber}
            onChange={(e) => setSlotNumber(e.target.value)}
            placeholder="B1-014"
            autoFocus
          />
        </NFField>
        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Type" htmlFor="slot-type">
            <NFSelect
              id="slot-type"
              value={slotType}
              onChange={(e) => setSlotType(e.target.value as SlotType)}
            >
              {SLOT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField label="Level" htmlFor="slot-level" hint="Optional">
            <NFInput
              id="slot-level"
              value={level}
              onChange={(e) => setLevel(e.target.value)}
              placeholder="Basement 1"
            />
          </NFField>
        </div>
        <NFField
          label="Monthly charge"
          htmlFor="slot-charge"
          hint="Billed through the parking charge field in your bill formula."
        >
          <NFInput
            id="slot-charge"
            type="number"
            min="0"
            step="1"
            value={charge}
            onChange={(e) => setCharge(e.target.value)}
          />
        </NFField>
      </div>
    </NFDialog>
  );
}

function AllotDialog({
  slot,
  flats,
  onClose,
  onSaved,
}: {
  slot: ParkingSlot | null;
  flats: Flat[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [flatId, setFlatId] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    setFlatId(slot?.flat_id ?? "");
    setError(null);
  }, [slot]);

  async function save(nextFlatId: string | null) {
    if (!slot) return;
    setSaving(true);
    setError(null);
    try {
      await api.post(`/parking/slots/${slot.id}/allotment`, { flat_id: nextFlatId });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not update this allotment.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <NFDialog
      open={slot !== null}
      onOpenChange={(open) => !open && onClose()}
      title={slot ? `Slot ${slot.slot_number}` : "Allotment"}
      description="An allotted slot must be released before it can go to another flat."
      footer={
        <div className="flex w-full flex-wrap justify-between gap-2">
          {slot?.flat_id ? (
            <NFButton variant="secondary" onClick={() => save(null)} loading={saving}>
              Release
            </NFButton>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <NFButton variant="secondary" onClick={onClose}>
              Cancel
            </NFButton>
            <NFButton onClick={() => save(flatId)} loading={saving} disabled={!flatId}>
              Allot
            </NFButton>
          </div>
        </div>
      }
    >
      <NFField label="Flat" htmlFor="allot-flat" error={error ?? undefined}>
        <NFSelect id="allot-flat" value={flatId} onChange={(e) => setFlatId(e.target.value)}>
          <option value="">Select a flat…</option>
          {flats.map((flat) => (
            <option key={flat.id} value={flat.id}>
              {flat.flat_number}
              {flat.building_name ? ` · ${flat.building_name}` : ""}
            </option>
          ))}
        </NFSelect>
      </NFField>
    </NFDialog>
  );
}
