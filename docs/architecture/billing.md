# Billing Architecture

> The frontend Bill Builder is an **editor**. The backend Formula Engine is the
> **authority**. Money is only ever computed server-side.

## 1. Object model

```
BillTemplate                 "Standard Maintenance"  (a named, reusable config)
   |
   +-- BillTemplateVersion   v1, v2, v3 ...  APPEND-ONLY, formula frozen per version
   |        |
   |        +-- formula JSONB (the AST)
   |        +-- line_item_spec JSONB (how the AST decomposes into presented rows)
   |
   +-- BillTemplateAssignment  which flats this template applies to
                               (ALL | BUILDING | BLOCK | FLAT_TYPE | EXPLICIT list)

BillingRun                   one execution: template version x period x flat set
   |
   +-- MaintenanceBill        one per flat.  IMMUTABLE once published.
            |
            +-- formula_snapshot JSONB   the exact AST used
            +-- input_snapshot   JSONB   every input value read
            +-- BillLineItem[]           the presented breakdown
```

### Why versions are append-only

A rate change must not rewrite history. Raising the per-sqft rate from ₹2.00 to
₹2.50 creates **v2**; every bill already generated still points at **v1** and
still carries v1's frozen `formula_snapshot`. Editing a published version is
structurally impossible — there is no `UPDATE` path on
`bill_template_versions.formula` in any repository, and a database trigger
rejects the write.

## 2. Formula AST

A formula is JSON, never a string, and never `eval()`-ed.

```json
{
  "type": "ADD",
  "children": [
    { "type": "FIELD", "field": "base_maintenance" },
    {
      "type": "MULTIPLY",
      "children": [
        { "type": "FIELD", "field": "flat_area" },
        { "type": "VALUE", "value": 2.5 }
      ]
    }
  ]
}
```

### Node types

| Type | Arity | Semantics |
|---|---|---|
| `VALUE` | leaf | Literal `Decimal`. |
| `FIELD` | leaf | Named input from the resolved context. |
| `ADD` `SUBTRACT` `MULTIPLY` `DIVIDE` | 2..n | Left-to-right fold. |
| `MIN` `MAX` | 1..n | |
| `PERCENTAGE` | 2 | `children[0] * children[1] / 100`. |
| `IF` | 3 | `cond, then, else`. Only the taken branch is evaluated. |
| `AND` `OR` `NOT` | 2..n / 1 | Boolean. |
| `GT` `GTE` `LT` `LTE` `EQ` `NEQ` | 2 | Comparison; produce booleans for `IF`. |
| `SLAB` | 1 + table | Progressive slab rate over a field (see below). |
| `ROUND` | 1 (+ dp) | Explicit rounding, `ROUND_HALF_UP`. |

### Slabs

Indian utility billing is slab-based, so it is a first-class node rather than a
tower of nested `IF`s:

```json
{
  "type": "SLAB",
  "input": { "type": "FIELD", "field": "water_consumption" },
  "mode": "PROGRESSIVE",
  "slabs": [
    { "up_to": 10,   "rate": 20 },
    { "up_to": 25,   "rate": 35 },
    { "up_to": null, "rate": 50 }
  ]
}
```

`PROGRESSIVE` charges each band separately (18 KL -> `10*20 + 8*35`).
`FLAT` charges the whole quantity at the matched band's rate.

### Available fields

| Field | Source | Type |
|---|---|---|
| `flat_area` | `flats.area_sqft` | Decimal |
| `flat_type` | `flats.flat_type` | str |
| `floor_number` | `floors.number` | int |
| `base_maintenance` | society setting / template param | Decimal |
| `water_consumption` | `water_readings` for the period | Decimal |
| `water_previous`, `water_current` | readings | Decimal |
| `electricity_units` | `electricity_readings` for the period | Decimal |
| `parking_slot_count` | count of allotted slots | int |
| `parking_charge_total` | sum of slot monthly charges | Decimal |
| `vehicle_count`, `two_wheeler_count`, `four_wheeler_count` | vehicles | int |
| `pet_count`, `pet_fee_total` | pets | int / Decimal |
| `occupancy_status` | `flats.occupancy_status` | str |
| `outstanding_balance` | prior unpaid bills | Decimal |
| `days_overdue` | derived | int |
| `period_months` | 1 / 3 / 6 / 12 | int |
| `custom.<key>` | `bill_template_versions.parameters` | Decimal |

The field registry lives in `app/engines/formula/fields.py`. Both the validator
and the frontend palette are generated from it, so an unknown field is
impossible to save.

## 3. Validation

`FormulaValidator.validate(ast) -> list[FormulaError]` runs at **save** time and
again at **evaluate** time. Checks:

| Check | Error code |
|---|---|
| Unknown node type | `UNKNOWN_NODE_TYPE` |
| Wrong arity | `INVALID_ARITY` |
| Unknown field name | `UNKNOWN_FIELD` |
| Non-numeric literal / NaN / Infinity | `INVALID_VALUE` |
| Depth > 32 | `EXCESSIVE_NESTING` |
| Node count > 500 | `FORMULA_TOO_LARGE` |
| Structural cycle (shared node reference) | `CIRCULAR_REFERENCE` |
| Literal divisor of zero | `DIVISION_BY_ZERO` |
| Boolean used where number expected (and vice versa) | `TYPE_MISMATCH` |
| Slabs not ascending / duplicate bound / only-`null` bound not last | `INVALID_SLAB_TABLE` |

Runtime division by zero (a *field* evaluating to 0) raises
`DIVISION_BY_ZERO` for that flat, marks the bill `FAILED` in the run, and lets
the rest of the run continue. One bad flat never aborts a 400-flat run.

## 4. Numeric policy

- Everything is `decimal.Decimal`. `float` never touches a money path.
- Working precision 28 significant digits.
- Intermediate results are **not** rounded.
- Each line item rounds to 2 dp with `ROUND_HALF_UP` at presentation.
- The bill total is the **sum of the rounded line items**, so the printed rows
  always add up to the printed total. (Rounding the unrounded total instead
  would produce bills that appear off by a paisa.)
- Storage: `NUMERIC(14,2)` for money, `NUMERIC(14,3)` for utility quantities.

## 5. Evaluation

```python
class FormulaEngine:
    def evaluate(self, ast: FormulaNode, ctx: EvaluationContext) -> EvaluationResult
```

`EvaluationResult` carries the value **and a trace**: every node with its inputs
and output. The trace powers "How was this calculated?" on the resident's bill
detail screen and is stored in the bill snapshot, so an explanation is
reproducible years later without re-running anything.

Pure function. No session, no I/O, no clock. Fully unit-testable.

## 6. Billing engine

```
BillingService.create_run(template_id, period, dry_run)
   |
   1  resolve active template + its ACTIVE version         -> frozen
   2  resolve applicable flats from assignment rules
   3  bulk-load period inputs (one query per input family, not per flat)
        water, electricity, parking, vehicles, pets, outstanding
   4  for each flat:
        build EvaluationContext
        FormulaEngine.evaluate(...)  -> value + trace
        decompose into BillLineItem[] via line_item_spec
        apply penalty / discount rules
        write MaintenanceBill(status=DRAFT) with formula_snapshot + input_snapshot
   5  run status -> COMPLETED (or COMPLETED_WITH_ERRORS)
   |
   v
Society Admin reviews DRAFT bills (may edit or void individual drafts)
   |
   v
BillingService.publish_run(run_id)
   |
   6  DRAFT -> PUBLISHED, set issued_at, due_date
   7  bills become IMMUTABLE (trigger-enforced)
   8  NotificationService.notify_bill_published(...) per flat
```

Step 3 is the performance-critical part: inputs are loaded **per run**, not per
flat. A 500-flat run issues ~8 queries, not ~4000.

`dry_run=True` computes and returns without persisting — this backs the Bill
Builder's live preview against a sample flat.

## 7. Immutability enforcement

Three layers, because this is a financial record:

1. **Repository** — no update method exists for a published bill.
2. **Service** — `publish_run` is the only transition into `PUBLISHED`; the
   reverse transition does not exist. A wrong bill is corrected with a **credit
   note**, never an edit.
3. **Database** — a `BEFORE UPDATE` trigger on `maintenance_bills` raises unless
   the row is `DRAFT`, or the change is confined to the payment-tracking columns
   (`amount_paid`, `payment_status`, `paid_at`).

`bill_line_items` and the two snapshot columns are covered by the same trigger.

## 8. Billing periods

| Frequency | `period_key` | Label |
|---|---|---|
| `MONTHLY` | `2026-08` | August 2026 |
| `QUARTERLY` | `2026-Q3` | Q3 2026 (Jul–Sep) |
| `HALF_YEARLY` | `2026-H1` | Apr–Sep 2026 |
| `YEARLY` | `FY2026-27` | FY 2026–27 |
| `ONE_TIME` | `OT-<uuid8>` | ad-hoc |

Half-yearly and yearly follow the **Indian financial year** (April–March):
`H1 = Apr–Sep`, `H2 = Oct–Mar`, `FY2026-27 = Apr 2026 – Mar 2027`. Quarters are
calendar quarters, which is what societies actually use for maintenance.

`period_key` is unique per `(flat_id, template_id)` — a partial unique index
prevents double-billing a flat for the same period.

## 9. Scheduling

APScheduler in-process (`AsyncIOScheduler`), one job per society-template with a
billing schedule. No Celery, no Redis.

Guards:
- Jobs are idempotent — a run for an existing `(template, period)` is skipped.
- A `billing_runs` advisory lock prevents concurrent runs for one template.
- Generated bills are always `DRAFT`. **Nothing is published automatically.**
  A human publishes.

If a second API instance ever appears, scheduling moves behind a PostgreSQL
advisory lock so exactly one instance owns the scheduler. That is a ~20-line
change and is noted here so it is not forgotten.

## 10. Test plan

| Area | Cases |
|---|---|
| Node semantics | Each node type, arity bounds, operator precedence via nesting |
| Slabs | Progressive and flat, boundary values, open-ended last band |
| Validation | Every error code in section 3 |
| Numerics | Decimal precision, half-up rounding, line items sum to total |
| Periods | All five frequencies, Indian FY boundaries, leap year |
| Engine | Penalty, discount, water, electricity, parking, pet fee, outstanding |
| Failure isolation | One flat divides by zero -> that bill FAILED, others OK |
| Versioning | Generate on v1, publish, create v2, assert v1 bills byte-identical |
| Immutability | Update attempt on a published bill raises at DB level |
| Duplicates | Second run for same (flat, template, period) is refused |
| Performance | 500-flat run stays within the query budget |
