/**
 * NestFlow primitives.
 *
 * Radix supplies behaviour and accessibility; these supply the NestFlow look.
 * Feature code imports from here, never from a raw Radix package, so a
 * restyle is one file rather than two hundred.
 */

import { Slot } from "@radix-ui/react-slot";
import { type VariantProps, cva } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/utils/cn";
import { colorFromString, initials } from "@/utils/format";

/* -------------------------------------------------------------------------- */
/* Button                                                                     */
/* -------------------------------------------------------------------------- */

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium " +
    "transition-[background-color,border-color,color,box-shadow,transform] duration-150 " +
    "disabled:pointer-events-none disabled:opacity-50 active:translate-y-px " +
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--nf-ring)] " +
    "[&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--nf-primary)] text-[var(--nf-primary-foreground)] hover:bg-[var(--nf-primary-hover)] active:bg-[var(--nf-primary-active)] nf-shadow-sm",
        secondary:
          "bg-[var(--nf-surface)] text-[var(--nf-text)] border border-[var(--nf-border)] hover:bg-[var(--nf-primary-subtle)] hover:border-[var(--nf-border-strong)]",
        outline:
          "border border-[var(--nf-border-strong)] text-[var(--nf-text)] hover:bg-[var(--nf-primary-subtle)]",
        ghost: "text-[var(--nf-text-muted)] hover:bg-[var(--nf-primary-subtle)] hover:text-[var(--nf-text)]",
        danger: "bg-[var(--nf-danger)] text-white hover:brightness-110 nf-shadow-sm",
        link: "text-[var(--nf-primary)] underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-8 px-3 text-[13px] [&_svg]:size-3.5",
        md: "h-10 px-4 text-sm [&_svg]:size-4",
        lg: "h-11 px-5 text-[15px] [&_svg]:size-[18px]",
        icon: "size-10 [&_svg]:size-[18px]",
        "icon-sm": "size-8 [&_svg]:size-4",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface NFButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const NFButton = React.forwardRef<HTMLButtonElement, NFButtonProps>(
  ({ className, variant, size, asChild, loading, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), "rounded-[var(--nf-radius-sm)]", className)}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading ? (
          <>
            <Spinner className="size-4" />
            <span>{children}</span>
          </>
        ) : (
          children
        )}
      </Comp>
    );
  },
);
NFButton.displayName = "NFButton";

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cn("animate-spin", className)} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path
        d="M12 2a10 10 0 0 1 10 10"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

/* -------------------------------------------------------------------------- */
/* Input / Textarea / Select                                                  */
/* -------------------------------------------------------------------------- */

export interface NFInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
  leadingIcon?: React.ReactNode;
  trailingSlot?: React.ReactNode;
}

export const NFInput = React.forwardRef<HTMLInputElement, NFInputProps>(
  ({ className, invalid, leadingIcon, trailingSlot, ...props }, ref) => (
    <div className="relative">
      {leadingIcon && (
        <span
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--nf-text-subtle)] [&_svg]:size-4"
          aria-hidden
        >
          {leadingIcon}
        </span>
      )}
      <input
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cn(
          "h-10 w-full rounded-[var(--nf-radius-sm)] border bg-[var(--nf-surface)] px-3 text-sm text-[var(--nf-text)]",
          "placeholder:text-[var(--nf-text-subtle)] transition-colors",
          "focus:outline-none focus:ring-2 focus:ring-[var(--nf-ring)]/30 focus:border-[var(--nf-primary)]",
          "disabled:cursor-not-allowed disabled:opacity-60",
          leadingIcon && "pl-9",
          trailingSlot && "pr-10",
          invalid
            ? "border-[var(--nf-danger)] focus:ring-[var(--nf-danger)]/25 focus:border-[var(--nf-danger)]"
            : "border-[var(--nf-border)]",
          className,
        )}
        {...props}
      />
      {trailingSlot && (
        <span className="absolute right-2 top-1/2 -translate-y-1/2">{trailingSlot}</span>
      )}
    </div>
  ),
);
NFInput.displayName = "NFInput";

export const NFTextarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }
>(({ className, invalid, ...props }, ref) => (
  <textarea
    ref={ref}
    aria-invalid={invalid || undefined}
    className={cn(
      "min-h-20 w-full rounded-[var(--nf-radius-sm)] border bg-[var(--nf-surface)] px-3 py-2 text-sm text-[var(--nf-text)]",
      "placeholder:text-[var(--nf-text-subtle)] focus:outline-none focus:ring-2 focus:ring-[var(--nf-ring)]/30 focus:border-[var(--nf-primary)]",
      invalid ? "border-[var(--nf-danger)]" : "border-[var(--nf-border)]",
      className,
    )}
    {...props}
  />
));
NFTextarea.displayName = "NFTextarea";

export const NFSelect = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement> & { invalid?: boolean }
>(({ className, invalid, children, ...props }, ref) => (
  <select
    ref={ref}
    aria-invalid={invalid || undefined}
    className={cn(
      "h-10 w-full appearance-none rounded-[var(--nf-radius-sm)] border bg-[var(--nf-surface)] px-3 pr-9 text-sm text-[var(--nf-text)]",
      "bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%23667085%22 stroke-width=%222%22 stroke-linecap=%22round%22><path d=%22m6 9 6 6 6-6%22/></svg>')] bg-[length:16px] bg-[right_0.65rem_center] bg-no-repeat",
      "focus:outline-none focus:ring-2 focus:ring-[var(--nf-ring)]/30 focus:border-[var(--nf-primary)]",
      invalid ? "border-[var(--nf-danger)]" : "border-[var(--nf-border)]",
      className,
    )}
    {...props}
  >
    {children}
  </select>
));
NFSelect.displayName = "NFSelect";

/* -------------------------------------------------------------------------- */
/* Field — label + control + error, wired for screen readers                  */
/* -------------------------------------------------------------------------- */

export interface NFFieldProps {
  label: string;
  htmlFor?: string;
  error?: string;
  hint?: string;
  required?: boolean;
  className?: string;
  children: React.ReactNode;
}

export function NFField({
  label,
  htmlFor,
  error,
  hint,
  required,
  className,
  children,
}: NFFieldProps) {
  const errorId = error && htmlFor ? `${htmlFor}-error` : undefined;
  const hintId = hint && htmlFor ? `${htmlFor}-hint` : undefined;

  return (
    <div className={cn("space-y-1.5", className)}>
      <label
        htmlFor={htmlFor}
        className="block text-[13px] font-medium text-[var(--nf-text)]"
      >
        {label}
        {required && (
          <span className="ml-0.5 text-[var(--nf-danger)]" aria-hidden>
            *
          </span>
        )}
      </label>
      {/* aria-describedby is applied to the control by the caller via id
          convention, keeping errors announced rather than merely coloured. */}
      <div aria-describedby={cn(errorId, hintId) || undefined}>{children}</div>
      {hint && !error && (
        <p id={hintId} className="text-xs text-[var(--nf-text-subtle)]">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="text-xs font-medium text-[var(--nf-danger)]">
          {error}
        </p>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Card                                                                       */
/* -------------------------------------------------------------------------- */

export function NFCard({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-[var(--nf-radius)] border border-[var(--nf-border)] bg-[var(--nf-surface)] nf-shadow-sm",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function NFCardHeader({
  title,
  description,
  action,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-3 border-b border-[var(--nf-border)] px-5 py-4",
        className,
      )}
    >
      <div className="min-w-0">
        <h3 className="text-[15px] font-semibold text-[var(--nf-text)]">{title}</h3>
        {description && (
          <p className="mt-0.5 text-[13px] text-[var(--nf-text-muted)]">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}

export function NFCardBody({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return <div className={cn("p-5", className)}>{children}</div>;
}

/* -------------------------------------------------------------------------- */
/* Status badge                                                               */
/* -------------------------------------------------------------------------- */

export type BadgeTone = "neutral" | "success" | "warning" | "danger" | "info" | "primary";

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral:
    "bg-[var(--nf-background)] text-[var(--nf-text-muted)] border-[var(--nf-border-strong)]",
  success: "bg-[var(--nf-success-subtle)] text-[var(--nf-success)] border-[var(--nf-success)]/25",
  warning: "bg-[var(--nf-warning-subtle)] text-[var(--nf-warning)] border-[var(--nf-warning)]/25",
  danger: "bg-[var(--nf-danger-subtle)] text-[var(--nf-danger)] border-[var(--nf-danger)]/25",
  info: "bg-[var(--nf-info-subtle)] text-[var(--nf-info)] border-[var(--nf-info)]/25",
  primary:
    "bg-[var(--nf-primary-subtle)] text-[var(--nf-primary)] border-[var(--nf-primary)]/25",
};

/** Maps every backend status string to a tone, so colour is consistent. */
const STATUS_TONES: Record<string, BadgeTone> = {
  ACTIVE: "success",
  TRIAL: "info",
  PROVISIONING: "info",
  PROVISIONING_FAILED: "danger",
  LOCKED: "danger",
  SUSPENDED: "warning",
  ARCHIVED: "neutral",
  EXPIRED: "danger",
  CANCELLED: "neutral",
  COMPLETED: "success",
  FAILED: "danger",
  PENDING: "warning",
  DRAFT: "neutral",
  PUBLISHED: "success",
  PAID: "success",
  UNPAID: "warning",
  PARTIAL: "warning",
  OVERDUE: "danger",
};

export function NFStatusBadge({
  status,
  tone,
  className,
}: {
  status: string;
  tone?: BadgeTone;
  className?: string;
}) {
  const resolved = tone ?? STATUS_TONES[status] ?? "neutral";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide",
        TONE_CLASSES[resolved],
        className,
      )}
    >
      <span className="size-1.5 rounded-full bg-current" aria-hidden />
      {status.replace(/_/g, " ")}
    </span>
  );
}

/* -------------------------------------------------------------------------- */
/* Page header, empty state, skeleton                                          */
/* -------------------------------------------------------------------------- */

export function NFPageHeader({
  title,
  description,
  actions,
  breadcrumb,
  className,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  breadcrumb?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-6", className)}>
      {breadcrumb && <div className="mb-2">{breadcrumb}</div>}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-[var(--nf-text)] sm:text-2xl">
            {title}
          </h1>
          {description && (
            <p className="mt-1 max-w-2xl text-sm text-[var(--nf-text-muted)]">{description}</p>
          )}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

export function NFEmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-14 text-center", className)}>
      {icon && (
        <div
          className="mb-4 flex size-12 items-center justify-center rounded-full bg-[var(--nf-primary-subtle)] text-[var(--nf-primary)] [&_svg]:size-6"
          aria-hidden
        >
          {icon}
        </div>
      )}
      <h3 className="text-[15px] font-semibold text-[var(--nf-text)]">{title}</h3>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm text-[var(--nf-text-muted)]">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function NFSkeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-[var(--nf-radius-sm)] bg-[var(--nf-border)]", className)}
      aria-hidden
    />
  );
}

/* -------------------------------------------------------------------------- */
/* Avatar                                                                     */
/* -------------------------------------------------------------------------- */

export function NFAvatar({
  name,
  src,
  size = 36,
  className,
}: {
  name: string;
  src?: string | null;
  size?: number;
  className?: string;
}) {
  const [failed, setFailed] = React.useState(false);

  if (src && !failed) {
    return (
      <img
        src={src}
        alt=""
        width={size}
        height={size}
        onError={() => setFailed(true)}
        className={cn("shrink-0 rounded-full object-cover", className)}
        style={{ width: size, height: size }}
      />
    );
  }

  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white",
        className,
      )}
      style={{ width: size, height: size, backgroundColor: colorFromString(name), fontSize: size * 0.38 }}
      aria-hidden
    >
      {initials(name)}
    </span>
  );
}
