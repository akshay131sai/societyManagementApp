/**
 * My Family — the flat admin's household roster.
 *
 * This screen belongs to the resident, not the society. It lists the people in
 * *their* flat and hands out app logins to them. Everything it reads is already
 * narrowed server-side by `principal.flat_ids`, so there is no flat filter here
 * and no way to page into a neighbour's household.
 *
 * Access is granted by email only. No password is set or collected anywhere —
 * the account is created with a placeholder identity that binds on first
 * sign-in.
 */

import { KeyRound, ShieldOff, Trash2, UserPlus, UsersRound } from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";

import { NFConfirmDialog, NFDialog } from "@/components/nestflow/data";
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
import {
  FAMILY_ACCESS_LEVELS,
  FAMILY_RELATIONSHIPS,
  type FamilyAccessLevel,
  type FamilyMember,
  type FamilyRelationship,
  type Resident,
} from "@/types";
import { formatDate } from "@/utils/format";

const ACCESS_TONE: Record<FamilyAccessLevel, "success" | "info" | "neutral" | "warning"> = {
  CO_ADMIN: "success",
  MEMBER: "info",
  CHILD: "warning",
  NONE: "neutral",
};

function accessLabel(level: FamilyAccessLevel): string {
  return FAMILY_ACCESS_LEVELS.find((l) => l.value === level)?.label ?? "No app access";
}

function relationshipLabel(value: FamilyRelationship): string {
  return FAMILY_RELATIONSHIPS.find((r) => r.value === value)?.label ?? value;
}

interface AddForm {
  full_name: string;
  relationship_to_resident: FamilyRelationship | "";
  date_of_birth: string;
  phone: string;
}

export default function FamilyPage() {
  const [resident, setResident] = React.useState<Resident | null>(null);
  const [members, setMembers] = React.useState<FamilyMember[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const [adding, setAdding] = React.useState(false);
  const [granting, setGranting] = React.useState<FamilyMember | null>(null);
  const [revoking, setRevoking] = React.useState<FamilyMember | null>(null);
  const [removing, setRemoving] = React.useState<FamilyMember | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      // Owner-scoped server-side: this is the caller's own flat, already.
      const page = await api.get<Page<Resident>>("/residents?limit=50");
      const primary = page.items.find((r) => r.is_primary) ?? page.items[0] ?? null;
      setResident(primary);
      setMembers(
        primary ? await api.get<FamilyMember[]>(`/residents/${primary.id}/family`) : [],
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load your household.");
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div>
        <NFPageHeader title="My Family" />
        <NFCard>
          <p className="px-6 py-10 text-center text-sm text-[var(--nf-text-muted)]">
            Loading your household…
          </p>
        </NFCard>
      </div>
    );
  }

  if (!resident) {
    return (
      <div>
        <NFPageHeader title="My Family" />
        <NFCard>
          <NFEmptyState
            icon={<UsersRound />}
            title="No flat is linked to your account"
            description="Your society admin needs to add you as a resident of a flat before you can manage a household."
          />
        </NFCard>
      </div>
    );
  }

  return (
    <div>
      <NFPageHeader
        title="My Family"
        description={`People living in flat ${resident.flat_number ?? ""}. Give them a login and they see this flat — and only this flat.`}
        actions={
          <NFButton onClick={() => setAdding(true)}>
            <UserPlus /> Add family member
          </NFButton>
        }
      />

      {error && (
        <p
          role="alert"
          className="mb-4 rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
        >
          {error}
        </p>
      )}

      <NFCard>
        {members.length === 0 ? (
          <NFEmptyState
            icon={<UsersRound />}
            title="No family members yet"
            description="Add the people who live with you. You choose, per person, how much of the flat they can see."
            action={
              <NFButton onClick={() => setAdding(true)}>
                <UserPlus /> Add family member
              </NFButton>
            }
          />
        ) : (
          <ul className="divide-y divide-[var(--nf-border)]">
            {members.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-[var(--nf-text)]">
                    {m.full_name}
                  </p>
                  <p className="mt-0.5 text-xs text-[var(--nf-text-muted)]">
                    {relationshipLabel(m.relationship_to_resident)}
                    {m.date_of_birth ? ` · born ${formatDate(m.date_of_birth)}` : ""}
                    {m.email ? ` · ${m.email}` : ""}
                  </p>
                </div>

                <NFStatusBadge
                  tone={ACCESS_TONE[m.access_level]}
                  status={m.has_login ? accessLabel(m.access_level) : "No app access"}
                />

                <div className="flex items-center gap-1">
                  <NFButton
                    variant="ghost"
                    size="sm"
                    onClick={() => setGranting(m)}
                    aria-label={`${m.has_login ? "Change access for" : "Give app access to"} ${m.full_name}`}
                  >
                    <KeyRound /> {m.has_login ? "Change" : "Give access"}
                  </NFButton>
                  {m.has_login && (
                    <NFButton
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Revoke access for ${m.full_name}`}
                      onClick={() => setRevoking(m)}
                    >
                      <ShieldOff />
                    </NFButton>
                  )}
                  <NFButton
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remove ${m.full_name}`}
                    onClick={() => setRemoving(m)}
                  >
                    <Trash2 />
                  </NFButton>
                </div>
              </li>
            ))}
          </ul>
        )}
      </NFCard>

      <AddMemberDialog
        open={adding}
        residentId={resident.id}
        onClose={() => setAdding(false)}
        onSaved={load}
      />
      <GrantAccessDialog
        member={granting}
        onClose={() => setGranting(null)}
        onSaved={load}
      />

      <NFConfirmDialog
        open={revoking !== null}
        onOpenChange={(o) => !o && setRevoking(null)}
        title={`Revoke access for ${revoking?.full_name ?? ""}?`}
        description="They stay on your household list, but can no longer sign in. You can give access back at any time."
        confirmLabel="Revoke access"
        destructive
        onConfirm={async () => {
          if (revoking) {
            await api.delete(`/family-members/${revoking.id}/access`).catch(() => undefined);
            setRevoking(null);
            await load();
          }
        }}
      />

      <NFConfirmDialog
        open={removing !== null}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={`Remove ${removing?.full_name ?? ""}?`}
        description="They are taken off your household list. Any app access they had is revoked with them."
        confirmLabel="Remove"
        destructive
        onConfirm={async () => {
          if (removing) {
            await api.delete(`/family-members/${removing.id}`).catch(() => undefined);
            setRemoving(null);
            await load();
          }
        }}
      />
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function AddMemberDialog({
  open,
  residentId,
  onClose,
  onSaved,
}: {
  open: boolean;
  residentId: string;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [error, setError] = React.useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<AddForm>({
    defaultValues: { full_name: "", relationship_to_resident: "", date_of_birth: "", phone: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await api.post("/family-members", {
        resident_id: residentId,
        full_name: values.full_name,
        relationship_to_resident: values.relationship_to_resident,
        date_of_birth: values.date_of_birth || null,
        phone: values.phone || null,
      });
      reset();
      onClose();
      await onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not add this family member.");
    }
  });

  return (
    <NFDialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title="Add a family member"
      description="Record who lives with you. You can give them a login afterwards."
      footer={
        <>
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton onClick={onSubmit} loading={isSubmitting}>
            Add
          </NFButton>
        </>
      }
    >
      <form className="space-y-4" onSubmit={onSubmit}>
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
          >
            {error}
          </p>
        )}

        <NFField label="Full name" htmlFor="fm-name" error={errors.full_name?.message} required>
          <NFInput
            id="fm-name"
            invalid={!!errors.full_name}
            {...register("full_name", {
              required: "Enter their name.",
              minLength: { value: 2, message: "Enter their name." },
            })}
          />
        </NFField>

        <NFField
          label="Relationship to you"
          htmlFor="fm-rel"
          error={errors.relationship_to_resident?.message}
          required
        >
          <NFSelect
            id="fm-rel"
            invalid={!!errors.relationship_to_resident}
            {...register("relationship_to_resident", { required: "Choose a relationship." })}
          >
            <option value="">Select…</option>
            {FAMILY_RELATIONSHIPS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </NFSelect>
        </NFField>

        <NFField label="Date of birth" htmlFor="fm-dob" hint="Optional.">
          <NFInput id="fm-dob" type="date" {...register("date_of_birth")} />
        </NFField>

        <NFField label="Phone" htmlFor="fm-phone" error={errors.phone?.message} hint="Optional.">
          <NFInput
            id="fm-phone"
            inputMode="numeric"
            invalid={!!errors.phone}
            {...register("phone", {
              pattern: { value: /^[6-9][0-9]{9}$/, message: "Enter a 10-digit mobile number." },
            })}
          />
        </NFField>
      </form>
    </NFDialog>
  );
}

/* -------------------------------------------------------------------------- */

function GrantAccessDialog({
  member,
  onClose,
  onSaved,
}: {
  member: FamilyMember | null;
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
  } = useForm<{ email: string; access_level: FamilyAccessLevel | "" }>();

  React.useEffect(() => {
    setError(null);
    reset({
      email: member?.email ?? "",
      access_level: member?.access_level === "NONE" ? "" : (member?.access_level ?? ""),
    });
  }, [member, reset]);

  const chosen = watch("access_level");
  const hint = FAMILY_ACCESS_LEVELS.find((l) => l.value === chosen)?.hint;

  const onSubmit = handleSubmit(async (values) => {
    if (!member) return;
    setError(null);
    try {
      await api.post(`/family-members/${member.id}/access`, {
        access_level: values.access_level,
        email: values.email,
      });
      onClose();
      await onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not grant access.");
    }
  });

  return (
    <NFDialog
      open={member !== null}
      onOpenChange={(o) => !o && onClose()}
      title={member?.has_login ? `Change access for ${member.full_name}` : `Give ${member?.full_name ?? ""} app access`}
      description="They sign in with this email address and a password they set themselves."
      footer={
        <>
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton onClick={onSubmit} loading={isSubmitting}>
            {member?.has_login ? "Save" : "Give access"}
          </NFButton>
        </>
      }
    >
      <form className="space-y-4" onSubmit={onSubmit}>
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
          >
            {error}
          </p>
        )}

        <NFField label="Email address" htmlFor="fa-email" error={errors.email?.message} required>
          <NFInput
            id="fa-email"
            type="email"
            autoComplete="off"
            invalid={!!errors.email}
            {...register("email", {
              required: "An email address is required to give app access.",
              pattern: { value: /^\S+@\S+\.\S+$/, message: "Enter a valid email address." },
            })}
          />
        </NFField>

        <NFField
          label="How much can they see?"
          htmlFor="fa-level"
          error={errors.access_level?.message}
          hint={hint}
          required
        >
          <NFSelect
            id="fa-level"
            invalid={!!errors.access_level}
            {...register("access_level", { required: "Choose an access level." })}
          >
            <option value="">Select…</option>
            {FAMILY_ACCESS_LEVELS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </NFSelect>
        </NFField>

        <p className="text-xs text-[var(--nf-text-subtle)]">
          Whatever you choose, they only ever see this flat.
        </p>
      </form>
    </NFDialog>
  );
}
