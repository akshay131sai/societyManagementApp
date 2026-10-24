/**
 * Maintenance and housekeeping.
 *
 * One component, two routes — the same trick the utility page uses. The two
 * departments have identical workflows and different permissions, so the only
 * things that vary are the endpoint prefix, the permission strings and the
 * words on the screen.
 *
 * Two screens in one: **Tasks** is what a worker opens (their list, and the
 * button that moves a job along), **Schedules** is what a supervisor opens (the
 * recurring plan the tasks come from). A worker with only the progress
 * permission never sees the second tab.
 */

import {
  CalendarClock,
  CheckCircle2,
  CirclePlay,
  ClipboardList,
  IndianRupee,
  Plus,
  RefreshCw,
  TriangleAlert,
} from "lucide-react";
import * as React from "react";

import {
  NFDataTable,
  NFDialog,
  NFPagination,
  NFSearch,
  NFStatCard,
  type Column,
} from "@/components/nestflow/data";
import {
  NFButton,
  NFCard,
  NFCardBody,
  NFCardHeader,
  NFEmptyState,
  NFField,
  NFInput,
  NFPageHeader,
  NFSelect,
  NFStatusBadge,
  NFTextarea,
  type BadgeTone,
} from "@/components/nestflow/primitives";
import { ApiError, api, type Page } from "@/services/api";
import { useAppSelector } from "@/store";
import type {
  Department,
  Priority,
  Recurrence,
  ScheduleRunResult,
  TaskStatus,
  TenantUser,
  WorkSchedule,
  WorkSummary,
  WorkTask,
} from "@/types";
import { formatCurrency, formatDate, formatRelative } from "@/utils/format";
import { hasPermission } from "@/utils/permissions";

const LIMIT = 20;

const STATUS_TONE: Record<TaskStatus, BadgeTone> = {
  PENDING: "warning",
  IN_PROGRESS: "info",
  COMPLETED: "primary",
  VERIFIED: "success",
  CANCELLED: "neutral",
  SKIPPED: "neutral",
};

const PRIORITY_TONE: Record<Priority, BadgeTone> = {
  LOW: "neutral",
  MEDIUM: "info",
  HIGH: "warning",
  URGENT: "danger",
};

const TRANSITION_LABEL: Record<TaskStatus, string> = {
  PENDING: "Reopen",
  IN_PROGRESS: "Start",
  COMPLETED: "Mark done",
  VERIFIED: "Verify",
  CANCELLED: "Cancel",
  SKIPPED: "Skip",
};

/** The API insists on a reason for these, so the dialog must ask for one. */
const REASON_REQUIRED: TaskStatus[] = ["CANCELLED", "SKIPPED"];

const RECURRENCES: Recurrence[] = [
  "DAILY",
  "WEEKLY",
  "FORTNIGHTLY",
  "MONTHLY",
  "QUARTERLY",
  "HALF_YEARLY",
  "YEARLY",
];

const PRIORITIES: Priority[] = ["LOW", "MEDIUM", "HIGH", "URGENT"];

const humanise = (value: string) =>
  value.charAt(0) + value.slice(1).toLowerCase().replace(/_/g, " ");

export default function WorkPage({ department }: { department: Department }) {
  const isMaintenance = department === "MAINTENANCE";
  const route = isMaintenance ? "maintenance" : "housekeeping";
  const label = isMaintenance ? "Maintenance" : "Housekeeping";
  const prefix = isMaintenance ? "maintenance" : "housekeeping";

  const principal = useAppSelector((s) => s.auth.principal);
  const canManage = hasPermission(principal, `${prefix}.manage`);
  const canProgress =
    hasPermission(principal, `${prefix}.task.progress`) || canManage;

  const [tab, setTab] = React.useState<"tasks" | "schedules">("tasks");
  const [page, setPage] = React.useState(1);
  const [q, setQ] = React.useState("");
  const [scope, setScope] = React.useState<"open" | "overdue" | "mine" | "all">("open");
  const [tasks, setTasks] = React.useState<Page<WorkTask> | null>(null);
  const [schedules, setSchedules] = React.useState<Page<WorkSchedule> | null>(null);
  const [summary, setSummary] = React.useState<WorkSummary | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [progressing, setProgressing] = React.useState<{
    task: WorkTask;
    status: TaskStatus;
  } | null>(null);
  const [addingTask, setAddingTask] = React.useState(false);
  const [addingSchedule, setAddingSchedule] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [banner, setBanner] = React.useState<string | null>(null);
  const [reload, setReload] = React.useState(0);

  React.useEffect(() => {
    setPage(1);
  }, [tab]);

  React.useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    const request =
      tab === "tasks"
        ? api
            .get<Page<WorkTask>>(
              `/${route}/tasks`,
              {
                page,
                limit: LIMIT,
                q: q || undefined,
                open_only: scope === "open" || undefined,
                overdue_only: scope === "overdue" || undefined,
                mine_only: scope === "mine" || undefined,
              },
              controller.signal,
            )
            .then(setTasks)
        : api
            .get<Page<WorkSchedule>>(
              `/${route}/schedules`,
              { page, limit: LIMIT, q: q || undefined },
              controller.signal,
            )
            .then(setSchedules);

    request.catch(() => undefined).finally(() => setLoading(false));
    return () => controller.abort();
  }, [route, tab, page, q, scope, reload]);

  React.useEffect(() => {
    const controller = new AbortController();
    api
      .get<WorkSummary>(`/${route}/summary`, undefined, controller.signal)
      .then(setSummary)
      .catch(() => undefined);
    return () => controller.abort();
  }, [route, reload]);

  async function generate() {
    setGenerating(true);
    try {
      const result = await api.post<ScheduleRunResult>(`/${route}/schedules/generate`);
      setBanner(
        result.tasks_created === 0
          ? "Nothing was due — every scheduled task for now already exists."
          : `${result.tasks_created} task(s) raised from ${result.schedules_examined} schedule(s).`,
      );
      setReload((n) => n + 1);
    } catch (e) {
      setBanner(e instanceof ApiError ? e.message : "Could not generate tasks.");
    } finally {
      setGenerating(false);
    }
  }

  const taskColumns: Column<WorkTask>[] = [
    {
      key: "title",
      header: "Task",
      render: (t) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--nf-text)]">{t.title}</p>
          <p className="mt-0.5 truncate text-[11px] text-[var(--nf-text-subtle)]">
            {[t.area, t.building_name, t.schedule_title && `from “${t.schedule_title}”`]
              .filter(Boolean)
              .join(" · ") || "Ad hoc"}
          </p>
        </div>
      ),
    },
    {
      key: "priority",
      header: "Priority",
      hideOnMobile: true,
      render: (t) => <NFStatusBadge status={t.priority} tone={PRIORITY_TONE[t.priority]} />,
    },
    {
      key: "due",
      header: "Due",
      render: (t) => (
        <span className={t.is_overdue ? "font-medium text-[var(--nf-danger)]" : undefined}>
          {formatDate(t.due_on)}
          {t.is_overdue && " · overdue"}
        </span>
      ),
    },
    {
      key: "assignee",
      header: "Assigned to",
      hideOnMobile: true,
      render: (t) => t.assignee_name ?? "—",
    },
    {
      key: "status",
      header: "Status",
      render: (t) => <NFStatusBadge status={t.status} tone={STATUS_TONE[t.status]} />,
    },
    ...(canProgress
      ? [
          {
            key: "actions",
            header: "",
            className: "text-right",
            render: (t: WorkTask) => (
              <div className="flex justify-end gap-1.5">
                {t.allowed_transitions.map((next) => (
                  <NFButton
                    key={next}
                    size="sm"
                    variant={next === "VERIFIED" ? "primary" : "secondary"}
                    onClick={(e) => {
                      e.stopPropagation();
                      setProgressing({ task: t, status: next });
                    }}
                  >
                    {next === "IN_PROGRESS" && <CirclePlay />}
                    {next === "COMPLETED" && <CheckCircle2 />}
                    {TRANSITION_LABEL[next]}
                  </NFButton>
                ))}
              </div>
            ),
          },
        ]
      : []),
  ];

  const scheduleColumns: Column<WorkSchedule>[] = [
    {
      key: "title",
      header: "Schedule",
      render: (s) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-[var(--nf-text)]">{s.title}</p>
          <p className="mt-0.5 truncate text-[11px] text-[var(--nf-text-subtle)]">
            {[s.area, s.building_name, s.vendor_name].filter(Boolean).join(" · ") || "—"}
          </p>
        </div>
      ),
    },
    { key: "recurrence", header: "Every", render: (s) => humanise(s.recurrence) },
    {
      key: "next",
      header: "Next due",
      render: (s) => (
        <span>
          {formatDate(s.next_due_on)}
          <span className="ml-1 text-[11px] text-[var(--nf-text-subtle)]">
            {formatRelative(s.next_due_on)}
          </span>
        </span>
      ),
    },
    {
      key: "open",
      header: "Open tasks",
      hideOnMobile: true,
      className: "text-right tabular-nums",
      headerClassName: "text-right",
      render: (s) => s.open_tasks,
    },
    {
      key: "cost",
      header: "Estimate",
      hideOnMobile: true,
      className: "text-right tabular-nums",
      headerClassName: "text-right",
      render: (s) => (s.estimated_cost ? formatCurrency(s.estimated_cost) : "—"),
    },
  ];

  return (
    <>
      <NFPageHeader
        title={label}
        description={
          isMaintenance
            ? "Repairs, servicing and the recurring contracts the society runs on."
            : "Cleaning rounds and the recurring schedules behind them."
        }
        actions={
          canManage ? (
            <div className="flex gap-2">
              <NFButton variant="secondary" onClick={generate} loading={generating}>
                <RefreshCw /> Generate due
              </NFButton>
              <NFButton
                onClick={() => (tab === "tasks" ? setAddingTask(true) : setAddingSchedule(true))}
              >
                <Plus /> {tab === "tasks" ? "New task" : "New schedule"}
              </NFButton>
            </div>
          ) : undefined
        }
      />

      {banner && (
        <div className="mb-6 flex items-start justify-between gap-3 rounded-[var(--nf-radius)] border border-[var(--nf-info)]/30 bg-[var(--nf-info-subtle)] p-4">
          <p className="text-[13px] text-[var(--nf-text)]">{banner}</p>
          <button
            type="button"
            onClick={() => setBanner(null)}
            className="text-[11px] font-semibold text-[var(--nf-info)]"
          >
            Dismiss
          </button>
        </div>
      )}

      {summary && (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <NFStatCard
            label="Open"
            value={summary.pending + summary.in_progress}
            icon={<ClipboardList />}
            tone="info"
            hint={`${summary.pending} pending · ${summary.in_progress} in progress`}
          />
          <NFStatCard
            label="Overdue"
            value={summary.overdue}
            icon={<TriangleAlert />}
            tone={summary.overdue > 0 ? "danger" : "success"}
          />
          <NFStatCard
            label="Awaiting sign-off"
            value={summary.awaiting_verification}
            icon={<CheckCircle2 />}
            tone={summary.awaiting_verification > 0 ? "warning" : "success"}
            hint="Done by the worker, not yet checked"
          />
          <NFStatCard
            label="Spend this month"
            value={formatCurrency(summary.cost_this_month)}
            icon={<IndianRupee />}
            tone="primary"
            hint={`${summary.active_schedules} active schedule(s)`}
          />
        </div>
      )}

      <NFCard>
        <NFCardHeader
          title={
            <div className="flex gap-1 rounded-[var(--nf-radius-sm)] bg-[var(--nf-background)] p-0.5">
              {(["tasks", "schedules"] as const)
                .filter((t) => t === "tasks" || canManage)
                .map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setTab(t)}
                    aria-pressed={tab === t}
                    className={
                      tab === t
                        ? "rounded-[var(--nf-radius-sm)] bg-[var(--nf-surface)] px-3 py-1.5 text-[13px] font-semibold text-[var(--nf-text)] nf-shadow-sm"
                        : "rounded-[var(--nf-radius-sm)] px-3 py-1.5 text-[13px] font-medium text-[var(--nf-text-muted)]"
                    }
                  >
                    {t === "tasks" ? "Tasks" : "Schedules"}
                  </button>
                ))}
            </div>
          }
          action={
            <div className="flex flex-wrap items-center gap-2">
              <NFSearch
                value={q}
                onChange={(value) => {
                  setQ(value);
                  setPage(1);
                }}
                placeholder="Search by title"
              />
              {tab === "tasks" && (
                <NFSelect
                  aria-label="Scope"
                  value={scope}
                  onChange={(e) => {
                    setScope(e.target.value as typeof scope);
                    setPage(1);
                  }}
                  className="sm:w-40"
                >
                  <option value="open">Open</option>
                  <option value="overdue">Overdue</option>
                  <option value="mine">Assigned to me</option>
                  <option value="all">All</option>
                </NFSelect>
              )}
            </div>
          }
        />
        <NFCardBody className="px-0 pb-0">
          {tab === "tasks" ? (
            <NFDataTable
              caption={`${label} tasks`}
              columns={taskColumns}
              rows={tasks?.items ?? []}
              rowKey={(t) => t.id}
              loading={loading}
              empty={
                <div className="px-5 pb-5">
                  <NFEmptyState
                    icon={<ClipboardList />}
                    title="Nothing to do"
                    description={
                      canManage
                        ? "Create a task, or set up a schedule so they appear on their own."
                        : "No tasks match this filter."
                    }
                  />
                </div>
              }
            />
          ) : (
            <NFDataTable
              caption={`${label} schedules`}
              columns={scheduleColumns}
              rows={schedules?.items ?? []}
              rowKey={(s) => s.id}
              loading={loading}
              empty={
                <div className="px-5 pb-5">
                  <NFEmptyState
                    icon={<CalendarClock />}
                    title="No schedules yet"
                    description="A schedule describes the intention — “the lift is serviced monthly” — and raises the task for you each time it comes round."
                  />
                </div>
              }
            />
          )}

          {(tab === "tasks" ? tasks : schedules) && (
            <div className="px-5 py-4">
              <NFPagination
                page={(tab === "tasks" ? tasks : schedules)!.page}
                pages={(tab === "tasks" ? tasks : schedules)!.pages}
                total={(tab === "tasks" ? tasks : schedules)!.total}
                limit={LIMIT}
                onPageChange={setPage}
              />
            </div>
          )}
        </NFCardBody>
      </NFCard>

      {progressing && (
        <ProgressDialog
          route={route}
          task={progressing.task}
          status={progressing.status}
          showCost={isMaintenance}
          onClose={() => setProgressing(null)}
          onSaved={() => {
            setProgressing(null);
            setReload((n) => n + 1);
          }}
        />
      )}

      {canManage && (
        <>
          <TaskDialog
            open={addingTask}
            route={route}
            label={label}
            onOpenChange={setAddingTask}
            onSaved={() => {
              setAddingTask(false);
              setReload((n) => n + 1);
            }}
          />
          <ScheduleDialog
            open={addingSchedule}
            route={route}
            label={label}
            onOpenChange={setAddingSchedule}
            onSaved={() => {
              setAddingSchedule(false);
              setReload((n) => n + 1);
            }}
          />
        </>
      )}
    </>
  );
}

/* -------------------------------------------------------------------------- */

function ProgressDialog({
  route,
  task,
  status,
  showCost,
  onClose,
  onSaved,
}: {
  route: string;
  task: WorkTask;
  status: TaskStatus;
  showCost: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [notes, setNotes] = React.useState("");
  const [cost, setCost] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const reasonRequired = REASON_REQUIRED.includes(status);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await api.post(`/${route}/tasks/${task.id}/progress`, {
        status,
        notes: notes || null,
        actual_cost: cost ? cost : null,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not update this task.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <NFDialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={`${TRANSITION_LABEL[status]}: ${task.title}`}
      size="sm"
      footer={
        <div className="flex justify-end gap-2">
          <NFButton variant="secondary" onClick={onClose}>
            Cancel
          </NFButton>
          <NFButton
            onClick={submit}
            loading={saving}
            disabled={reasonRequired && !notes.trim()}
          >
            {TRANSITION_LABEL[status]}
          </NFButton>
        </div>
      }
    >
      <div className="space-y-4">
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
          >
            {error}
          </p>
        )}
        <NFField
          label={reasonRequired ? "Why not?" : "Notes"}
          htmlFor="p-notes"
          required={reasonRequired}
          hint={reasonRequired ? undefined : "What was done, and anything worth recording."}
        >
          <NFTextarea
            id="p-notes"
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            autoFocus
          />
        </NFField>
        {showCost && status === "COMPLETED" && (
          <NFField label="What did it cost?" htmlFor="p-cost" hint="Optional">
            <NFInput
              id="p-cost"
              type="number"
              min="0"
              step="1"
              value={cost}
              onChange={(e) => setCost(e.target.value)}
            />
          </NFField>
        )}
      </div>
    </NFDialog>
  );
}

function useStaff(enabled: boolean): TenantUser[] {
  const [staff, setStaff] = React.useState<TenantUser[]>([]);
  React.useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    api
      .get<Page<TenantUser>>("/users", { limit: 100 }, controller.signal)
      .then((r) => setStaff(r.items))
      .catch(() => undefined);
    return () => controller.abort();
  }, [enabled]);
  return staff;
}

function TaskDialog({
  open,
  route,
  label,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  route: string;
  label: string;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const staff = useStaff(open);
  const [title, setTitle] = React.useState("");
  const [dueOn, setDueOn] = React.useState(() => new Date().toISOString().slice(0, 10));
  const [area, setArea] = React.useState("");
  const [priority, setPriority] = React.useState<Priority>("MEDIUM");
  const [assignee, setAssignee] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setTitle("");
    setArea("");
    setAssignee("");
    setError(null);
  }, [open]);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await api.post(`/${route}/tasks`, {
        title,
        due_on: dueOn,
        area: area || null,
        priority,
        assigned_to: assignee || null,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create this task.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <NFDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`New ${label.toLowerCase()} task`}
      footer={
        <div className="flex justify-end gap-2">
          <NFButton variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </NFButton>
          <NFButton onClick={submit} loading={saving} disabled={!title.trim()}>
            Create
          </NFButton>
        </div>
      }
    >
      <div className="space-y-4">
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
          >
            {error}
          </p>
        )}
        <NFField label="What needs doing?" htmlFor="t-title" required>
          <NFInput
            id="t-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            autoFocus
          />
        </NFField>
        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Due on" htmlFor="t-due" required>
            <NFInput
              id="t-due"
              type="date"
              value={dueOn}
              onChange={(e) => setDueOn(e.target.value)}
            />
          </NFField>
          <NFField label="Priority" htmlFor="t-pri">
            <NFSelect
              id="t-pri"
              value={priority}
              onChange={(e) => setPriority(e.target.value as Priority)}
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {humanise(p)}
                </option>
              ))}
            </NFSelect>
          </NFField>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Where?" htmlFor="t-area" hint="Optional">
            <NFInput
              id="t-area"
              value={area}
              onChange={(e) => setArea(e.target.value)}
              placeholder="Tower A lobby"
            />
          </NFField>
          <NFField label="Assign to" htmlFor="t-who" hint="Optional">
            <NFSelect
              id="t-who"
              value={assignee}
              onChange={(e) => setAssignee(e.target.value)}
            >
              <option value="">Nobody yet</option>
              {staff.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name}
                </option>
              ))}
            </NFSelect>
          </NFField>
        </div>
      </div>
    </NFDialog>
  );
}

function ScheduleDialog({
  open,
  route,
  label,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  route: string;
  label: string;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const staff = useStaff(open);
  const [title, setTitle] = React.useState("");
  const [recurrence, setRecurrence] = React.useState<Recurrence>("MONTHLY");
  const [startsOn, setStartsOn] = React.useState(() => new Date().toISOString().slice(0, 10));
  const [leadDays, setLeadDays] = React.useState("3");
  const [area, setArea] = React.useState("");
  const [vendor, setVendor] = React.useState("");
  const [cost, setCost] = React.useState("");
  const [assignee, setAssignee] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setTitle("");
    setArea("");
    setVendor("");
    setCost("");
    setAssignee("");
    setError(null);
  }, [open]);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      await api.post(`/${route}/schedules`, {
        title,
        recurrence,
        starts_on: startsOn,
        lead_days: Number(leadDays) || 0,
        area: area || null,
        vendor_name: vendor || null,
        estimated_cost: cost || null,
        assigned_to: assignee || null,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create this schedule.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <NFDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`New ${label.toLowerCase()} schedule`}
      description="The task is raised for you each time it comes round."
      footer={
        <div className="flex justify-end gap-2">
          <NFButton variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </NFButton>
          <NFButton onClick={submit} loading={saving} disabled={!title.trim()}>
            Create
          </NFButton>
        </div>
      }
    >
      <div className="space-y-4">
        {error && (
          <p
            role="alert"
            className="rounded-[var(--nf-radius-sm)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] px-3 py-2 text-[13px] text-[var(--nf-danger)]"
          >
            {error}
          </p>
        )}
        <NFField label="What repeats?" htmlFor="s-title" required>
          <NFInput
            id="s-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Lift service"
            autoFocus
          />
        </NFField>
        <div className="grid gap-4 sm:grid-cols-3">
          <NFField label="Every" htmlFor="s-rec">
            <NFSelect
              id="s-rec"
              value={recurrence}
              onChange={(e) => setRecurrence(e.target.value as Recurrence)}
            >
              {RECURRENCES.map((r) => (
                <option key={r} value={r}>
                  {humanise(r)}
                </option>
              ))}
            </NFSelect>
          </NFField>
          <NFField label="Starting" htmlFor="s-start" required>
            <NFInput
              id="s-start"
              type="date"
              value={startsOn}
              onChange={(e) => setStartsOn(e.target.value)}
            />
          </NFField>
          <NFField
            label="Raise it"
            htmlFor="s-lead"
            hint="Days early, so a worker sees it coming"
          >
            <NFInput
              id="s-lead"
              type="number"
              min="0"
              max="90"
              value={leadDays}
              onChange={(e) => setLeadDays(e.target.value)}
            />
          </NFField>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Where?" htmlFor="s-area" hint="Optional">
            <NFInput id="s-area" value={area} onChange={(e) => setArea(e.target.value)} />
          </NFField>
          <NFField label="Assign to" htmlFor="s-who" hint="Optional">
            <NFSelect
              id="s-who"
              value={assignee}
              onChange={(e) => setAssignee(e.target.value)}
            >
              <option value="">Nobody yet</option>
              {staff.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name}
                </option>
              ))}
            </NFSelect>
          </NFField>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <NFField label="Vendor" htmlFor="s-vendor" hint="Optional">
            <NFInput id="s-vendor" value={vendor} onChange={(e) => setVendor(e.target.value)} />
          </NFField>
          <NFField label="Estimated cost" htmlFor="s-cost" hint="Optional">
            <NFInput
              id="s-cost"
              type="number"
              min="0"
              step="1"
              value={cost}
              onChange={(e) => setCost(e.target.value)}
            />
          </NFField>
        </div>
      </div>
    </NFDialog>
  );
}
