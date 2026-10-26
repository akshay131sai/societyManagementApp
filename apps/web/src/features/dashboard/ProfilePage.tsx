import { CheckCircle2, KeyRound, Lock, Mail, Phone, Shield } from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";

import {
  NFAvatar,
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFField,
  NFInput,
  NFPageHeader,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
import { PASSWORD_HINT, newPasswordRules, passwordPolicy } from "@/features/auth/passwords";
import { ApiError } from "@/services/api";
import { IS_PASSWORD_AUTH, changePassword } from "@/services/auth";
import { useAppSelector } from "@/store";

export default function ProfilePage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const society = useAppSelector((s) => s.auth.society);

  if (!principal) return null;

  return (
    <>
      <NFPageHeader title="Profile" description="Your account and what you can do here." />

      <div className="grid max-w-4xl gap-5 lg:grid-cols-3">
        <NFCard className="lg:col-span-1">
          <NFCardBody className="text-center">
            <NFAvatar name={principal.display_name} size={72} className="mx-auto" />
            <h2 className="mt-4 text-lg font-semibold text-[var(--nf-text)]">
              {principal.display_name}
            </h2>
            <p className="mt-0.5 text-sm text-[var(--nf-text-muted)]">{principal.email}</p>
            <div className="mt-4 flex flex-wrap justify-center gap-1.5">
              {principal.roles.map((role) => (
                <NFStatusBadge key={role} status={role} tone="primary" />
              ))}
            </div>
          </NFCardBody>
        </NFCard>

        <div className="space-y-5 lg:col-span-2">
          <NFCard>
            <NFCardHeader title="Account" />
            <NFCardBody>
              <dl className="space-y-3.5 text-sm">
                <Row icon={<Mail />} label="Email">
                  {principal.email}
                </Row>
                <Row icon={<Shield />} label="Scope">
                  {principal.is_super_admin ? "Platform administrator" : (society?.name ?? "—")}
                </Row>
                <Row icon={<Phone />} label="Identity">
                  <span className="font-mono text-[12px]">{principal.firebase_uid}</span>
                </Row>
              </dl>
            </NFCardBody>
          </NFCard>

          {IS_PASSWORD_AUTH && <ChangePasswordCard />}

          <NFCard>
            <NFCardHeader
              title="Permissions"
              description={`${principal.permissions.length} permissions granted by your role.`}
            />
            <NFCardBody>
              <div className="nf-scroll max-h-72 overflow-y-auto">
                <div className="flex flex-wrap gap-1.5">
                  {principal.permissions.map((permission) => (
                    <span
                      key={permission}
                      className="rounded-full border border-[var(--nf-border)] bg-[var(--nf-background)] px-2.5 py-1 font-mono text-[11px] text-[var(--nf-text-muted)]"
                    >
                      {permission}
                    </span>
                  ))}
                </div>
              </div>
            </NFCardBody>
          </NFCard>
        </div>
      </div>
    </>
  );
}

interface PasswordForm {
  current_password: string;
  new_password: string;
  confirm: string;
}

function ChangePasswordCard() {
  const [done, setDone] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    setError,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<PasswordForm>({
    defaultValues: { current_password: "", new_password: "", confirm: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setDone(false);
    setFormError(null);
    try {
      await changePassword(values.current_password, values.new_password);
      reset();
      setDone(true);
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fieldErrors).length) {
        for (const [field, message] of Object.entries(e.fieldErrors)) {
          if (field === "current_password" || field === "new_password") {
            setError(field, { message });
          }
        }
      } else {
        setFormError(e instanceof ApiError ? e.message : "Could not change your password.");
      }
    }
  });

  return (
    <NFCard>
      <NFCardHeader
        title="Password"
        description="Changing it signs you out on every other device."
      />
      <NFCardBody>
        <form onSubmit={onSubmit} className="grid gap-4 sm:max-w-sm" noValidate>
          {formError && (
            <p
              role="alert"
              className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
            >
              {formError}
            </p>
          )}
          {done && (
            <p
              role="status"
              className="flex items-center gap-2 rounded-[var(--nf-radius-sm)] bg-[var(--nf-success-subtle)] px-3 py-2 text-[13px] text-[var(--nf-success)]"
            >
              <CheckCircle2 className="size-4" aria-hidden /> Password changed.
            </p>
          )}

          <NFField
            label="Current password"
            htmlFor="current_password"
            error={errors.current_password?.message}
            required
          >
            <NFInput
              id="current_password"
              type="password"
              autoComplete="current-password"
              leadingIcon={<Lock />}
              invalid={!!errors.current_password}
              {...register("current_password", { required: "Enter your current password." })}
            />
          </NFField>

          <NFField
            label="New password"
            htmlFor="new_password"
            error={errors.new_password?.message}
            hint={PASSWORD_HINT}
            required
          >
            <NFInput
              id="new_password"
              type="password"
              autoComplete="new-password"
              leadingIcon={<KeyRound />}
              invalid={!!errors.new_password}
              {...register("new_password", {
                required: "Choose a new password.",
                ...newPasswordRules,
                validate: (value: string) => {
                  const policy = passwordPolicy(value);
                  if (policy !== true) return policy;
                  return (
                    value !== getValues("current_password") ||
                    "Choose a password different from the current one."
                  );
                },
              })}
            />
          </NFField>

          <NFField label="Repeat new password" htmlFor="confirm" error={errors.confirm?.message} required>
            <NFInput
              id="confirm"
              type="password"
              autoComplete="new-password"
              leadingIcon={<KeyRound />}
              invalid={!!errors.confirm}
              {...register("confirm", {
                required: "Repeat the new password.",
                validate: (v) => v === getValues("new_password") || "The passwords do not match.",
              })}
            />
          </NFField>

          <div>
            <NFButton type="submit" loading={isSubmitting}>
              Change password
            </NFButton>
          </div>
        </form>
      </NFCardBody>
    </NFCard>
  );
}

function Row({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3">
      <span
        className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-[var(--nf-radius-sm)] bg-[var(--nf-primary-subtle)] text-[var(--nf-primary)] [&_svg]:size-4"
        aria-hidden
      >
        {icon}
      </span>
      <div className="min-w-0">
        <dt className="text-xs text-[var(--nf-text-muted)]">{label}</dt>
        <dd className="mt-0.5 break-all text-[var(--nf-text)]">{children}</dd>
      </div>
    </div>
  );
}
