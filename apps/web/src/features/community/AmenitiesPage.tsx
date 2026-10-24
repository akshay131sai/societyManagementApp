/**
 * Amenities and their bookings.
 *
 * The centre of this screen is a **slot grid**, not a form. A resident picks a
 * facility and a day and taps a cell; there is nowhere to type 10:07, because
 * the server would refuse it and because a grid is how people actually think
 * about the clubhouse.
 *
 * Losing the race is a normal outcome, not an error state. Two people can tap
 * the same 9 a.m. Sunday cell — PostgreSQL refuses the second insert, this
 * screen says so in a sentence and refreshes the grid.
 */

import {
  CalendarDays,
  CheckCircle2,
  Clock,
  IndianRupee,
  Plus,
  Trees,
  XCircle,
} from "lucide-react";
import * as React from "react";

import {
  NFConfirmDialog,
  NFDialog,
  NFPagination,
  NFStatCard,
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
  NFSkeleton,
  NFStatusBadge,
  NFTextarea,
  type BadgeTone,
} from "@/components/nestflow/primitives";
import { ApiError, api, type Page } from "@/services/api";
import { useAppSelector } from "@/store";
import type {
  Amenity,
  AmenityBooking,
  AmenitySlot,
  AmenitySummary,
  Availability,
  BookingStatus,
} from "@/types";
import { cn } from "@/utils/cn";
import { formatCurrency, formatDate, formatDateTime } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const LIMIT = 10;

const STATUS_TONE: Record<BookingStatus, BadgeTone> = {
  PENDING: "warning",
  CONFIRMED: "success",
  CANCELLED: "neutral",
  REJECTED: "danger",
  COMPLETED: "neutral",
  NO_SHOW: "danger",
};

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function AmenitiesPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const canManage = hasPermission(principal, "amenity.manage");
  const canBook = hasPermission(principal, "amenity.book");

  const [amenities, setAmenities] = React.useState<Amenity[]>([]);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [day, setDay] = React.useState(today);
  const [grid, setGrid] = React.useState<Availability | null>(null);
  const [gridLoading, setGridLoading] = React.useState(false);
  const [bookings, setBookings] = React.useState<Page<AmenityBooking> | null>(null);
  const [page, setPage] = React.useState(1);
  const [summary, setSummary] = React.useState<AmenitySummary | null>(null);
  const [booking, setBooking] = React.useState<AmenitySlot | null>(null);
  const [cancelling, setCancelling] = React.useState<AmenityBooking | null>(null);
  const [adding, setAdding] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [reload, setReload] = React.useState(0);

  React.useEffect(() => {
    const controller = new AbortController();
    api
      .get<Page<Amenity>>("/amenities", { limit: 50 }, controller.signal)
      .then((r) => {
        setAmenities(r.items);
        setSelected((current) => current ?? r.items[0]?.id ?? null);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [reload]);

  React.useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    setGridLoading(true);
    api
      .get<Availability>(`/amenities/${selected}/availability`, { on: day }, controller.signal)
      .then(setGrid)
      .catch(() => undefined)
      .finally(() => setGridLoading(false));
    return () => controller.abort();
  }, [selected, day, reload]);

  React.useEffect(() => {
    const controller = new AbortController();
    api
      .get<Page<AmenityBooking>>(
        "/amenities/bookings",
        { page, limit: LIMIT, upcoming_only: true },
        controller.signal,
      )
      .then(setBookings)
      .catch(() => undefined);
    return () => controller.abort();
  }, [page, reload]);

  React.useEffect(() => {
    if (!canManage) return;
    const controller = new AbortController();
    api
      .get<AmenitySummary>("/amenities/summary", undefined, controller.signal)
      .then(setSummary)
      .catch(() => undefined);
    return () => controller.abort();
  }, [canManage, reload]);

  const amenity = amenities.find((a) => a.id === selected) ?? null;

  async function decide(id: string, approved: boolean) {
    await api
      .post(`/amenities/bookings/${id}/decision`, {
        approved,
        reason: approved ? null : "Not available.",
      })
      .catch(() => undefined);
    setReload((n) => n + 1);
  }

  return (
    <>
      <NFPageHeader
        title="Amenities"
        description="The clubhouse, the lawn, the courts — and who has them when."
        actions={
          canManage ? (
            <NFButton onClick={() => setAdding(true)}>
              <Plus /> Add an amenity
            </NFButton>
          ) : undefined
        }
      />

      {notice && (
        <div className="mb-6 flex items-start justify-between gap-3 rounded-[var(--nf-radius)] border border-[var(--nf-warning)]/30 bg-[var(--nf-warning-subtle)] p-4">
          <p className="text-[13px] text-[var(--nf-text)]">{notice}</p>
          <button
            type="button"
            onClick={() => setNotice(null)}
            className="text-[11px] font-semibold text-[var(--nf-warning)]"
          >
            Dismiss
          </button>
        </div>
      )}

      {canManage && summary && (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <NFStatCard label="Facilities" value={summary.amenities} icon={<Trees />} tone="primary" />
          <NFStatCard
            label="Booked today"
            value={summary.bookings_today}
            icon={<CalendarDays />}
            tone="info"
            hint={`${summary.upcoming} upcoming`}
          />
          <NFStatCard
            label="Awaiting approval"
            value={summary.pending_approval}
            icon={<Clock />}
            tone={summary.pending_approval > 0 ? "warning" : "success"}
          />
          <NFStatCard
            label="Revenue this month"
            value={formatCurrency(summary.revenue_this_month)}
            icon={<IndianRupee />}
            tone="success"
          />
        </div>
      )}

      {amenities.length === 0 ? (
        <NFEmptyState
          icon={<Trees />}
          title="No amenities yet"
          description={
            canManage
              ? "Add the clubhouse or the lawn and residents can start booking slots."
              : "The society has not set up any bookable facilities."
          }
        />
      ) : (
        <NFCard className="mb-6">
          <NFCardHeader
            title="Availability"
            description={
              amenity
                ? `${amenity.opens_at.slice(0, 5)}–${amenity.closes_at.slice(0, 5)} · ${amenity.slot_minutes} minute slots · ${
                    Number(amenity.booking_charge) === 0
                      ? "no charge"
                      : `${formatCurrency(amenity.booking_charge)} a slot`
                  }`
                : undefined
            }
            action={
              <div className="flex flex-wrap items-center gap-2">
                <NFSelect
                  aria-label="Amenity"
                  value={selected ?? ""}
                  onChange={(e) => setSelected(e.target.value)}
                  className="sm:w-48"
                >
                  {amenities.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </NFSelect>
                <NFInput
                  type="date"
                  aria-label="Date"
                  value={day}
                  min={today()}
                  onChange={(e) => setDay(e.target.value)}
                  className="sm:w-40"
                />
              </div>
            }
          />
          <NFCardBody>
            {gridLoading ? (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
                {Array.from({ length: 12 }).map((_, i) => (
                  <NFSkeleton key={i} className="h-14" />
                ))}
              </div>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
                  {(grid?.slots ?? []).map((slot) => {
                    const taken = !slot.available;
                    return (
                      <button
                        key={slot.starts_at}
                        type="button"
                        disabled={taken || !canBook}
                        onClick={() => setBooking(slot)}
                        className={cn(
                          "rounded-[var(--nf-radius-sm)] border px-2 py-2.5 text-center transition-colors",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--nf-ring)]",
                          slot.is_own
                            ? "border-[var(--nf-primary)] bg-[var(--nf-primary-subtle)]"
                            : taken
                              ? "cursor-not-allowed border-[var(--nf-border)] bg-[var(--nf-background)] opacity-60"
                              : "border-[var(--nf-border)] hover:border-[var(--nf-primary)] hover:bg-[var(--nf-primary-subtle)]",
                        )}
                      >
                        <span className="block text-[13px] font-medium text-[var(--nf-text)]">
                          {slot.label}
                        </span>
                        <span className="mt-0.5 block text-[11px] text-[var(--nf-text-muted)]">
                          {slot.is_own
                            ? "Yours"
                            : taken
                              ? (slot.booked_by_flat ?? "Booked")
                              : "Free"}
                        </span>
                      </button>
                    );
                  })}
                </div>
                {!canBook && (
                  <p className="mt-3 text-[11px] text-[var(--nf-text-subtle)]">
                    You can see availability but not book — ask the office.
                  </p>
                )}
              </>
            )}
          </NFCardBody>
        </NFCard>
      )}

      <NFCard>
        <NFCardHeader
          title="Upcoming bookings"
          description={canManage ? "Everyone's." : "Your flat's."}
        />
        <NFCardBody className="px-0 pb-0">
          {(bookings?.items.length ?? 0) === 0 ? (
            <div className="px-5 pb-5">
              <NFEmptyState
                icon={<CalendarDays />}
                title="Nothing booked"
                description="Pick a free slot above."
              />
            </div>
          ) : (
            <ul className="divide-y divide-[var(--nf-border)]">
              {bookings!.items.map((b) => (
                <li
                  key={b.id}
                  className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5"
                >
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-medium text-[var(--nf-text)]">
                      {b.amenity_name ?? "Amenity"}
                      <span className="ml-2 font-normal text-[var(--nf-text-muted)]">
                        {formatDate(b.booking_date)} ·{" "}
                        {formatDateTime(b.starts_at).split(", ").pop()}–
                        {formatDateTime(b.ends_at).split(", ").pop()}
                      </span>
                    </p>
                    <p className="mt-0.5 text-[11px] text-[var(--nf-text-subtle)]">
                      {b.flat_number ?? "—"} · {b.booked_by_name}
                      {Number(b.charge) > 0 && ` · ${formatCurrency(b.charge)}`}
                      {b.guests > 0 && ` · ${b.guests} guest${b.guests === 1 ? "" : "s"}`}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <NFStatusBadge status={b.status} tone={STATUS_TONE[b.status]} />
                    {canManage && b.status === "PENDING" && (
                      <>
                        <NFButton size="sm" onClick={() => decide(b.id, true)}>
                          <CheckCircle2 /> Approve
                        </NFButton>
                        <NFButton
                          size="sm"
                          variant="secondary"
                          onClick={() => decide(b.id, false)}
                        >
                          <XCircle /> Reject
                        </NFButton>
                      </>
                    )}
                    {b.can_cancel && (
                      <NFButton size="sm" variant="ghost" onClick={() => setCancelling(b)}>
                        Cancel
                      </NFButton>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
          {bookings && bookings.total > LIMIT && (
            <div className="px-5 py-4">
              <NFPagination
                page={bookings.page}
                pages={bookings.pages}
                total={bookings.total}
                limit={bookings.limit}
                onPageChange={setPage}
              />
            </div>
          )}
        </NFCardBody>
      </NFCard>

      {booking && amenity && (
        <BookDialog
          amenity={amenity}
          slot={booking}
          onClose={() => setBooking(null)}
          onDone={(message) => {
            setBooking(null);
            if (message) setNotice(message);
            setReload((n) => n + 1);
          }}
        />
      )}

      <NFConfirmDialog
        open={cancelling !== null}
        onOpenChange={(open) => !open && setCancelling(null)}
        title="Cancel this booking?"
        description={
          cancelling
            ? `The slot goes back into the pool for anyone to take.`
            : ""
        }
        confirmLabel="Cancel booking"
        destructive
        onConfirm={async () => {
          if (!cancelling) return;
          await api
            .post(`/amenities/bookings/${cancelling.id}/cancellation`, { reason: null })
            .catch(() => undefined);
          setCancelling(null);
          setReload((n) => n + 1);
        }}
      />

      {canManage && (
        <AmenityDialog
          open={adding}
          onOpenChange={setAdding}
          onSaved={() => {
            setAdding(false);
            setReload((n) => n + 1);
          }}
        />
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */

function BookDialog({
  amenity,
  slot,
  onClose,
  onDone,
}: {
  amenity: Amenity;
  slot: AmenitySlot;
  onClose: () => void;
  onDone: (message?: string) => void;
}) {
  const [slots, setSlots] = React.useState(1);
  const [guests, setGuests] = React.useState("0");
  const [purpose, setPurpose] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const charge = Number(amenity.booking_charge) * slots;

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await api.post("/amenities/bookings", {
        amenity_id: amenity.id,
        starts_at: slot.starts_at,
        slots,
        guests: Number(guests) || 0,
        purpose: purpose || null,
      });
      onDone(
        amenity.requires_approval
          ? "Booking requested. You will be told once it is approved."
          : undefined,
      );
    } catch (e) {
      const message =
        e instanceof ApiError ? e.message : "Could not book this slot.";
      // A lost race is an ordinary outcome, not a failure of the app: somebody
      // else got there first, and the grid behind this dialog is now stale.
      if (e instanceof ApiError && e.status === 409) onDone(message);
      else setError(message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <NFDialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={`Book ${amenity.name}`}
      description={`${formatDate(slot.starts_at)} · from ${slot.label.split("–")[0]}`}
      footer={
        <div className="flex justify-end gap-2">
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton onClick={submit} loading={saving}>
            {amenity.requires_approval ? "Request" : "Book"}
            {charge > 0 && ` · ${formatCurrency(charge)}`}
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
          <NFField
            label="How long?"
            htmlFor="b-slots"
            hint={`Up to ${amenity.max_slots_per_booking} slot(s)`}
          >
            <NFSelect
              id="b-slots"
              value={String(slots)}
              onChange={(e) => setSlots(Number(e.target.value))}
            >
              {Array.from({ length: amenity.max_slots_per_booking }).map((_, i) => (
                <option key={i} value={i + 1}>
                  {(i + 1) * amenity.slot_minutes} minutes
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField label="Guests" htmlFor="b-guests" hint="Optional">
            <NFInput
              id="b-guests"
              type="number"
              min="0"
              value={guests}
              onChange={(e) => setGuests(e.target.value)}
            />
          </NFField>
        </div>

        <NFField label="What for?" htmlFor="b-purpose" hint="Optional">
          <NFInput
            id="b-purpose"
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            placeholder="Birthday party"
          />
        </NFField>

        {amenity.rules && (
          <div className="rounded-[var(--nf-radius-sm)] border border-[var(--nf-border)] bg-[var(--nf-background)] px-3 py-2.5">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--nf-text-muted)]">
              House rules
            </p>
            <p className="mt-1 whitespace-pre-wrap text-[13px] text-[var(--nf-text)]">
              {amenity.rules}
            </p>
          </div>
        )}
      </div>
    </NFDialog>
  );
}

function AmenityDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const [name, setName] = React.useState("");
  const [opens, setOpens] = React.useState("06:00");
  const [closes, setCloses] = React.useState("22:00");
  const [slotMinutes, setSlotMinutes] = React.useState("60");
  const [charge, setCharge] = React.useState("0");
  const [requiresApproval, setRequiresApproval] = React.useState(false);
  const [rules, setRules] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setName("");
    setRules("");
    setError(null);
  }, [open]);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await api.post("/amenities", {
        name,
        opens_at: `${opens}:00`,
        closes_at: `${closes}:00`,
        slot_minutes: Number(slotMinutes),
        booking_charge: charge || "0",
        requires_approval: requiresApproval,
        rules: rules || null,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not add this amenity.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <NFDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add an amenity"
      footer={
        <div className="flex justify-end gap-2">
          <NFButton variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </NFButton>
          <NFButton onClick={submit} loading={saving} disabled={!name.trim()}>
            Add
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

        <NFField label="Name" htmlFor="a-name" required>
          <NFInput
            id="a-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Clubhouse"
            autoFocus
          />
        </NFField>

        <div className="grid gap-4 sm:grid-cols-3">
          <NFField label="Opens" htmlFor="a-open">
            <NFInput
              id="a-open"
              type="time"
              value={opens}
              onChange={(e) => setOpens(e.target.value)}
            />
          </NFField>
          <NFField label="Closes" htmlFor="a-close">
            <NFInput
              id="a-close"
              type="time"
              value={closes}
              onChange={(e) => setCloses(e.target.value)}
            />
          </NFField>
          <NFField
            label="Slot length"
            htmlFor="a-slot"
            hint="Minutes. 1440 for a whole day."
          >
            <NFInput
              id="a-slot"
              type="number"
              min="15"
              max="1440"
              step="15"
              value={slotMinutes}
              onChange={(e) => setSlotMinutes(e.target.value)}
            />
          </NFField>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Charge per slot" htmlFor="a-charge" hint="Zero if it is included">
            <NFInput
              id="a-charge"
              type="number"
              min="0"
              step="1"
              value={charge}
              onChange={(e) => setCharge(e.target.value)}
            />
          </NFField>
          <NFField label="Approval" htmlFor="a-approve">
            <label className="flex h-10 items-center gap-2 text-[13px] text-[var(--nf-text)]">
              <input
                id="a-approve"
                type="checkbox"
                checked={requiresApproval}
                onChange={(e) => setRequiresApproval(e.target.checked)}
                className="accent-[var(--nf-primary)]"
              />
              A booking waits for the office
            </label>
          </NFField>
        </div>

        <NFField label="House rules" htmlFor="a-rules" hint="Shown before someone books.">
          <NFTextarea
            id="a-rules"
            rows={3}
            value={rules}
            onChange={(e) => setRules(e.target.value)}
          />
        </NFField>
      </div>
    </NFDialog>
  );
}
