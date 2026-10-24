import { Mail, Phone, Shield } from "lucide-react";

import {
  NFAvatar,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFPageHeader,
  NFStatusBadge,
} from "@/components/nestflow/primitives";
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
