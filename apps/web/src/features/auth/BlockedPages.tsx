/**
 * Blocked-state screens.
 *
 * A locked society, an expired subscription and a tenant still provisioning
 * are three different situations with three different next actions. Showing
 * one generic "access denied" for all of them would leave the user stuck.
 */

import { Clock, CreditCard, Lock, ShieldOff } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { NFButton, NFCard } from "@/components/nestflow/primitives";
import { useAppDispatch, useAppSelector } from "@/store";
import { bootstrapSession, signOut } from "@/store/authSlice";

function BlockedShell({
  icon,
  tone,
  title,
  message,
  children,
}: {
  icon: React.ReactNode;
  tone: "danger" | "warning" | "info";
  title: string;
  message: string;
  children?: React.ReactNode;
}) {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();

  const toneVar = { danger: "--nf-danger", warning: "--nf-warning", info: "--nf-info" }[tone];
  const subtleVar = {
    danger: "--nf-danger-subtle",
    warning: "--nf-warning-subtle",
    info: "--nf-info-subtle",
  }[tone];

  return (
    <div className="flex min-h-dvh items-center justify-center bg-[var(--nf-background)] p-6">
      <NFCard className="w-full max-w-md p-8 text-center">
        <span
          className="mx-auto mb-5 flex size-14 items-center justify-center rounded-full [&_svg]:size-7"
          style={{ backgroundColor: `var(${subtleVar})`, color: `var(${toneVar})` }}
          aria-hidden
        >
          {icon}
        </span>

        <h1 className="text-xl font-semibold text-[var(--nf-text)]">{title}</h1>
        <p className="mt-2.5 text-sm leading-relaxed text-[var(--nf-text-muted)]">{message}</p>

        {children}

        <div className="mt-7 flex flex-col gap-2 sm:flex-row sm:justify-center">
          <NFButton variant="secondary" onClick={() => dispatch(bootstrapSession())}>
            Check again
          </NFButton>
          <NFButton
            variant="ghost"
            onClick={async () => {
              await dispatch(signOut());
              navigate("/login", { replace: true });
            }}
          >
            Sign out
          </NFButton>
        </div>
      </NFCard>
    </div>
  );
}

export function SubscriptionExpiredPage() {
  const message = useAppSelector((s) => s.auth.errorMessage);
  return (
    <BlockedShell
      icon={<CreditCard />}
      tone="warning"
      title="Subscription ended"
      message={
        message ??
        "Your society subscription has ended. Please contact your society administrator to renew access."
      }
    >
      <p className="mt-4 rounded-[var(--nf-radius-sm)] bg-[var(--nf-background)] px-3 py-2 text-[12px] text-[var(--nf-text-subtle)]">
        Your society's data is safe and untouched. Access resumes as soon as the subscription is
        renewed.
      </p>
    </BlockedShell>
  );
}

export function SocietyLockedPage() {
  const message = useAppSelector((s) => s.auth.errorMessage);
  return (
    <BlockedShell
      icon={<Lock />}
      tone="danger"
      title="Access locked"
      message={message ?? "This society has been locked. Please contact NestFlow support."}
    />
  );
}

export function ProvisioningPage() {
  return (
    <BlockedShell
      icon={<Clock />}
      tone="info"
      title="Setting up your society"
      message="Your society's workspace is still being prepared. This usually takes less than a minute."
    />
  );
}

export function UnauthorizedPage() {
  const navigate = useNavigate();
  return (
    <div className="flex min-h-[60vh] items-center justify-center p-6">
      <NFCard className="w-full max-w-md p-8 text-center">
        <span
          className="mx-auto mb-5 flex size-14 items-center justify-center rounded-full bg-[var(--nf-danger-subtle)] text-[var(--nf-danger)] [&_svg]:size-7"
          aria-hidden
        >
          <ShieldOff />
        </span>
        <h1 className="text-xl font-semibold text-[var(--nf-text)]">Not permitted</h1>
        <p className="mt-2.5 text-sm text-[var(--nf-text-muted)]">
          Your role does not have access to this section. If you believe this is a mistake, ask
          your society administrator to review your permissions.
        </p>
        <NFButton className="mt-7" onClick={() => navigate(-1)}>
          Go back
        </NFButton>
      </NFCard>
    </div>
  );
}

export function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <div className="flex min-h-[60vh] items-center justify-center p-6">
      <NFCard className="w-full max-w-md p-8 text-center">
        <p className="text-5xl font-bold tracking-tight text-[var(--nf-primary)]">404</p>
        <h1 className="mt-3 text-xl font-semibold text-[var(--nf-text)]">Page not found</h1>
        <p className="mt-2.5 text-sm text-[var(--nf-text-muted)]">
          That page does not exist, or it has moved.
        </p>
        <NFButton className="mt-7" onClick={() => navigate("/")}>
          Back to dashboard
        </NFButton>
      </NFCard>
    </div>
  );
}
