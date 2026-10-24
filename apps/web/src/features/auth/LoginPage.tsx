import { Building2, Lock, Mail, ShieldAlert, Sparkles } from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";

import loginHero from "@/assets/login-hero.png";
import { NFButton, NFField, NFInput } from "@/components/nestflow/primitives";
import { IS_DEV_AUTH } from "@/services/auth";
import { useAppDispatch, useAppSelector } from "@/store";
import { clearError, signIn } from "@/store/authSlice";
import { homePathFor } from "@/utils/permissions";

interface LoginForm {
  email: string;
  password: string;
}

export default function LoginPage() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const { status, errorMessage, errorCode } = useAppSelector((s) => s.auth);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginForm>({ defaultValues: { email: "", password: "" } });

  React.useEffect(() => {
    dispatch(clearError());
  }, [dispatch]);

  const onSubmit = handleSubmit(async (values) => {
    const result = await dispatch(signIn(values));
    if (signIn.fulfilled.match(result)) {
      navigate(homePathFor(result.payload.principal), { replace: true });
    }
  });

  const submitting = status === "loading";

  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      {/* Brand panel — decorative, hidden on small screens. The headline and feature
          list are part of the hero image itself, so they are kept here only for
          screen readers. */}
      <div
        className="relative hidden flex-col justify-between overflow-hidden p-12 lg:flex"
        style={{ backgroundColor: "var(--nf-sidebar)" }}
      >
        <img
          src={loginHero}
          alt=""
          aria-hidden
          className="absolute inset-0 size-full object-cover object-left"
        />

        <div className="relative flex items-center gap-3">
          <span
            className="flex size-10 items-center justify-center rounded-[var(--nf-radius-sm)] text-lg font-bold text-[var(--nf-primary-foreground)]"
            style={{ backgroundColor: "var(--nf-primary)" }}
            aria-hidden
          >
            N
          </span>
          <span className="text-lg font-semibold text-white">NestFlow</span>
        </div>

        <div className="sr-only">
          <h2 className="text-3xl font-semibold leading-tight text-white">
            Society management, without the spreadsheets.
          </h2>
          <p className="mt-4 text-[15px] leading-relaxed text-white/60">
            Maintenance billing, utilities, visitors, complaints and housekeeping — for every
            flat in your society, in one place.
          </p>

          <ul className="mt-8 space-y-3 text-sm text-white/70">
            {[
              "Visual bill builder with versioned templates",
              "Water and electricity analytics per flat",
              "Real-time visitor approval at the gate",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2.5">
                <span
                  className="mt-1.5 size-1.5 shrink-0 rounded-full"
                  style={{ backgroundColor: "var(--nf-primary)" }}
                  aria-hidden
                />
                {item}
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-xs text-white/60">© 2026 NestFlow · Built for Indian societies</p>
      </div>

      {/* Form panel */}
      <div className="flex items-center justify-center bg-[var(--nf-background)] p-6">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <div className="mb-4 flex items-center gap-3">
              <span
                className="flex size-10 items-center justify-center rounded-[var(--nf-radius-sm)] text-lg font-bold text-[var(--nf-primary-foreground)]"
                style={{ backgroundColor: "var(--nf-primary)" }}
                aria-hidden
              >
                N
              </span>
              <span className="text-lg font-semibold text-[var(--nf-text)]">NestFlow</span>
            </div>
          </div>

          <h1 className="text-2xl font-semibold tracking-tight text-[var(--nf-text)]">
            Welcome back
          </h1>
          <p className="mt-1.5 text-sm text-[var(--nf-text-muted)]">
            Sign in to your society account.
          </p>

          {IS_DEV_AUTH && (
            <div className="mt-5 flex gap-2.5 rounded-[var(--nf-radius)] border border-[var(--nf-warning)]/30 bg-[var(--nf-warning-subtle)] p-3">
              <Sparkles className="mt-0.5 size-4 shrink-0 text-[var(--nf-warning)]" aria-hidden />
              <div className="text-[12.5px] leading-relaxed text-[var(--nf-text)]">
                <p className="font-semibold text-[var(--nf-warning)]">Development sign-in</p>
                <p className="mt-0.5 text-[var(--nf-text-muted)]">
                  Firebase is not configured yet. Enter any registered email — the password is
                  ignored. The API refuses this mode in production.
                </p>
              </div>
            </div>
          )}

          {errorMessage && (
            <div
              role="alert"
              className="mt-5 flex gap-2.5 rounded-[var(--nf-radius)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] p-3"
            >
              <ShieldAlert className="mt-0.5 size-4 shrink-0 text-[var(--nf-danger)]" aria-hidden />
              <div className="text-[12.5px] leading-relaxed">
                <p className="text-[var(--nf-text)]">{errorMessage}</p>
                {errorCode && (
                  <p className="mt-0.5 font-mono text-[11px] text-[var(--nf-text-subtle)]">
                    {errorCode}
                  </p>
                )}
              </div>
            </div>
          )}

          <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
            <NFField label="Email address" htmlFor="email" error={errors.email?.message} required>
              <NFInput
                id="email"
                type="email"
                autoComplete="email"
                autoFocus
                placeholder="you@society.in"
                leadingIcon={<Mail />}
                invalid={!!errors.email}
                aria-describedby={errors.email ? "email-error" : undefined}
                {...register("email", {
                  required: "Enter your email address.",
                  pattern: { value: /^\S+@\S+\.\S+$/, message: "That is not a valid email address." },
                })}
              />
            </NFField>

            <NFField
              label="Password"
              htmlFor="password"
              error={errors.password?.message}
              required={!IS_DEV_AUTH}
            >
              <NFInput
                id="password"
                type="password"
                autoComplete="current-password"
                placeholder={IS_DEV_AUTH ? "not required in dev mode" : "••••••••"}
                leadingIcon={<Lock />}
                invalid={!!errors.password}
                {...register("password", {
                  required: IS_DEV_AUTH ? false : "Enter your password.",
                })}
              />
            </NFField>

            <NFButton type="submit" size="lg" loading={submitting} className="w-full">
              Sign in
            </NFButton>
          </form>

          <div className="mt-6 flex items-center gap-2 rounded-[var(--nf-radius)] border border-[var(--nf-border)] bg-[var(--nf-surface)] p-3">
            <Building2 className="size-4 shrink-0 text-[var(--nf-text-subtle)]" aria-hidden />
            <p className="text-[12px] leading-relaxed text-[var(--nf-text-muted)]">
              Accounts are created by your society administrator. Signing in with a new identity
              does not create one.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
