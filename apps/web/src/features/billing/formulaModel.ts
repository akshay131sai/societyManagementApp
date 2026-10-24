/**
 * Formula tree helpers for the Bill Builder.
 *
 * The editor manipulates the same AST the backend stores and evaluates — there
 * is no separate editor model to drift out of sync. These are pure functions
 * over that tree.
 */

import type { FieldSpec, FormulaNode, LineItemSpec } from "@/types";

export type NodeKind = FormulaNode["type"];

/** Every node type the palette offers, grouped for the left panel. */
export const OPERATORS: {
  type: string;
  label: string;
  symbol: string;
  arity: "n" | 2 | 1 | 3;
  group: string;
  hint: string;
}[] = [
  { type: "ADD", label: "Add", symbol: "+", arity: "n", group: "Maths", hint: "a + b" },
  { type: "SUBTRACT", label: "Subtract", symbol: "−", arity: "n", group: "Maths", hint: "a − b" },
  { type: "MULTIPLY", label: "Multiply", symbol: "×", arity: "n", group: "Maths", hint: "a × b" },
  { type: "DIVIDE", label: "Divide", symbol: "÷", arity: "n", group: "Maths", hint: "a ÷ b" },
  { type: "MIN", label: "Smallest of", symbol: "min", arity: "n", group: "Maths", hint: "the lower value" },
  { type: "MAX", label: "Largest of", symbol: "max", arity: "n", group: "Maths", hint: "the higher value" },
  { type: "PERCENTAGE", label: "Percentage of", symbol: "%", arity: 2, group: "Maths", hint: "12% of the base" },
  { type: "ROUND", label: "Round", symbol: "≈", arity: 1, group: "Maths", hint: "to 2 decimals" },
  { type: "SLAB", label: "Slab rate", symbol: "▤", arity: 1, group: "Maths", hint: "progressive tariff bands" },

  { type: "IF", label: "If / otherwise", symbol: "?", arity: 3, group: "Conditions", hint: "charge differently when…" },
  { type: "AND", label: "And", symbol: "&", arity: "n", group: "Conditions", hint: "both must hold" },
  { type: "OR", label: "Or", symbol: "|", arity: "n", group: "Conditions", hint: "either may hold" },
  { type: "NOT", label: "Not", symbol: "!", arity: 1, group: "Conditions", hint: "the opposite" },

  { type: "GT", label: "is greater than", symbol: ">", arity: 2, group: "Comparisons", hint: "" },
  { type: "GTE", label: "is at least", symbol: "≥", arity: 2, group: "Comparisons", hint: "" },
  { type: "LT", label: "is less than", symbol: "<", arity: 2, group: "Comparisons", hint: "" },
  { type: "LTE", label: "is at most", symbol: "≤", arity: 2, group: "Comparisons", hint: "" },
  { type: "EQ", label: "is", symbol: "=", arity: 2, group: "Comparisons", hint: "" },
  { type: "NEQ", label: "is not", symbol: "≠", arity: 2, group: "Comparisons", hint: "" },
];

export const OPERATOR_BY_TYPE = new Map(OPERATORS.map((o) => [o.type, o]));

const BOOLEAN_TYPES = new Set([
  "GT", "GTE", "LT", "LTE", "EQ", "NEQ", "AND", "OR", "NOT", "BOOL",
]);

export function producesBoolean(node: FormulaNode | undefined, fields: FieldSpec[]): boolean {
  if (!node) return false;
  if (BOOLEAN_TYPES.has(node.type)) return true;
  if (node.type === "FIELD") {
    return fields.find((f) => f.key === node.field)?.kind === "BOOLEAN";
  }
  return false;
}

/* -------------------------------------------------------------------------- */
/* Construction                                                               */
/* -------------------------------------------------------------------------- */

export function valueNode(value = "0"): FormulaNode {
  return { type: "VALUE", value };
}

export function fieldNode(field: string): FormulaNode {
  return { type: "FIELD", field };
}

/** A new operator with placeholder children, so the tree is always complete. */
export function operatorNode(type: string): FormulaNode {
  const spec = OPERATOR_BY_TYPE.get(type);
  if (!spec) return valueNode();

  switch (type) {
    case "SLAB":
      return {
        type: "SLAB",
        mode: "PROGRESSIVE",
        input: valueNode("0"),
        slabs: [
          { up_to: "10", rate: "20" },
          { up_to: null, rate: "35" },
        ],
      };
    case "ROUND":
      return { type: "ROUND", children: [valueNode()], decimal_places: 2 };
    case "IF":
      return {
        type: "IF",
        children: [
          { type: "GT", children: [valueNode("0"), valueNode("0")] },
          valueNode("0"),
          valueNode("0"),
        ],
      };
    case "NOT":
      return { type: "NOT", children: [{ type: "BOOL", bool_value: true }] };
    case "AND":
    case "OR":
      return {
        type,
        children: [
          { type: "GT", children: [valueNode("0"), valueNode("0")] },
          { type: "GT", children: [valueNode("0"), valueNode("0")] },
        ],
      };
    default: {
      const count = spec.arity === "n" ? 2 : spec.arity;
      return { type, children: Array.from({ length: count }, () => valueNode()) };
    }
  }
}

export function emptyLineItem(index: number): LineItemSpec {
  return {
    code: `ITEM_${index + 1}`,
    label: `Charge ${index + 1}`,
    node: valueNode("0"),
    is_credit: false,
    sort_order: index + 1,
  };
}

/* -------------------------------------------------------------------------- */
/* Traversal — path is a dotted string like "children.0.children.1"           */
/* -------------------------------------------------------------------------- */

export function getNode(root: FormulaNode, path: string): FormulaNode | undefined {
  if (!path) return root;
  let current: FormulaNode | undefined = root;
  for (const step of path.split(".")) {
    if (!current) return undefined;
    if (step === "input") {
      current = current.input;
    } else if (/^\d+$/.test(step)) {
      current = current.children?.[Number(step)];
    } else {
      current = (current as unknown as Record<string, FormulaNode>)[step];
    }
  }
  return current;
}

/** Replace the node at `path`, returning a new tree (never mutating). */
export function setNode(root: FormulaNode, path: string, next: FormulaNode): FormulaNode {
  if (!path) return next;

  const steps = path.split(".");
  const clone = structuredClone(root);
  let cursor: FormulaNode = clone;

  for (let i = 0; i < steps.length - 1; i += 1) {
    const step = steps[i];
    if (step === "input") {
      cursor = cursor.input as FormulaNode;
    } else if (/^\d+$/.test(step)) {
      cursor = (cursor.children as FormulaNode[])[Number(step)];
    }
  }

  const last = steps[steps.length - 1];
  if (last === "input") cursor.input = next;
  else if (/^\d+$/.test(last)) (cursor.children as FormulaNode[])[Number(last)] = next;
  return clone;
}

export function addChild(root: FormulaNode, path: string): FormulaNode {
  const target = getNode(root, path);
  if (!target?.children) return root;
  const next = structuredClone(target);
  next.children = [...(next.children ?? []), valueNode()];
  return setNode(root, path, next);
}

export function removeChild(root: FormulaNode, path: string, index: number): FormulaNode {
  const target = getNode(root, path);
  if (!target?.children || target.children.length <= 1) return root;
  const next = structuredClone(target);
  next.children = next.children!.filter((_, i) => i !== index);
  return setNode(root, path, next);
}

export function countNodes(node: FormulaNode | undefined): number {
  if (!node) return 0;
  let total = 1;
  for (const child of node.children ?? []) total += countNodes(child);
  if (node.input) total += countNodes(node.input);
  return total;
}

/* -------------------------------------------------------------------------- */
/* Rendering                                                                  */
/* -------------------------------------------------------------------------- */

/** A one-line reading of a subtree, for collapsed nodes and summaries. */
export function describe(node: FormulaNode | undefined, fields: FieldSpec[]): string {
  if (!node) return "—";

  switch (node.type) {
    case "VALUE":
      return node.value ?? "0";
    case "TEXT":
      return `"${node.text ?? ""}"`;
    case "BOOL":
      return node.bool_value ? "yes" : "no";
    case "FIELD":
      return fields.find((f) => f.key === node.field)?.label ?? node.field ?? "?";
    case "SLAB":
      return `slab(${describe(node.input, fields)}, ${node.slabs?.length ?? 0} bands)`;
    case "ROUND":
      return `round(${describe(node.children?.[0], fields)})`;
    case "PERCENTAGE":
      return `${describe(node.children?.[1], fields)}% of ${describe(node.children?.[0], fields)}`;
    case "IF":
      return `if ${describe(node.children?.[0], fields)} then ${describe(
        node.children?.[1],
        fields,
      )} else ${describe(node.children?.[2], fields)}`;
    case "NOT":
      return `not ${describe(node.children?.[0], fields)}`;
    default: {
      const spec = OPERATOR_BY_TYPE.get(node.type);
      const parts = (node.children ?? []).map((c) => describe(c, fields));
      if (!spec) return parts.join(" ");
      if (spec.group === "Comparisons" || spec.type === "AND" || spec.type === "OR") {
        return parts.join(` ${spec.label} `);
      }
      return parts.join(` ${spec.symbol} `);
    }
  }
}

/** Ready-made formulas, so a new society is not staring at a blank canvas. */
export const PRESETS: { name: string; description: string; build: () => LineItemSpec[] }[] = [
  {
    name: "Flat rate",
    description: "One fixed amount for every flat.",
    build: () => [
      {
        code: "BASE",
        label: "Maintenance",
        node: fieldNode("base_maintenance"),
        sort_order: 1,
      },
    ],
  },
  {
    name: "Per square foot",
    description: "Charged on the flat's built-up area.",
    build: () => [
      {
        code: "AREA",
        label: "Area charges",
        quantity_field: "flat_area",
        unit: "sqft",
        node: { type: "MULTIPLY", children: [fieldNode("flat_area"), valueNode("2.50")] },
        sort_order: 1,
      },
    ],
  },
  {
    name: "Base + area + water",
    description: "The most common Indian society structure, with a water slab.",
    build: () => [
      { code: "BASE", label: "Base maintenance", node: fieldNode("base_maintenance"), sort_order: 1 },
      {
        code: "AREA",
        label: "Area charges",
        quantity_field: "flat_area",
        unit: "sqft",
        node: { type: "MULTIPLY", children: [fieldNode("flat_area"), valueNode("2.00")] },
        sort_order: 2,
      },
      {
        code: "WATER",
        label: "Water",
        quantity_field: "water_consumption",
        unit: "KL",
        node: {
          type: "SLAB",
          mode: "PROGRESSIVE",
          input: fieldNode("water_consumption"),
          slabs: [
            { up_to: "10", rate: "20" },
            { up_to: "25", rate: "35" },
            { up_to: null, rate: "50" },
          ],
        },
        sort_order: 3,
      },
      {
        code: "PARKING",
        label: "Parking",
        node: fieldNode("parking_charge_total"),
        sort_order: 4,
      },
    ],
  },
  {
    name: "With a vacancy rebate",
    description: "Base and area, with 10% off while the flat is empty.",
    build: () => [
      { code: "BASE", label: "Base maintenance", node: fieldNode("base_maintenance"), sort_order: 1 },
      {
        code: "AREA",
        label: "Area charges",
        quantity_field: "flat_area",
        unit: "sqft",
        node: { type: "MULTIPLY", children: [fieldNode("flat_area"), valueNode("2.00")] },
        sort_order: 2,
      },
      {
        code: "REBATE",
        label: "Vacancy rebate",
        is_credit: true,
        sort_order: 3,
        node: {
          type: "IF",
          children: [
            fieldNode("is_vacant"),
            { type: "PERCENTAGE", children: [fieldNode("base_maintenance"), valueNode("10")] },
            valueNode("0"),
          ],
        },
      },
    ],
  },
];
