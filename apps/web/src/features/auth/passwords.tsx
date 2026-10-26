/**
 * Password fields shared by every screen that sets one.
 *
 * The rules mirror the API's policy (`app/auth/passwords.py`) so the form
 * says what is wrong before the request; the server still enforces them.
 */

import { KeyRound, Lock } from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";

import { NFDialog } from "@/components/nestflow/data";
import { NFButton, NFField, NFInput } from "@/components/nestflow/primitives";
import { ApiError, api } from "@/services/api";

export const PASSWORD_HINT = "At least 8 characters, with a letter and a number.";

/** `true`, or what is wrong with the password. An empty value passes — whether
 *  one is required is the field's own `required` rule. */
export function passwordPolicy(value: string): true | string {
  if (!value) return true;
  if (/[A-Za-z]/.test(value) && /[0-9]/.test(value)) return true;
  return "Include at least one letter and one number.";
}

/** Spread into `register(name, { required, ...newPasswordRules })`. */
export const newPasswordRules = {
  minLength: { value: 8, message: "Use at least 8 characters." },
  maxLength: { value: 128, message: "Use at most 128 characters." },
  validate: (value: string) => passwordPolicy(value),
};

interface SetPasswordForm {
  password: string;
  confirm: string;
}

/**
 * An administrator setting or resetting someone else's password.
 *
 * `endpoint` is the reset route for the account — `/users/{id}/password` for a
 * society user, `/platform/users/{id}/password` for a platform account.
 */
export function SetPasswordDialog({
  open,
  onOpenChange,
  endpoint,
  name,
  email,
  onDone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  endpoint: string;
  name: string;
  email: string;
  onDone?: () => void;
}) {
  const [formError, setFormError] = React.useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<SetPasswordForm>({ defaultValues: { password: "", confirm: "" } });

  const close = (next: boolean) => {
    onOpenChange(next);
    if (!next) {
      reset();
      setFormError(null);
    }
  };

  const onSubmit = handleSubmit(async ({ password }) => {
    setFormError(null);
    try {
      await api.post(endpoint, { password });
      close(false);
      onDone?.();
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "Could not set the password.");
    }
  });

  return (
    <NFDialog
      open={open}
      onOpenChange={close}
      size="sm"
      title="Set password"
      description={`${name} (${email}) will sign in with this password. They are signed out of every device.`}
      footer={
        <>
          <NFButton variant="secondary" onClick={() => close(false)}>
            Cancel
          </NFButton>
          <NFButton onClick={onSubmit} loading={isSubmitting}>
            Set password
          </NFButton>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {formError && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
          >
            {formError}
          </p>
        )}
        <NFField
          label="New password"
          htmlFor="set-password"
          error={errors.password?.message}
          hint={PASSWORD_HINT}
          required
        >
          <NFInput
            id="set-password"
            type="password"
            autoComplete="new-password"
            leadingIcon={<KeyRound />}
            invalid={!!errors.password}
            {...register("password", { required: "Enter a password.", ...newPasswordRules })}
          />
        </NFField>
        <NFField label="Repeat it" htmlFor="set-confirm" error={errors.confirm?.message} required>
          <NFInput
            id="set-confirm"
            type="password"
            autoComplete="new-password"
            leadingIcon={<Lock />}
            invalid={!!errors.confirm}
            {...register("confirm", {
              required: "Repeat the password.",
              validate: (v) => v === getValues("password") || "The passwords do not match.",
            })}
          />
        </NFField>
      </form>
    </NFDialog>
  );
}
