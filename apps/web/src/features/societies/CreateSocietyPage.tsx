import { ArrowLeft, CheckCircle2, Database, Loader2, ShieldAlert } from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router-dom";

import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFField,
  NFInput,
  NFPageHeader,
  NFSelect,
} from "@/components/nestflow/primitives";
import { ApiError, api } from "@/services/api";
import type { SocietyProvisionResult, SubscriptionPlan } from "@/types";

interface FormValues {
  name: string;
  registration_number: string;
  address_line1: string;
  city: string;
  state: string;
  pincode: string;
  contact_email: string;
  contact_phone: string;
  plan_id: string;
  admin_email: string;
  admin_name: string;
  admin_phone: string;
}

const INDIAN_STATES = [
  "Andhra Pradesh", "Assam", "Bihar", "Chhattisgarh", "Delhi", "Goa", "Gujarat",
  "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
  "Madhya Pradesh", "Maharashtra", "Odisha", "Punjab", "Rajasthan", "Tamil Nadu",
  "Telangana", "Uttar Pradesh", "Uttarakhand", "West Bengal",
];

export default function CreateSocietyPage() {
  const navigate = useNavigate();
  const [plans, setPlans] = React.useState<SubscriptionPlan[]>([]);
  const [result, setResult] = React.useState<SocietyProvisionResult | null>(null);
  const [formError, setFormError] = React.useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    defaultValues: { state: "Maharashtra", plan_id: "" },
  });

  React.useEffect(() => {
    api
      .get<SubscriptionPlan[]>("/platform/plans", { active_only: true })
      .then(setPlans)
      .catch(() => setPlans([]));
  }, []);

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const created = await api.post<SocietyProvisionResult>("/platform/societies", {
        name: values.name,
        registration_number: values.registration_number || null,
        address_line1: values.address_line1 || null,
        city: values.city,
        state: values.state,
        pincode: values.pincode,
        contact_email: values.contact_email,
        contact_phone: values.contact_phone,
        plan_id: values.plan_id || null,
        admin: {
          email: values.admin_email,
          display_name: values.admin_name,
          phone: values.admin_phone || null,
        },
      });
      setResult(created);
    } catch (e) {
      if (e instanceof ApiError) {
        // Map server field errors back onto the form so they appear inline.
        const fields = e.fieldErrors;
        let mapped = false;
        for (const [field, message] of Object.entries(fields)) {
          const key = field.replace("admin.", "admin_").replace("display_name", "name");
          if (key in values) {
            setError(key as keyof FormValues, { message });
            mapped = true;
          }
        }
        if (!mapped) setFormError(e.message);
      } else {
        setFormError("Could not create the society. Please try again.");
      }
    }
  });

  /* ---------------------------------------------------------------------- */
  /* Success                                                                */
  /* ---------------------------------------------------------------------- */

  if (result) {
    return (
      <>
        <NFPageHeader title="Society created" />
        <NFCard className="mx-auto max-w-2xl">
          <NFCardBody className="text-center">
            <span
              className="mx-auto mb-5 flex size-14 items-center justify-center rounded-full bg-[var(--nf-success-subtle)] text-[var(--nf-success)]"
              aria-hidden
            >
              <CheckCircle2 className="size-7" />
            </span>
            <h2 className="text-xl font-semibold text-[var(--nf-text)]">{result.society.name}</h2>
            <p className="mt-1.5 text-sm text-[var(--nf-text-muted)]">
              Provisioned successfully and ready to use.
            </p>

            <dl className="mt-6 space-y-px overflow-hidden rounded-[var(--nf-radius)] border border-[var(--nf-border)] text-left text-sm">
              {[
                ["Identifier", result.society.slug],
                ["Tenant database", result.database_name],
                ["Schema revision", result.alembic_revision],
                ["Society admin", result.admin_email],
                [
                  "Subscription",
                  `${result.subscription.plan_name ?? "—"} · ${result.subscription.status} until ${result.subscription.end_date}`,
                ],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="flex flex-wrap justify-between gap-2 bg-[var(--nf-background)] px-4 py-2.5"
                >
                  <dt className="text-[var(--nf-text-muted)]">{label}</dt>
                  <dd className="font-mono text-[13px] text-[var(--nf-text)]">{value}</dd>
                </div>
              ))}
            </dl>

            <div className="mt-6 flex items-start gap-2.5 rounded-[var(--nf-radius)] border border-[var(--nf-info)]/25 bg-[var(--nf-info-subtle)] p-3 text-left">
              <Database className="mt-0.5 size-4 shrink-0 text-[var(--nf-info)]" aria-hidden />
              <p className="text-[12.5px] leading-relaxed text-[var(--nf-text-muted)]">
                A dedicated PostgreSQL database was created, migrated and seeded with roles,
                permissions, settings and a default theme. The society admin can sign in
                immediately — no further setup is needed.
              </p>
            </div>

            <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
              <NFButton onClick={() => navigate(`/admin/societies/${result.society.id}`)}>
                View society
              </NFButton>
              <NFButton variant="secondary" onClick={() => setResult(null)}>
                Create another
              </NFButton>
            </div>
          </NFCardBody>
        </NFCard>
      </>
    );
  }

  /* ---------------------------------------------------------------------- */
  /* Form                                                                   */
  /* ---------------------------------------------------------------------- */

  return (
    <>
      <NFPageHeader
        title="New society"
        description="Creating a society provisions its own PostgreSQL database, runs migrations and seeds roles automatically."
        breadcrumb={
          <Link
            to="/admin/societies"
            className="inline-flex items-center gap-1.5 text-[13px] text-[var(--nf-text-muted)] hover:text-[var(--nf-primary)]"
          >
            <ArrowLeft className="size-3.5" aria-hidden /> Societies
          </Link>
        }
      />

      {formError && (
        <div
          role="alert"
          className="mx-auto mb-5 flex max-w-3xl gap-2.5 rounded-[var(--nf-radius)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] p-3.5"
        >
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-[var(--nf-danger)]" aria-hidden />
          <p className="text-sm text-[var(--nf-text)]">{formError}</p>
        </div>
      )}

      <form onSubmit={onSubmit} noValidate className="mx-auto max-w-3xl space-y-5">
        <NFCard>
          <NFCardHeader title="Society details" />
          <NFCardBody className="grid gap-4 sm:grid-cols-2">
            <NFField
              label="Society name"
              htmlFor="name"
              error={errors.name?.message}
              required
              className="sm:col-span-2"
            >
              <NFInput
                id="name"
                placeholder="Green Valley Residency"
                invalid={!!errors.name}
                {...register("name", {
                  required: "Enter the society name.",
                  minLength: { value: 3, message: "At least 3 characters." },
                })}
              />
            </NFField>

            <NFField label="Registration number" htmlFor="registration_number">
              <NFInput id="registration_number" placeholder="Optional" {...register("registration_number")} />
            </NFField>

            <NFField label="Address" htmlFor="address_line1">
              <NFInput id="address_line1" placeholder="Baner Road" {...register("address_line1")} />
            </NFField>

            <NFField label="City" htmlFor="city" error={errors.city?.message} required>
              <NFInput
                id="city"
                placeholder="Pune"
                invalid={!!errors.city}
                {...register("city", { required: "Enter the city." })}
              />
            </NFField>

            <NFField label="State" htmlFor="state" error={errors.state?.message} required>
              <NFSelect id="state" invalid={!!errors.state} {...register("state", { required: true })}>
                {INDIAN_STATES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </NFSelect>
            </NFField>

            <NFField label="PIN code" htmlFor="pincode" error={errors.pincode?.message} required>
              <NFInput
                id="pincode"
                inputMode="numeric"
                maxLength={6}
                placeholder="411045"
                invalid={!!errors.pincode}
                {...register("pincode", {
                  required: "Enter the PIN code.",
                  pattern: { value: /^[1-9][0-9]{5}$/, message: "Six digits, not starting with 0." },
                })}
              />
            </NFField>

            <NFField
              label="Office email"
              htmlFor="contact_email"
              error={errors.contact_email?.message}
              required
            >
              <NFInput
                id="contact_email"
                type="email"
                placeholder="office@society.in"
                invalid={!!errors.contact_email}
                {...register("contact_email", {
                  required: "Enter the office email.",
                  pattern: { value: /^\S+@\S+\.\S+$/, message: "Not a valid email address." },
                })}
              />
            </NFField>

            <NFField
              label="Office phone"
              htmlFor="contact_phone"
              error={errors.contact_phone?.message}
              hint="10-digit Indian mobile, without +91"
              required
            >
              <NFInput
                id="contact_phone"
                inputMode="tel"
                maxLength={10}
                placeholder="9822012345"
                invalid={!!errors.contact_phone}
                {...register("contact_phone", {
                  required: "Enter the office phone number.",
                  pattern: {
                    value: /^[6-9][0-9]{9}$/,
                    message: "Ten digits, starting with 6–9.",
                  },
                })}
              />
            </NFField>
          </NFCardBody>
        </NFCard>

        <NFCard>
          <NFCardHeader
            title="Society administrator"
            description="This person receives full control of the society. They can sign in as soon as provisioning completes."
          />
          <NFCardBody className="grid gap-4 sm:grid-cols-2">
            <NFField label="Full name" htmlFor="admin_name" error={errors.admin_name?.message} required>
              <NFInput
                id="admin_name"
                placeholder="Rohan Deshpande"
                invalid={!!errors.admin_name}
                {...register("admin_name", { required: "Enter the administrator's name." })}
              />
            </NFField>

            <NFField
              label="Email address"
              htmlFor="admin_email"
              error={errors.admin_email?.message}
              required
            >
              <NFInput
                id="admin_email"
                type="email"
                placeholder="admin@society.in"
                invalid={!!errors.admin_email}
                {...register("admin_email", {
                  required: "Enter the administrator's email.",
                  pattern: { value: /^\S+@\S+\.\S+$/, message: "Not a valid email address." },
                })}
              />
            </NFField>

            <NFField label="Phone" htmlFor="admin_phone" error={errors.admin_phone?.message}>
              <NFInput
                id="admin_phone"
                inputMode="tel"
                maxLength={10}
                placeholder="9822011111"
                invalid={!!errors.admin_phone}
                {...register("admin_phone", {
                  pattern: { value: /^[6-9][0-9]{9}$/, message: "Ten digits, starting with 6–9." },
                })}
              />
            </NFField>
          </NFCardBody>
        </NFCard>

        <NFCard>
          <NFCardHeader title="Subscription" description="Leave blank to use the default plan." />
          <NFCardBody>
            <NFField label="Plan" htmlFor="plan_id" className="sm:max-w-sm">
              <NFSelect id="plan_id" {...register("plan_id")}>
                <option value="">Default plan</option>
                {plans.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · ₹{p.price} / {p.billing_cycle.toLowerCase().replace("_", " ")}
                    {p.trial_days ? ` · ${p.trial_days}-day trial` : ""}
                  </option>
                ))}
              </NFSelect>
            </NFField>
          </NFCardBody>
        </NFCard>

        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <NFButton type="button" variant="secondary" asChild>
            <Link to="/admin/societies">Cancel</Link>
          </NFButton>
          <NFButton type="submit" loading={isSubmitting}>
            {isSubmitting ? "Provisioning…" : "Create society"}
          </NFButton>
        </div>

        {isSubmitting && (
          <p className="flex items-center justify-center gap-2 text-[13px] text-[var(--nf-text-muted)]">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            Creating the database, running migrations and seeding roles…
          </p>
        )}
      </form>
    </>
  );
}
