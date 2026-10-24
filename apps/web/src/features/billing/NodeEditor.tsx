/**
 * The formula node editor.
 *
 * A keyboard-operable tree, not a drag-only canvas. Every action — change a
 * node's kind, pick a field, add or remove an operand, edit a slab band — is a
 * focusable control, so the Bill Builder is usable without a pointer. The
 * accessibility requirement in the spec is met by the primary interface rather
 * than by a bolted-on alternative.
 */

import { ChevronDown, GripVertical, Plus, Trash2 } from "lucide-react";
import * as React from "react";

import { NFButton, NFInput, NFSelect } from "@/components/nestflow/primitives";
import {
  OPERATORS,
  OPERATOR_BY_TYPE,
  addChild,
  describe,
  fieldNode,
  getNode,
  operatorNode,
  removeChild,
  setNode,
  valueNode,
} from "@/features/billing/formulaModel";
import type { FieldSpec, FormulaNode } from "@/types";
import { cn } from "@/utils/cn";

interface Props {
  root: FormulaNode;
  path: string;
  fields: FieldSpec[];
  onChange: (next: FormulaNode) => void;
  /** Depth drives the indent guide, nothing else. */
  depth?: number;
  /** Set for an IF's condition slot, so only boolean kinds are offered. */
  expectsBoolean?: boolean;
  onRemove?: () => void;
  errorPaths?: Set<string>;
}

const KIND_OPTIONS = [
  { value: "VALUE", label: "A number" },
  { value: "FIELD", label: "A field" },
  { value: "TEXT", label: "Some text" },
  { value: "BOOL", label: "Yes / no" },
];

export function NodeEditor({
  root,
  path,
  fields,
  onChange,
  depth = 0,
  expectsBoolean = false,
  onRemove,
  errorPaths,
}: Props) {
  const node = getNode(root, path);
  if (!node) return null;

  const spec = OPERATOR_BY_TYPE.get(node.type);
  const isLeaf = ["VALUE", "FIELD", "TEXT", "BOOL"].includes(node.type);
  const hasError = errorPaths?.has(path);

  function replace(next: FormulaNode) {
    onChange(setNode(root, path, next));
  }

  function changeKind(kind: string) {
    if (kind === "VALUE") return replace(valueNode(node!.value ?? "0"));
    if (kind === "FIELD") return replace(fieldNode(fields[0]?.key ?? "flat_area"));
    if (kind === "TEXT") return replace({ type: "TEXT", text: node!.text ?? "" });
    if (kind === "BOOL") return replace({ type: "BOOL", bool_value: node!.bool_value ?? true });
    replace(operatorNode(kind));
  }

  const availableOperators = expectsBoolean
    ? OPERATORS.filter((o) => o.group === "Comparisons" || ["AND", "OR", "NOT"].includes(o.type))
    : OPERATORS;

  const availableKinds = expectsBoolean
    ? KIND_OPTIONS.filter((k) => k.value === "BOOL" || k.value === "FIELD")
    : KIND_OPTIONS;

  return (
    <div
      className={cn(
        "rounded-[var(--nf-radius-sm)] border bg-[var(--nf-surface)]",
        hasError ? "border-[var(--nf-danger)]" : "border-[var(--nf-border)]",
        depth > 0 && "mt-2",
      )}
    >
      {/* Header: what kind of node this is */}
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--nf-border)] p-2">
        <GripVertical className="size-3.5 shrink-0 text-[var(--nf-text-subtle)]" aria-hidden />

        <NFSelect
          value={node.type}
          onChange={(e) => changeKind(e.target.value)}
          aria-label="Node kind"
          className="h-8 w-auto min-w-40 text-[13px]"
        >
          <optgroup label="Value">
            {availableKinds.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </optgroup>
          {["Maths", "Conditions", "Comparisons"].map((group) => {
            const ops = availableOperators.filter((o) => o.group === group);
            if (!ops.length) return null;
            return (
              <optgroup key={group} label={group}>
                {ops.map((o) => (
                  <option key={o.type} value={o.type}>
                    {o.label}
                  </option>
                ))}
              </optgroup>
            );
          })}
        </NFSelect>

        {/* Leaf value editors */}
        {node.type === "VALUE" && (
          <NFInput
            type="number"
            step="0.01"
            value={node.value ?? "0"}
            onChange={(e) => replace({ ...node, value: e.target.value || "0" })}
            aria-label="Value"
            className="h-8 w-32 text-[13px]"
          />
        )}

        {node.type === "TEXT" && (
          <NFInput
            value={node.text ?? ""}
            onChange={(e) => replace({ ...node, text: e.target.value })}
            aria-label="Text"
            placeholder="3BHK"
            className="h-8 w-36 text-[13px]"
          />
        )}

        {node.type === "BOOL" && (
          <NFSelect
            value={node.bool_value ? "true" : "false"}
            onChange={(e) => replace({ ...node, bool_value: e.target.value === "true" })}
            aria-label="Yes or no"
            className="h-8 w-24 text-[13px]"
          >
            <option value="true">Yes</option>
            <option value="false">No</option>
          </NFSelect>
        )}

        {node.type === "FIELD" && (
          <NFSelect
            value={node.field ?? ""}
            onChange={(e) => replace({ ...node, field: e.target.value })}
            aria-label="Field"
            className="h-8 w-auto min-w-52 text-[13px]"
          >
            {Object.entries(
              fields.reduce<Record<string, FieldSpec[]>>((acc, f) => {
                if (expectsBoolean && f.kind !== "BOOLEAN") return acc;
                (acc[f.group] ??= []).push(f);
                return acc;
              }, {}),
            ).map(([group, groupFields]) => (
              <optgroup key={group} label={group}>
                {groupFields.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.label}
                    {f.unit ? ` (${f.unit})` : ""}
                  </option>
                ))}
              </optgroup>
            ))}
          </NFSelect>
        )}

        {node.type === "ROUND" && (
          <NFSelect
            value={String(node.decimal_places ?? 2)}
            onChange={(e) => replace({ ...node, decimal_places: Number(e.target.value) })}
            aria-label="Decimal places"
            className="h-8 w-32 text-[13px]"
          >
            {[0, 1, 2, 3].map((d) => (
              <option key={d} value={d}>
                {d} decimal{d === 1 ? "" : "s"}
              </option>
            ))}
          </NFSelect>
        )}

        {node.type === "SLAB" && (
          <NFSelect
            value={node.mode ?? "PROGRESSIVE"}
            onChange={(e) =>
              replace({ ...node, mode: e.target.value as "PROGRESSIVE" | "FLAT" })
            }
            aria-label="Slab mode"
            className="h-8 w-auto text-[13px]"
          >
            <option value="PROGRESSIVE">Progressive (each band separately)</option>
            <option value="FLAT">Flat (whole amount at one rate)</option>
          </NFSelect>
        )}

        <span className="ml-auto flex items-center gap-1">
          {!isLeaf && spec?.arity === "n" && (
            <NFButton
              variant="ghost"
              size="icon-sm"
              aria-label="Add another value"
              title="Add another value"
              onClick={() => onChange(addChild(root, path))}
            >
              <Plus />
            </NFButton>
          )}
          {onRemove && (
            <NFButton variant="ghost" size="icon-sm" aria-label="Remove this part" onClick={onRemove}>
              <Trash2 />
            </NFButton>
          )}
        </span>
      </div>

      {/* Children */}
      {!isLeaf && (
        <div
          className={cn(
            "space-y-0 p-2",
            depth < 4 && "border-l-2 border-[var(--nf-primary)]/20 ml-2",
          )}
        >
          {node.type === "SLAB" ? (
            <SlabEditor
              node={node}
              fields={fields}
              root={root}
              path={path}
              onChange={onChange}
              depth={depth}
              errorPaths={errorPaths}
            />
          ) : (
            (node.children ?? []).map((_, index) => (
              <div key={index}>
                {node.type === "IF" && (
                  <p className="mb-1 mt-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--nf-text-muted)]">
                    {["When", "Then charge", "Otherwise charge"][index]}
                  </p>
                )}
                {node.type === "PERCENTAGE" && (
                  <p className="mb-1 mt-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--nf-text-muted)]">
                    {["Of this amount", "This percent"][index]}
                  </p>
                )}
                <NodeEditor
                  root={root}
                  path={path ? `${path}.${index}` : String(index)}
                  fields={fields}
                  onChange={onChange}
                  depth={depth + 1}
                  expectsBoolean={
                    (node.type === "IF" && index === 0) ||
                    node.type === "AND" ||
                    node.type === "OR" ||
                    node.type === "NOT"
                  }
                  errorPaths={errorPaths}
                  onRemove={
                    spec?.arity === "n" && (node.children?.length ?? 0) > 1
                      ? () => onChange(removeChild(root, path, index))
                      : undefined
                  }
                />
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function SlabEditor({
  node,
  fields,
  root,
  path,
  onChange,
  depth,
  errorPaths,
}: {
  node: FormulaNode;
  fields: FieldSpec[];
  root: FormulaNode;
  path: string;
  onChange: (n: FormulaNode) => void;
  depth: number;
  errorPaths?: Set<string>;
}) {
  const slabs = node.slabs ?? [];

  function updateSlabs(next: typeof slabs) {
    onChange(setNode(root, path, { ...node, slabs: next }));
  }

  return (
    <>
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--nf-text-muted)]">
        Measured quantity
      </p>
      <NodeEditor
        root={root}
        path={path ? `${path}.input` : "input"}
        fields={fields}
        onChange={onChange}
        depth={depth + 1}
        errorPaths={errorPaths}
      />

      <p className="mb-1 mt-3 text-[11px] font-semibold uppercase tracking-wide text-[var(--nf-text-muted)]">
        Bands
      </p>
      <div className="space-y-1.5">
        {slabs.map((band, i) => {
          const isLast = i === slabs.length - 1;
          return (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <span className="w-14 shrink-0 text-[12px] text-[var(--nf-text-muted)]">
                {i === 0 ? "up to" : "then to"}
              </span>
              {isLast ? (
                <span className="flex h-8 w-28 items-center rounded-[var(--nf-radius-sm)] border border-dashed border-[var(--nf-border)] px-2 text-[12px] text-[var(--nf-text-subtle)]">
                  and above
                </span>
              ) : (
                <NFInput
                  type="number"
                  step="0.001"
                  value={band.up_to ?? ""}
                  onChange={(e) =>
                    updateSlabs(
                      slabs.map((b, j) => (j === i ? { ...b, up_to: e.target.value } : b)),
                    )
                  }
                  aria-label={`Band ${i + 1} upper bound`}
                  className="h-8 w-28 text-[13px]"
                />
              )}
              <span className="text-[12px] text-[var(--nf-text-muted)]">at ₹</span>
              <NFInput
                type="number"
                step="0.01"
                value={band.rate}
                onChange={(e) =>
                  updateSlabs(slabs.map((b, j) => (j === i ? { ...b, rate: e.target.value } : b)))
                }
                aria-label={`Band ${i + 1} rate`}
                className="h-8 w-24 text-[13px]"
              />
              <span className="text-[12px] text-[var(--nf-text-muted)]">per unit</span>
              {slabs.length > 1 && (
                <NFButton
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Remove band ${i + 1}`}
                  onClick={() => updateSlabs(slabs.filter((_, j) => j !== i))}
                >
                  <Trash2 />
                </NFButton>
              )}
            </div>
          );
        })}
        <NFButton
          variant="ghost"
          size="sm"
          onClick={() =>
            // The open-ended band must stay last, so a new one is inserted
            // before it — otherwise consumption above the top band is free.
            updateSlabs([
              ...slabs.slice(0, -1),
              { up_to: "50", rate: "40" },
              slabs[slabs.length - 1],
            ])
          }
        >
          <Plus /> Add band
        </NFButton>
      </div>
    </>
  );
}

/* -------------------------------------------------------------------------- */

export function NodeSummary({
  node,
  fields,
  className,
}: {
  node: FormulaNode;
  fields: FieldSpec[];
  className?: string;
}) {
  return (
    <code className={cn("text-[12px] text-[var(--nf-text-muted)]", className)}>
      {describe(node, fields)}
    </code>
  );
}

export function CollapsibleSection({
  title,
  subtitle,
  defaultOpen = false,
  children,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <div className="rounded-[var(--nf-radius)] border border-[var(--nf-border)]">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left"
      >
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-[var(--nf-text-subtle)] transition-transform",
            !open && "-rotate-90",
          )}
          aria-hidden
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium text-[var(--nf-text)]">
            {title}
          </span>
          {subtitle && <span className="block truncate text-[11px]">{subtitle}</span>}
        </span>
      </button>
      {open && <div className="border-t border-[var(--nf-border)] p-3">{children}</div>}
    </div>
  );
}
