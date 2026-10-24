/**
 * The Bill Builder.
 *
 * Three panels: presets and line items on the left, the formula tree in the
 * middle, a live preview on the right. The preview calls the **real** backend
 * engine against a **real** flat — it is not a client-side approximation, so
 * what the admin sees is what residents will be billed.
 */

import {
  AlertTriangle,
  ArrowLeft,
  Check,
  FileText,
  History,
  Plus,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react";
import * as React from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { NFDialog } from "@/components/nestflow/data";
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
  NFStatusBadge,
  NFTextarea,
} from "@/components/nestflow/primitives";
import { NodeEditor } from "@/features/billing/NodeEditor";
import {
  PRESETS,
  countNodes,
  describe,
  emptyLineItem,
} from "@/features/billing/formulaModel";
import { ApiError, api, type Page } from "@/services/api";
import type {
  BillTemplateDetail,
  FieldSpec,
  Flat,
  FormulaDefinition,
  FormulaError,
  LineItemSpec,
  PreviewResult,
} from "@/types";
import { cn } from "@/utils/cn";
import { formatCurrency } from "@/utils/format";

const FREQUENCIES: { value: string; label: string }[] = [
  { value: "MONTHLY", label: "Monthly" },
  { value: "QUARTERLY", label: "Quarterly" },
  { value: "HALF_YEARLY", label: "Half-yearly (Apr–Sep / Oct–Mar)" },
  { value: "YEARLY", label: "Yearly (Apr–Mar)" },
];

export default function BillBuilderPage() {
  const { templateId } = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const editing = Boolean(templateId);

  const [fields, setFields] = React.useState<FieldSpec[]>([]);
  const [flats, setFlats] = React.useState<Flat[]>([]);
  const [template, setTemplate] = React.useState<BillTemplateDetail | null>(null);
  const [loading, setLoading] = React.useState(true);

  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [frequency, setFrequency] = React.useState("MONTHLY");
  const [baseMaintenance, setBaseMaintenance] = React.useState("3000");
  const [lineItems, setLineItems] = React.useState<LineItemSpec[]>([]);
  const [selected, setSelected] = React.useState(0);

  const [previewFlatId, setPreviewFlatId] = React.useState<string>("");
  const [preview, setPreview] = React.useState<PreviewResult | null>(null);
  const [previewing, setPreviewing] = React.useState(false);

  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [presetOpen, setPresetOpen] = React.useState(false);
  const [versionNotes, setVersionNotes] = React.useState("");

  /* ---------------------------------------------------------------- */

  React.useEffect(() => {
    (async () => {
      try {
        const [f, flatPage] = await Promise.all([
          api.get<FieldSpec[]>("/billing/fields"),
          api.get<Page<Flat>>("/flats", { limit: 50 }),
        ]);
        setFields(f);
        setFlats(flatPage.items);
        setPreviewFlatId(flatPage.items[0]?.id ?? "");

        if (templateId) {
          const t = await api.get<BillTemplateDetail>(`/bill-templates/${templateId}`);
          setTemplate(t);
          setName(t.name);
          setDescription(t.description ?? "");
          setFrequency(t.frequency);
          const active =
            t.versions.find((v) => v.id === t.active_version_id) ?? t.versions[0];
          if (active) {
            setLineItems(active.formula.line_items ?? []);
            setBaseMaintenance(String(active.parameters?.base_maintenance ?? "3000"));
          }
        } else {
          const presetName = search.get("preset");
          const preset = PRESETS.find((p) => p.name === presetName) ?? PRESETS[2];
          setLineItems(preset.build());
        }
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Could not load the Bill Builder.");
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateId]);

  const definition: FormulaDefinition = React.useMemo(
    () => ({ line_items: lineItems }),
    [lineItems],
  );

  /* --- Live preview, debounced --------------------------------------- */
  React.useEffect(() => {
    if (!lineItems.length) {
      setPreview(null);
      return;
    }
    const handle = setTimeout(async () => {
      setPreviewing(true);
      try {
        setPreview(
          await api.post<PreviewResult>("/billing/preview", {
            formula: definition,
            parameters: { base_maintenance: baseMaintenance || "0" },
            flat_id: previewFlatId || null,
          }),
        );
      } catch {
        setPreview(null);
      } finally {
        setPreviewing(false);
      }
    }, 450);
    return () => clearTimeout(handle);
  }, [definition, baseMaintenance, previewFlatId, lineItems.length]);

  const errorPaths = React.useMemo(() => {
    const set = new Set<string>();
    for (const e of preview?.errors ?? []) {
      // "line_items[2].node.children[0]" -> the node path within that item
      const match = /^line_items\[(\d+)\]\.node\.?(.*)$/.exec(e.path);
      if (match && Number(match[1]) === selected) {
        set.add(match[2].replace(/children\[(\d+)\]/g, "$1").replace(/^\./, ""));
      }
    }
    return set;
  }, [preview, selected]);

  /* ---------------------------------------------------------------- */

  function updateItem(index: number, patch: Partial<LineItemSpec>) {
    setSaved(false);
    setLineItems((items) => items.map((it, i) => (i === index ? { ...it, ...patch } : it)));
  }

  function addItem() {
    setSaved(false);
    setLineItems((items) => [...items, emptyLineItem(items.length)]);
    setSelected(lineItems.length);
  }

  function removeItem(index: number) {
    setSaved(false);
    setLineItems((items) => items.filter((_, i) => i !== index));
    setSelected((s) => Math.max(0, Math.min(s, lineItems.length - 2)));
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const body = {
        formula: definition,
        parameters: { base_maintenance: baseMaintenance || "0" },
      };
      if (editing) {
        // Append a version — the existing one is never edited, so bills already
        // generated keep their formula.
        await api.post(`/bill-templates/${templateId}/versions`, {
          ...body,
          notes: versionNotes || "Updated in the Bill Builder",
          activate: true,
        });
        const refreshed = await api.get<BillTemplateDetail>(`/bill-templates/${templateId}`);
        setTemplate(refreshed);
        setVersionNotes("");
      } else {
        const created = await api.post<BillTemplateDetail>("/bill-templates", {
          name,
          description: description || null,
          frequency,
          ...body,
        });
        navigate(`/app/bill-builder/${created.id}`, { replace: true });
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save this template.");
    } finally {
      setSaving(false);
    }
  }

  const current = lineItems[selected];
  const invalid = (preview?.errors?.length ?? 0) > 0;
  const canSave = lineItems.length > 0 && !invalid && (editing || name.trim().length >= 2);

  if (loading) {
    return (
      <>
        <NFPageHeader title="Bill Builder" />
        <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)_320px]">
          <NFSkeleton className="h-96" />
          <NFSkeleton className="h-96" />
          <NFSkeleton className="h-96" />
        </div>
      </>
    );
  }

  return (
    <>
      <NFPageHeader
        title={editing ? name || "Bill Builder" : "New bill template"}
        description={
          editing
            ? "Saving creates a new version. Bills already issued keep the formula they were built with."
            : "Build the formula once; every billing run reuses it."
        }
        breadcrumb={
          <Link
            to="/app/bill-templates"
            className="inline-flex items-center gap-1.5 text-[13px] text-[var(--nf-text-muted)] hover:text-[var(--nf-primary)]"
          >
            <ArrowLeft className="size-3.5" aria-hidden /> Templates
          </Link>
        }
        actions={
          <div className="flex items-center gap-2">
            {editing && template && (
              <span className="hidden text-[13px] text-[var(--nf-text-muted)] sm:block">
                v{template.versions.find((v) => v.id === template.active_version_id)?.version_number ?? 1} active
              </span>
            )}
            <NFButton onClick={save} loading={saving} disabled={!canSave}>
              {saved ? (
                <>
                  <Check /> Saved
                </>
              ) : (
                <>
                  <Save /> {editing ? "Save as new version" : "Create template"}
                </>
              )}
            </NFButton>
          </div>
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

      <div className="grid gap-4 lg:grid-cols-[minmax(0,260px)_minmax(0,1fr)_minmax(0,340px)]">
        {/* ---------------------------------------------------------- */}
        {/* LEFT — settings and line items                              */}
        {/* ---------------------------------------------------------- */}
        <div className="space-y-4">
          {!editing && (
            <NFCard>
              <NFCardHeader title="Template" />
              <NFCardBody className="space-y-3">
                <NFField label="Name" htmlFor="t-name" required>
                  <NFInput
                    id="t-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Standard Maintenance"
                  />
                </NFField>
                <NFField label="Billed" htmlFor="t-freq">
                  <NFSelect
                    id="t-freq"
                    value={frequency}
                    onChange={(e) => setFrequency(e.target.value)}
                  >
                    {FREQUENCIES.map((f) => (
                      <option key={f.value} value={f.value}>
                        {f.label}
                      </option>
                    ))}
                  </NFSelect>
                </NFField>
                <NFField label="Description" htmlFor="t-desc">
                  <NFTextarea
                    id="t-desc"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    className="min-h-16"
                  />
                </NFField>
              </NFCardBody>
            </NFCard>
          )}

          <NFCard>
            <NFCardHeader
              title="Base amount"
              description="Read by the 'Base maintenance' field, unless a flat overrides it."
            />
            <NFCardBody>
              <NFField label="Amount" htmlFor="t-base">
                <NFInput
                  id="t-base"
                  type="number"
                  step="0.01"
                  value={baseMaintenance}
                  onChange={(e) => {
                    setBaseMaintenance(e.target.value);
                    setSaved(false);
                  }}
                />
              </NFField>
            </NFCardBody>
          </NFCard>

          <NFCard>
            <NFCardHeader
              title="Charges"
              description={`${lineItems.length} line item(s)`}
              action={
                <NFButton variant="ghost" size="icon-sm" aria-label="Add a charge" onClick={addItem}>
                  <Plus />
                </NFButton>
              }
            />
            <ul className="divide-y divide-[var(--nf-border)]">
              {lineItems.map((item, i) => (
                <li key={i}>
                  <button
                    onClick={() => setSelected(i)}
                    aria-current={i === selected}
                    className={cn(
                      "flex w-full items-start gap-2 px-3 py-2.5 text-left transition-colors",
                      i === selected
                        ? "bg-[var(--nf-primary-subtle)]"
                        : "hover:bg-[var(--nf-background)]",
                    )}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate text-[13px] font-medium text-[var(--nf-text)]">
                          {item.label}
                        </span>
                        {item.is_credit && (
                          <span className="shrink-0 rounded-full bg-[var(--nf-success-subtle)] px-1.5 text-[10px] font-semibold text-[var(--nf-success)]">
                            CREDIT
                          </span>
                        )}
                      </span>
                      <span className="mt-0.5 block truncate font-mono text-[11px] text-[var(--nf-text-muted)]">
                        {describe(item.node, fields)}
                      </span>
                    </span>
                    {preview?.line_items?.[i] && (
                      <span className="shrink-0 text-[12px] tabular-nums text-[var(--nf-text-muted)]">
                        {formatCurrency(preview.line_items[i].amount, true)}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
            {lineItems.length === 0 && (
              <NFCardBody className="text-center">
                <p className="text-[13px] text-[var(--nf-text-muted)]">No charges yet.</p>
                <NFButton size="sm" className="mt-3" onClick={addItem}>
                  <Plus /> Add a charge
                </NFButton>
              </NFCardBody>
            )}
          </NFCard>

          <NFButton variant="secondary" className="w-full" onClick={() => setPresetOpen(true)}>
            <Sparkles /> Start from a preset
          </NFButton>

          {editing && template && template.versions.length > 0 && (
            <NFCard>
              <NFCardHeader title="Versions" description="Newest first" />
              <ul className="divide-y divide-[var(--nf-border)] text-[13px]">
                {template.versions.slice(0, 6).map((v) => (
                  <li key={v.id} className="flex items-center gap-2 px-3 py-2">
                    <History className="size-3.5 shrink-0 text-[var(--nf-text-subtle)]" aria-hidden />
                    <span className="flex-1 text-[var(--nf-text)]">v{v.version_number}</span>
                    {v.bill_count > 0 && (
                      <span className="text-[11px] text-[var(--nf-text-muted)]">
                        {v.bill_count} bill(s)
                      </span>
                    )}
                    {v.is_active && <NFStatusBadge status="ACTIVE" tone="success" />}
                  </li>
                ))}
              </ul>
            </NFCard>
          )}
        </div>

        {/* ---------------------------------------------------------- */}
        {/* CENTRE — the formula tree                                    */}
        {/* ---------------------------------------------------------- */}
        <NFCard className="min-w-0">
          {current ? (
            <>
              <NFCardHeader
                title="Formula"
                description={`${countNodes(current.node)} part(s) in this charge`}
                action={
                  lineItems.length > 1 ? (
                    <NFButton
                      variant="ghost"
                      size="icon-sm"
                      aria-label="Delete this charge"
                      onClick={() => removeItem(selected)}
                    >
                      <Trash2 />
                    </NFButton>
                  ) : undefined
                }
              />
              <NFCardBody className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <NFField label="Shown on the bill as" htmlFor="li-label">
                    <NFInput
                      id="li-label"
                      value={current.label}
                      onChange={(e) => updateItem(selected, { label: e.target.value })}
                    />
                  </NFField>
                  <NFField label="Code" htmlFor="li-code" hint="Uppercase, used in exports">
                    <NFInput
                      id="li-code"
                      value={current.code}
                      className="font-mono uppercase"
                      onChange={(e) =>
                        updateItem(selected, {
                          code: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ""),
                        })
                      }
                    />
                  </NFField>
                  <NFField
                    label="Show a quantity from"
                    htmlFor="li-qty"
                    hint="Optional — prints as '18 KL × ₹26.67'"
                  >
                    <NFSelect
                      id="li-qty"
                      value={current.quantity_field ?? ""}
                      onChange={(e) => {
                        const key = e.target.value || null;
                        updateItem(selected, {
                          quantity_field: key,
                          unit: key ? (fields.find((f) => f.key === key)?.unit ?? null) : null,
                        });
                      }}
                    >
                      <option value="">No quantity</option>
                      {fields
                        .filter((f) => f.kind === "QUANTITY" || f.kind === "COUNT")
                        .map((f) => (
                          <option key={f.key} value={f.key}>
                            {f.label}
                          </option>
                        ))}
                    </NFSelect>
                  </NFField>
                  <NFField label="Kind" htmlFor="li-credit">
                    <NFSelect
                      id="li-credit"
                      value={current.is_credit ? "credit" : "charge"}
                      onChange={(e) =>
                        updateItem(selected, { is_credit: e.target.value === "credit" })
                      }
                    >
                      <option value="charge">Charge (adds to the bill)</option>
                      <option value="credit">Credit (subtracts)</option>
                    </NFSelect>
                  </NFField>
                </div>

                <div className="border-t border-[var(--nf-border)] pt-4">
                  <NodeEditor
                    root={current.node}
                    path=""
                    fields={fields}
                    errorPaths={errorPaths}
                    onChange={(next) => updateItem(selected, { node: next })}
                  />
                </div>
              </NFCardBody>
            </>
          ) : (
            <NFCardBody className="py-16 text-center">
              <FileText className="mx-auto size-8 text-[var(--nf-text-subtle)]" aria-hidden />
              <p className="mt-3 text-sm text-[var(--nf-text-muted)]">
                Add a charge to start building the formula.
              </p>
            </NFCardBody>
          )}
        </NFCard>

        {/* ---------------------------------------------------------- */}
        {/* RIGHT — live preview                                        */}
        {/* ---------------------------------------------------------- */}
        <div className="space-y-4 lg:sticky lg:top-24 lg:self-start">
          <NFCard>
            <NFCardHeader
              title="Live preview"
              description="Calculated by the real billing engine, on a real flat."
            />
            <NFCardBody className="space-y-4">
              <NFField label="Preview against" htmlFor="pv-flat">
                <NFSelect
                  id="pv-flat"
                  value={previewFlatId}
                  onChange={(e) => setPreviewFlatId(e.target.value)}
                >
                  {flats.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.flat_number} · {Number(f.area_sqft)} sqft
                      {f.flat_type ? ` · ${f.flat_type}` : ""}
                    </option>
                  ))}
                </NFSelect>
              </NFField>

              {invalid ? (
                <div className="space-y-2 rounded-[var(--nf-radius)] border border-[var(--nf-danger)]/30 bg-[var(--nf-danger-subtle)] p-3">
                  <p className="flex items-center gap-1.5 text-[13px] font-semibold text-[var(--nf-danger)]">
                    <AlertTriangle className="size-3.5" aria-hidden /> This formula is not valid
                  </p>
                  <ul className="space-y-1">
                    {preview?.errors.map((e: FormulaError, i) => (
                      <li key={i} className="text-[12px] leading-relaxed text-[var(--nf-text)]">
                        {e.message}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : preview?.flat ? (
                <div
                  className={cn(
                    "overflow-hidden rounded-[var(--nf-radius)] border border-[var(--nf-border)] transition-opacity",
                    previewing && "opacity-60",
                  )}
                >
                  <div className="border-b border-[var(--nf-border)] bg-[var(--nf-background)] px-3 py-2">
                    <p className="text-[12px] font-semibold text-[var(--nf-text)]">
                      Flat {preview.flat.flat_number}
                    </p>
                    {preview.period && (
                      <p className="text-[11px] text-[var(--nf-text-muted)]">
                        {preview.period.label}
                      </p>
                    )}
                  </div>
                  <table className="w-full text-[13px]">
                    <tbody>
                      {preview.line_items.map((li) => (
                        <tr key={li.code} className="border-b border-[var(--nf-border)]">
                          <td className="px-3 py-2 text-[var(--nf-text)]">
                            {li.label}
                            {li.quantity && li.unit && (
                              <span className="block text-[11px] text-[var(--nf-text-muted)]">
                                {Number(li.quantity)} {li.unit}
                                {li.rate ? ` × ₹${Number(li.rate)}` : ""}
                              </span>
                            )}
                          </td>
                          <td
                            className="px-3 py-2 text-right tabular-nums"
                            style={{ color: li.is_credit ? "var(--nf-success)" : undefined }}
                          >
                            {li.is_credit ? "−" : ""}
                            {formatCurrency(li.amount, true)}
                          </td>
                        </tr>
                      ))}
                      <tr className="bg-[var(--nf-primary-subtle)]">
                        <td className="px-3 py-2.5 font-semibold text-[var(--nf-text)]">Total</td>
                        <td className="px-3 py-2.5 text-right font-semibold tabular-nums text-[var(--nf-primary)]">
                          {formatCurrency(preview.total, true)}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-[13px] text-[var(--nf-text-muted)]">
                  {preview?.message ?? "Add a charge to see a preview."}
                </p>
              )}

              {preview?.inputs && Object.keys(preview.inputs).length > 0 && (
                <details className="text-[12px]">
                  <summary className="cursor-pointer text-[var(--nf-text-muted)]">
                    Inputs read ({Object.keys(preview.inputs).length})
                  </summary>
                  <dl className="mt-2 space-y-1">
                    {Object.entries(preview.inputs).map(([k, v]) => (
                      <div key={k} className="flex justify-between gap-2">
                        <dt className="truncate font-mono text-[var(--nf-text-subtle)]">{k}</dt>
                        <dd className="tabular-nums text-[var(--nf-text)]">{v}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              )}
            </NFCardBody>
          </NFCard>

          {editing && (
            <NFCard>
              <NFCardHeader title="Version note" description="What changed, and why." />
              <NFCardBody>
                <NFTextarea
                  value={versionNotes}
                  onChange={(e) => setVersionNotes(e.target.value)}
                  placeholder="Water rate revised from April"
                  className="min-h-16 text-[13px]"
                  aria-label="Version note"
                />
              </NFCardBody>
            </NFCard>
          )}
        </div>
      </div>

      <NFDialog
        open={presetOpen}
        onOpenChange={setPresetOpen}
        title="Start from a preset"
        description="Replaces the current charges. You can edit everything afterwards."
      >
        <ul className="space-y-2">
          {PRESETS.map((preset) => (
            <li key={preset.name}>
              <button
                onClick={() => {
                  setLineItems(preset.build());
                  setSelected(0);
                  setPresetOpen(false);
                  setSaved(false);
                }}
                className="w-full rounded-[var(--nf-radius)] border border-[var(--nf-border)] p-3 text-left transition-colors hover:border-[var(--nf-primary)] hover:bg-[var(--nf-primary-subtle)]"
              >
                <p className="text-[13px] font-medium text-[var(--nf-text)]">{preset.name}</p>
                <p className="mt-0.5 text-[12px] text-[var(--nf-text-muted)]">
                  {preset.description}
                </p>
              </button>
            </li>
          ))}
        </ul>
      </NFDialog>
    </>
  );
}
