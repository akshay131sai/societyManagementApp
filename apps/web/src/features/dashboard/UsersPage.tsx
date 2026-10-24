import { Plus, Users } from "lucide-react";
import * as React from "react";
import { useForm } from "react-hook-form";

import {
  NFDataTable,
  NFDialog,
  NFPagination,
  NFSearch,
  type Column,
} from "@/components/nestflow/data";
import {
  NFAvatar,
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
import { useAppSelector } from "@/store";
import type { Role, TenantUser } from "@/types";
import { formatDate, formatPhone } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

interface CreateForm {
  email: string;
  full_name: string;
  phone: string;
  role_code: string;
}

export default function UsersPage() {
  const principal = useAppSelector((s) => s.auth.principal);
  const canCreate = hasPermission(principal, "user.create");
  const canAssignRoles = hasPermission(principal, "role.assign");

  const [data, setData] = React.useState<Page<TenantUser> | null>(null);
  const [roles, setRoles] = React.useState<Role[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [roleFilter, setRoleFilter] = React.useState("");
  const [createOpen, setCreateOpen] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [refreshKey, setRefreshKey] = React.useState(0);

  const [debouncedQ, setDebouncedQ] = React.useState("");
  React.useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQ(q);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  React.useEffect(() => {
    if (canAssignRoles || canCreate) {
      api.get<Role[]>("/roles").then(setRoles).catch(() => setRoles([]));
    }
  }, [canAssignRoles, canCreate]);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api
      .get<Page<TenantUser>>(
        "/users",
        { page, limit: 25, q: debouncedQ, role: roleFilter },
        controller.signal,
      )
      .then(setData)
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setData(null);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [page, debouncedQ, roleFilter, refreshKey]);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<CreateForm>({ defaultValues: { role_code: "FLAT_OWNER" } });

  const onCreate = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await api.post("/users", {
        email: values.email,
        full_name: values.full_name,
        phone: values.phone || null,
        role_codes: [values.role_code],
      });
      setCreateOpen(false);
      reset();
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setFormError(e instanceof ApiError ? e.message : "Could not create this user.");
    }
  });

  const columns: Column<TenantUser>[] = [
    {
      key: "user",
      header: "Member",
      render: (u) => (
        <div className="flex min-w-0 items-center gap-3">
          <NFAvatar name={u.full_name} src={u.avatar_url} size={34} />
          <div className="min-w-0">
            <p className="truncate font-medium text-[var(--nf-text)]">{u.full_name}</p>
            <p className="truncate text-xs text-[var(--nf-text-muted)]">{u.email}</p>
          </div>
        </div>
      ),
    },
    {
      key: "roles",
      header: "Roles",
      render: (u) => (
        <div className="flex flex-wrap gap-1">
          {u.roles.map((r) => (
            <span
              key={r}
              className="rounded-full bg-[var(--nf-primary-subtle)] px-2 py-0.5 text-[11px] font-medium text-[var(--nf-primary)]"
            >
              {r.replace(/_/g, " ")}
            </span>
          ))}
        </div>
      ),
    },
    {
      key: "phone",
      header: "Phone",
      hideOnMobile: true,
      render: (u) => (
        <span className="text-[var(--nf-text-muted)]">{formatPhone(u.phone)}</span>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (u) => <NFStatusBadge status={u.is_active ? "ACTIVE" : "SUSPENDED"} />,
    },
    {
      key: "last_login",
      header: "Last sign-in",
      hideOnMobile: true,
      render: (u) => (
        <span className="text-[var(--nf-text-muted)]">
          {u.last_login_at ? formatDate(u.last_login_at) : "Never"}
        </span>
      ),
    },
  ];

  return (
    <>
      <NFPageHeader
        title="Users & roles"
        description="Everyone who can sign in to this society, and what they are allowed to do."
        actions={
          canCreate ? (
            <NFButton onClick={() => setCreateOpen(true)}>
              <Plus /> Add member
            </NFButton>
          ) : undefined
        }
      />

      <NFCard>
        <div className="flex flex-wrap items-center gap-3 border-b border-[var(--nf-border)] p-4">
          <NFSearch value={q} onChange={setQ} placeholder="Search by name or email…" />
          <NFSelect
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setPage(1);
            }}
            aria-label="Filter by role"
            className="sm:w-56"
          >
            <option value="">All roles</option>
            {roles.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </NFSelect>
        </div>

        <NFDataTable
          caption="Society members and their roles"
          columns={columns}
          rows={data?.items ?? []}
          rowKey={(u) => u.id}
          loading={loading}
          empty={
            <NFEmptyState
              icon={<Users />}
              title={q || roleFilter ? "No matching members" : "No members yet"}
              description={
                q || roleFilter
                  ? "Try a different search term or clear the role filter."
                  : "Add residents, staff and guards so they can sign in."
              }
              action={
                canCreate && !q && !roleFilter ? (
                  <NFButton onClick={() => setCreateOpen(true)}>
                    <Plus /> Add the first member
                  </NFButton>
                ) : undefined
              }
            />
          }
        />

        {data && (
          <NFPagination
            page={data.page}
            pages={data.pages}
            total={data.total}
            limit={data.limit}
            onPageChange={setPage}
          />
        )}
      </NFCard>

      <NFDialog
        open={createOpen}
        onOpenChange={(o) => {
          setCreateOpen(o);
          if (!o) {
            reset();
            setFormError(null);
          }
        }}
        title="Add a member"
        description="They can sign in with this email once their identity provider account exists."
        footer={
          <>
            <NFButton variant="secondary" onClick={() => setCreateOpen(false)}>
              Cancel
            </NFButton>
            <NFButton onClick={onCreate} loading={isSubmitting}>
              Add member
            </NFButton>
          </>
        }
      >
        <form onSubmit={onCreate} className="space-y-4" noValidate>
          {formError && (
            <p
              role="alert"
              className="rounded-[var(--nf-radius-sm)] bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
            >
              {formError}
            </p>
          )}

          <NFField label="Full name" htmlFor="full_name" error={errors.full_name?.message} required>
            <NFInput
              id="full_name"
              placeholder="Sneha Kulkarni"
              invalid={!!errors.full_name}
              {...register("full_name", { required: "Enter their full name." })}
            />
          </NFField>

          <NFField label="Email address" htmlFor="email" error={errors.email?.message} required>
            <NFInput
              id="email"
              type="email"
              placeholder="resident@society.in"
              invalid={!!errors.email}
              {...register("email", {
                required: "Enter their email address.",
                pattern: { value: /^\S+@\S+\.\S+$/, message: "Not a valid email address." },
              })}
            />
          </NFField>

          <NFField label="Phone" htmlFor="phone" error={errors.phone?.message}>
            <NFInput
              id="phone"
              inputMode="tel"
              maxLength={10}
              placeholder="9822012345"
              invalid={!!errors.phone}
              {...register("phone", {
                pattern: { value: /^[6-9][0-9]{9}$/, message: "Ten digits, starting with 6–9." },
              })}
            />
          </NFField>

          <NFField label="Role" htmlFor="role_code" required>
            <NFSelect id="role_code" {...register("role_code", { required: true })}>
              {roles.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.name}
                </option>
              ))}
            </NFSelect>
          </NFField>
        </form>
      </NFDialog>
    </>
  );
}
