/**
 * Pets.
 *
 * Registered per flat, with an optional monthly fee that the billing engine
 * reads through the `pet_fee_total` field — which is why the fee lives here
 * rather than being re-entered on every bill.
 *
 * An expired vaccination is called out on the row: it is the one fact on this
 * screen that needs someone to act.
 */

import { Bird, Cat, Dog, Plus, Trash2, TriangleAlert } from "lucide-react";
import * as React from "react";

import {
  NFConfirmDialog,
  NFDataTable,
  NFDialog,
  NFPagination,
  NFSearch,
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
import type { Flat, Pet, PetType } from "@/types";
import { formatCurrency, formatDate } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const PET_TYPES: { value: PetType; label: string; icon: React.ReactNode }[] = [
  { value: "DOG", label: "Dog", icon: <Dog /> },
  { value: "CAT", label: "Cat", icon: <Cat /> },
  { value: "BIRD", label: "Bird", icon: <Bird /> },
  { value: "OTHER", label: "Other", icon: <Dog /> },
];

const TYPE_LABELS = Object.fromEntries(PET_TYPES.map((t) => [t.value, t.label]));
const LIMIT = 20;

export default function PetsPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const canManage = hasPermission(principal, "pet.manage");

  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [pets, setPets] = React.useState<Page<Pet> | null>(null);
  const [flats, setFlats] = React.useState<Flat[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [addOpen, setAddOpen] = React.useState(false);
  const [removing, setRemoving] = React.useState<Pet | null>(null);
  const [reload, setReload] = React.useState(0);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api
      .get<Page<Pet>>("/pets", { page, limit: LIMIT, q: q || undefined }, controller.signal)
      .then(setPets)
      .catch(() => undefined)
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, q, reload]);

  React.useEffect(() => {
    if (!canManage) return;
    const controller = new AbortController();
    api
      .get<Page<Flat>>("/flats", { limit: 100 }, controller.signal)
      .then((r) => setFlats(r.items))
      .catch(() => undefined);
    return () => controller.abort();
  }, [canManage, reload]);

  const columns: Column<Pet>[] = [
    {
      key: "name",
      header: "Name",
      render: (p) => <span className="font-medium text-[var(--nf-text)]">{p.name}</span>,
    },
    { key: "type", header: "Type", render: (p) => TYPE_LABELS[p.pet_type] ?? p.pet_type },
    { key: "breed", header: "Breed", hideOnMobile: true, render: (p) => p.breed ?? "—" },
    { key: "flat", header: "Flat", render: (p) => p.flat_number ?? "—" },
    {
      key: "vaccination",
      header: "Vaccination",
      hideOnMobile: true,
      render: (p) =>
        p.vaccination_expiry == null ? (
          <span className="text-[var(--nf-text-subtle)]">Not recorded</span>
        ) : p.vaccination_due ? (
          <span className="inline-flex items-center gap-1.5 text-[var(--nf-warning)]">
            <TriangleAlert className="size-3.5" aria-hidden />
            Due {formatDate(p.vaccination_expiry)}
          </span>
        ) : (
          <span className="text-[var(--nf-text-muted)]">
            Valid to {formatDate(p.vaccination_expiry)}
          </span>
        ),
    },
    {
      key: "fee",
      header: "Monthly fee",
      hideOnMobile: true,
      className: "text-right tabular-nums",
      headerClassName: "text-right",
      render: (p) => (Number(p.monthly_fee) === 0 ? "—" : formatCurrency(p.monthly_fee)),
    },
    ...(canManage
      ? [
          {
            key: "actions",
            header: "",
            className: "text-right",
            render: (p: Pet) => (
              <NFButton
                variant="ghost"
                size="sm"
                aria-label={`Remove ${p.name}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setRemoving(p);
                }}
              >
                <Trash2 />
              </NFButton>
            ),
          },
        ]
      : []),
  ];

  const overdue = (pets?.items ?? []).filter((p) => p.vaccination_due).length;

  return (
    <>
      <NFPageHeader
        title="Pets"
        description={
          canManage
            ? "Pets registered in the society, with their vaccination status."
            : "The pets registered against your flat."
        }
        actions={
          canManage ? (
            <NFButton onClick={() => setAddOpen(true)}>
              <Plus /> Register pet
            </NFButton>
          ) : undefined
        }
      />

      {overdue > 0 && (
        <div className="mb-6 flex items-start gap-2.5 rounded-[var(--nf-radius)] border border-[var(--nf-warning)]/30 bg-[var(--nf-warning-subtle)] p-4">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-[var(--nf-warning)]" aria-hidden />
          <p className="text-[13px] text-[var(--nf-text)]">
            <span className="font-semibold text-[var(--nf-warning)]">
              {overdue} pet{overdue === 1 ? "" : "s"}
            </span>{" "}
            {overdue === 1 ? "has" : "have"} an expired vaccination record.
          </p>
        </div>
      )}

      <NFCard>
        <NFCardHeader
          title="Registered pets"
          action={
            <NFSearch
              value={q}
              onChange={(value) => {
                setQ(value);
                setPage(1);
              }}
              placeholder="Search by name"
            />
          }
        />
        <NFCardBody className="px-0 pb-0">
          <NFDataTable
            caption="Registered pets"
            columns={columns}
            rows={pets?.items ?? []}
            rowKey={(p) => p.id}
            loading={loading}
            empty={
              <div className="px-5 pb-5">
                <NFEmptyState
                  title="No pets registered"
                  description={
                    canManage
                      ? "Register a pet to keep its vaccination record and fee with the flat."
                      : "No pet has been registered against your flat yet."
                  }
                />
              </div>
            }
          />
          {pets && pets.total > 0 && (
            <div className="px-5 py-4">
              <NFPagination
                page={pets.page}
                pages={pets.pages}
                total={pets.total}
                limit={pets.limit}
                onPageChange={setPage}
              />
            </div>
          )}
        </NFCardBody>
      </NFCard>

      {canManage && (
        <>
          <AddPetDialog
            open={addOpen}
            onOpenChange={setAddOpen}
            flats={flats}
            defaultFlatId={principal?.flat_ids[0] ?? ""}
            onSaved={() => {
              setAddOpen(false);
              setReload((n) => n + 1);
            }}
          />
          <NFConfirmDialog
            open={removing !== null}
            onOpenChange={(open) => !open && setRemoving(null)}
            title="Remove this pet?"
            description={
              removing ? `${removing.name} will no longer be registered to this flat.` : ""
            }
            confirmLabel="Remove"
            destructive
            onConfirm={async () => {
              if (!removing) return;
              await api.delete(`/pets/${removing.id}`);
              setRemoving(null);
              setReload((n) => n + 1);
            }}
          />
        </>
      )}
    </>
  );
}

function AddPetDialog({
  open,
  onOpenChange,
  flats,
  defaultFlatId,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  flats: Flat[];
  defaultFlatId: string;
  onSaved: () => void;
}) {
  const [flatId, setFlatId] = React.useState(defaultFlatId);
  const [name, setName] = React.useState("");
  const [type, setType] = React.useState<PetType>("DOG");
  const [breed, setBreed] = React.useState("");
  const [expiry, setExpiry] = React.useState("");
  const [fee, setFee] = React.useState("0");
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setFlatId(defaultFlatId || flats[0]?.id || "");
    setName("");
    setBreed("");
    setExpiry("");
    setFee("0");
    setError(null);
  }, [open, defaultFlatId, flats]);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await api.post("/pets", {
        flat_id: flatId,
        name,
        pet_type: type,
        breed: breed || null,
        vaccination_expiry: expiry || null,
        monthly_fee: fee || "0",
      });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not register this pet.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <NFDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Register a pet"
      footer={
        <div className="flex justify-end gap-2">
          <NFButton variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </NFButton>
          <NFButton onClick={submit} loading={saving} disabled={!flatId || !name.trim()}>
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
          <NFField label="Flat" htmlFor="p-flat" required>
            <NFSelect id="p-flat" value={flatId} onChange={(e) => setFlatId(e.target.value)}>
              {flats.map((flat) => (
                <option key={flat.id} value={flat.id}>
                  {flat.flat_number}
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField label="Name" htmlFor="p-name" required>
            <NFInput
              id="p-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </NFField>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Type" htmlFor="p-type">
            <NFSelect id="p-type" value={type} onChange={(e) => setType(e.target.value as PetType)}>
              {PET_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField label="Breed" htmlFor="p-breed" hint="Optional">
            <NFInput id="p-breed" value={breed} onChange={(e) => setBreed(e.target.value)} />
          </NFField>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Vaccination valid to" htmlFor="p-expiry" hint="Optional">
            <NFInput
              id="p-expiry"
              type="date"
              value={expiry}
              onChange={(e) => setExpiry(e.target.value)}
            />
          </NFField>
          <NFField label="Monthly fee" htmlFor="p-fee" hint="Charged through the bill formula">
            <NFInput
              id="p-fee"
              type="number"
              min="0"
              step="1"
              value={fee}
              onChange={(e) => setFee(e.target.value)}
            />
          </NFField>
        </div>
      </div>
    </NFDialog>
  );
}
