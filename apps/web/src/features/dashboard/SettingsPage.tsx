import { Check } from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";

import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFField,
  NFInput,
  NFPageHeader,
  NFSelect,
  NFSkeleton,
} from "@/components/nestflow/primitives";
import { ApiError, api } from "@/services/api";
import type { SocietySettings } from "@/types";

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export default function SettingsPage() {
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<Partial<SocietySettings>>();

  React.useEffect(() => {
    api
      .get<SocietySettings>("/society/settings")
      .then((s) => reset(s))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load settings."))
      .finally(() => setLoading(false));
  }, [reset]);

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      const updated = await api.put<SocietySettings>("/society/settings", {
        society_name: values.society_name,
        registration_number: values.registration_number || null,
        address_line1: values.address_line1 || null,
        city: values.city || null,
        state: values.state || null,
        pincode: values.pincode || null,
        contact_email: values.contact_email || null,
        contact_phone: values.contact_phone || null,
        financial_year_start_month: Number(values.financial_year_start_month),
        bill_due_days: Number(values.bill_due_days),
        late_fee_percent: String(values.late_fee_percent ?? "0"),
        late_fee_grace_days: Number(values.late_fee_grace_days),
      });
      reset(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save these settings.");
    }
  });

  if (loading) {
    return (
      <>
        <NFPageHeader title="Settings" />
        <div className="space-y-5">
          <NFSkeleton className="h-72" />
          <NFSkeleton className="h-56" />
        </div>
      </>
    );
  }

  return (
    <>
      <NFPageHeader
        title="Settings"
        description="Society details and billing defaults. These apply only to your society."
        actions={
          <NFButton onClick={onSubmit} loading={isSubmitting} disabled={!isDirty && !saved}>
            {saved ? (
              <>
                <Check /> Saved
              </>
            ) : (
              "Save changes"
            )}
          </NFButton>
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

      <form onSubmit={onSubmit} noValidate className="max-w-3xl space-y-5">
        <NFCard>
          <NFCardHeader title="Society details" />
          <NFCardBody className="grid gap-4 sm:grid-cols-2">
            <NFField
              label="Society name"
              htmlFor="society_name"
              error={errors.society_name?.message}
              required
              className="sm:col-span-2"
            >
              <NFInput
                id="society_name"
                invalid={!!errors.society_name}
                {...register("society_name", { required: "Enter the society name." })}
              />
            </NFField>

            <NFField label="Registration number" htmlFor="registration_number">
              <NFInput id="registration_number" {...register("registration_number")} />
            </NFField>

            <NFField label="Address" htmlFor="address_line1">
              <NFInput id="address_line1" {...register("address_line1")} />
            </NFField>

            <NFField label="City" htmlFor="city">
              <NFInput id="city" {...register("city")} />
            </NFField>

            <NFField label="State" htmlFor="state">
              <NFInput id="state" {...register("state")} />
            </NFField>

            <NFField label="PIN code" htmlFor="pincode" error={errors.pincode?.message}>
              <NFInput
                id="pincode"
                inputMode="numeric"
                maxLength={6}
                invalid={!!errors.pincode}
                {...register("pincode", {
                  pattern: { value: /^[1-9][0-9]{5}$/, message: "Six digits, not starting with 0." },
                })}
              />
            </NFField>

            <NFField
              label="Office email"
              htmlFor="contact_email"
              error={errors.contact_email?.message}
            >
              <NFInput
                id="contact_email"
                type="email"
                invalid={!!errors.contact_email}
                {...register("contact_email", {
                  pattern: { value: /^\S+@\S+\.\S+$/, message: "Not a valid email address." },
                })}
              />
            </NFField>

            <NFField
              label="Office phone"
              htmlFor="contact_phone"
              error={errors.contact_phone?.message}
            >
              <NFInput
                id="contact_phone"
                inputMode="tel"
                maxLength={10}
                invalid={!!errors.contact_phone}
                {...register("contact_phone", {
                  pattern: { value: /^[6-9][0-9]{9}$/, message: "Ten digits, starting with 6–9." },
                })}
              />
            </NFField>
          </NFCardBody>
        </NFCard>

        <NFCard>
          <NFCardHeader
            title="Billing defaults"
            description="Used when generating maintenance bills. Individual templates can override these."
          />
          <NFCardBody className="grid gap-4 sm:grid-cols-2">
            <NFField
              label="Financial year starts"
              htmlFor="financial_year_start_month"
              hint="April is the Indian financial year"
            >
              <NFSelect id="financial_year_start_month" {...register("financial_year_start_month")}>
                {MONTHS.map((m, i) => (
                  <option key={m} value={i + 1}>
                    {m}
                  </option>
                ))}
              </NFSelect>
            </NFField>

            <NFField
              label="Payment due after"
              htmlFor="bill_due_days"
              hint="Days from bill issue"
              error={errors.bill_due_days?.message}
            >
              <NFInput
                id="bill_due_days"
                type="number"
                min={0}
                max={90}
                invalid={!!errors.bill_due_days}
                {...register("bill_due_days", {
                  min: { value: 0, message: "Cannot be negative." },
                  max: { value: 90, message: "90 days maximum." },
                })}
              />
            </NFField>

            <NFField
              label="Late fee"
              htmlFor="late_fee_percent"
              hint="Percent of the outstanding amount"
            >
              <NFInput
                id="late_fee_percent"
                type="number"
                step="0.01"
                min={0}
                max={100}
                {...register("late_fee_percent")}
              />
            </NFField>

            <NFField
              label="Grace period"
              htmlFor="late_fee_grace_days"
              hint="Days after the due date before a late fee applies"
            >
              <NFInput
                id="late_fee_grace_days"
                type="number"
                min={0}
                max={90}
                {...register("late_fee_grace_days")}
              />
            </NFField>
          </NFCardBody>
        </NFCard>

        <NFCard>
          <NFCardHeader title="Locale" description="Fixed for the Indian market." />
          <NFCardBody>
            <dl className="grid gap-3 text-sm sm:grid-cols-3">
              {[
                ["Currency", "INR (₹)"],
                ["Locale", "en-IN"],
                ["Timezone", "Asia/Kolkata"],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-[var(--nf-text-muted)]">{label}</dt>
                  <dd className="mt-0.5 font-medium text-[var(--nf-text)]">{value}</dd>
                </div>
              ))}
            </dl>
          </NFCardBody>
        </NFCard>
      </form>
    </>
  );
}
