/** Shared API types. Mirrors the FastAPI OpenAPI contract. */

export type SocietyStatus =
  | "PROVISIONING"
  | "PROVISIONING_FAILED"
  | "ACTIVE"
  | "LOCKED"
  | "SUSPENDED"
  | "ARCHIVED";

export type SubscriptionStatus = "TRIAL" | "ACTIVE" | "EXPIRED" | "CANCELLED" | "SUSPENDED";

export type BillingCycle = "MONTHLY" | "QUARTERLY" | "HALF_YEARLY" | "YEARLY";

export type ProvisioningState =
  | "PENDING"
  | "DATABASE_CREATED"
  | "MIGRATED"
  | "SEEDED"
  | "COMPLETED"
  | "FAILED";

export type RoleCode =
  | "SUPER_ADMIN"
  | "SOCIETY_ADMIN"
  | "FLAT_OWNER"
  | "MAINTENANCE_ADMIN"
  | "MAINTENANCE"
  | "HOUSEKEEPER_ADMIN"
  | "HOUSEKEEPER"
  | "SECURITY_ADMIN"
  | "SECURITY";

export interface Principal {
  id: string;
  firebase_uid: string;
  email: string;
  display_name: string;
  is_super_admin: boolean;
  society_id: string | null;
  tenant_user_id: string | null;
  roles: RoleCode[];
  permissions: string[];
  flat_ids: string[];
}

export interface SocietyContext {
  id: string;
  name: string;
  slug: string;
  status: SocietyStatus;
  city: string;
  state: string;
  timezone: string;
  total_flats: number;
}

export interface SubscriptionContext {
  status: SubscriptionStatus;
  plan_name: string | null;
  start_date: string;
  end_date: string;
  days_remaining: number;
  is_trial: boolean;
}

export interface ThemePayload {
  theme_mode: "light" | "dark" | "system";
  primary_color: string;
  secondary_color: string;
  accent_color: string;
  sidebar_color: string;
  border_radius: number;
  logo_url: string | null;
  society_name?: string | null;
  updated_at?: string | null;
}

export interface NavItem {
  key: string;
  label: string;
  icon: string;
  path: string;
  permission: string | null;
  badge: string | null;
  children: NavItem[];
}

export interface MeResponse {
  principal: Principal;
  society: SocietyContext | null;
  subscription: SubscriptionContext | null;
  theme: ThemePayload | null;
  navigation: NavItem[];
  auth_provider: string;
  server_time: string;
}

/* -------------------------------------------------------------------------- */
/* Platform                                                                   */
/* -------------------------------------------------------------------------- */

export interface Society {
  id: string;
  name: string;
  slug: string;
  registration_number: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string;
  state: string;
  pincode: string;
  contact_email: string;
  contact_phone: string;
  timezone: string;
  status: SocietyStatus;
  total_flats: number;
  locked_at: string | null;
  locked_reason: string | null;
  created_at: string;
}

export interface SocietyRegistry {
  database_name: string;
  sequence_number: number;
  provisioning_state: ProvisioningState;
  provisioning_step: string | null;
  provisioning_error: string | null;
  alembic_revision: string | null;
  migrated_at: string | null;
}

export interface SocietySubscriptionSummary {
  id: string;
  plan_name: string | null;
  status: SubscriptionStatus;
  start_date: string;
  end_date: string;
  days_remaining?: number;
}

export interface SocietyDetail extends Society {
  registry: SocietyRegistry | null;
  subscription: SocietySubscriptionSummary | null;
  admin_count: number;
  user_count: number;
}

export interface SocietyProvisionResult {
  society: Society;
  database_name: string;
  alembic_revision: string;
  admin_email: string;
  admin_firebase_uid: string;
  subscription: SocietySubscriptionSummary;
  resumed: boolean;
}

export interface SubscriptionPlan {
  id: string;
  name: string;
  code: string;
  description: string | null;
  price: string;
  billing_cycle: BillingCycle;
  max_flats: number | null;
  max_users: number | null;
  features: Record<string, unknown>;
  trial_days: number;
  is_active: boolean;
  sort_order: number;
}

export interface Subscription {
  id: string;
  society_id: string;
  plan_id: string;
  plan_name: string | null;
  status: SubscriptionStatus;
  start_date: string;
  end_date: string;
  is_current: boolean;
  price_snapshot: string;
  max_flats_snapshot: number | null;
  max_users_snapshot: number | null;
  notes: string | null;
  created_at: string;
}

export interface PlatformDashboard {
  total_societies: number;
  active_societies: number;
  locked_societies: number;
  provisioning_societies: number;
  failed_societies: number;
  active_subscriptions: number;
  expiring_soon: number;
  total_users: number;
  total_plans: number;
}

export interface PlatformUser {
  id: string;
  email: string;
  display_name: string;
  phone: string | null;
  is_super_admin: boolean;
  society_id: string | null;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface AuditLog {
  id: number;
  request_id: string | null;
  action: string;
  actor_email: string | null;
  society_id: string | null;
  target_type: string | null;
  target_id: string | null;
  changes: Record<string, unknown> | null;
  status: string;
  created_at: string;
}

/* -------------------------------------------------------------------------- */
/* Society scope                                                              */
/* -------------------------------------------------------------------------- */

export interface SocietySettings {
  society_name: string;
  registration_number: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state: string | null;
  pincode: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  timezone: string;
  currency: string;
  locale: string;
  financial_year_start_month: number;
  default_billing_cycle: string;
  bill_due_days: number;
  late_fee_percent: string;
  late_fee_grace_days: number;
  updated_at: string | null;
}

export interface SocietyDashboard {
  society_name: string;
  total_users: number;
  active_users: number;
  total_flats: number;
  total_buildings: number;
  total_residents: number;
  occupancy: Record<string, number>;
  unread_notifications: number;
  roles_summary: Record<string, number>;
  subscription_status: string;
  subscription_days_remaining: number;
  provisioned_at: string | null;
}

export interface TenantUser {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  avatar_url: string | null;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  roles: RoleCode[];
}

export interface Role {
  id: string;
  code: RoleCode;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: string[];
}

export interface Notification {
  id: string;
  category: string;
  title: string;
  body: string | null;
  link: string | null;
  is_read: boolean;
  created_at: string;
}

/* -------------------------------------------------------------------------- */
/* Structure (Phase 2)                                                        */
/* -------------------------------------------------------------------------- */

export type OccupancyStatus = "OWNER_OCCUPIED" | "RENTED" | "VACANT";
export type ResidentType = "OWNER" | "TENANT";

export interface Building {
  id: string;
  name: string;
  code: string;
  description: string | null;
  total_floors: number | null;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  block_count: number;
  floor_count: number;
  flat_count: number;
}

export interface Block {
  id: string;
  building_id: string;
  building_name: string | null;
  name: string;
  code: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
  created_at: string;
  floor_count: number;
  flat_count: number;
}

export interface Floor {
  id: string;
  block_id: string;
  block_name: string | null;
  building_id: string | null;
  building_name: string | null;
  number: number;
  name: string | null;
  display_name: string;
  flat_count: number;
  created_at: string;
}

export interface Flat {
  id: string;
  flat_number: string;
  flat_type: string | null;
  area_sqft: string;
  carpet_area_sqft: string | null;
  occupancy_status: OccupancyStatus;
  base_maintenance_override: string | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  floor_id: string;
  block_id: string;
  building_id: string;
  floor_number: number | null;
  floor_name: string | null;
  block_name: string | null;
  building_name: string | null;
  resident_count: number;
}

export interface FlatDetail extends Flat {
  residents: ResidentSummary[];
}

export interface ResidentSummary {
  id: string;
  full_name: string;
  phone: string | null;
  email: string | null;
  resident_type: ResidentType;
  is_primary: boolean;
}

export interface Resident {
  id: string;
  flat_id: string;
  flat_number: string | null;
  user_id: string | null;
  full_name: string;
  email: string | null;
  phone: string | null;
  resident_type: ResidentType;
  is_primary: boolean;
  move_in_date: string | null;
  move_out_date: string | null;
  is_active: boolean;
  created_at: string;
}

export type FamilyRelationship =
  | "SPOUSE"
  | "FATHER"
  | "MOTHER"
  | "SON"
  | "DAUGHTER"
  | "BROTHER"
  | "SISTER"
  | "GRANDPARENT"
  | "GRANDCHILD"
  | "OTHER";

/** NONE means "on the roster, no login". Every other level maps to a role. */
export type FamilyAccessLevel = "NONE" | "CHILD" | "MEMBER" | "CO_ADMIN";

export const FAMILY_RELATIONSHIPS: { value: FamilyRelationship; label: string }[] = [
  { value: "SPOUSE", label: "Spouse" },
  { value: "FATHER", label: "Father" },
  { value: "MOTHER", label: "Mother" },
  { value: "SON", label: "Son" },
  { value: "DAUGHTER", label: "Daughter" },
  { value: "BROTHER", label: "Brother" },
  { value: "SISTER", label: "Sister" },
  { value: "GRANDPARENT", label: "Grandparent" },
  { value: "GRANDCHILD", label: "Grandchild" },
  { value: "OTHER", label: "Other" },
];

export const FAMILY_ACCESS_LEVELS: {
  value: Exclude<FamilyAccessLevel, "NONE">;
  label: string;
  hint: string;
}[] = [
  {
    value: "CO_ADMIN",
    label: "Co-admin",
    hint: "Everything you can do, including managing the household.",
  },
  {
    value: "MEMBER",
    label: "Member",
    hint: "Sees the whole flat — bills, meters, visitors. Cannot change it.",
  },
  {
    value: "CHILD",
    label: "Restricted",
    hint: "Notices, visitors and amenities. No bills or meter readings.",
  },
];

export interface FamilyMember {
  id: string;
  resident_id: string;
  full_name: string;
  relationship_to_resident: FamilyRelationship;
  date_of_birth: string | null;
  phone: string | null;
  email: string | null;
  access_level: FamilyAccessLevel;
  is_active: boolean;
  has_login: boolean;
}

export interface ResidentDetail extends Resident {
  family_members: FamilyMember[];
}

export interface FlatBulkResult {
  created: number;
  skipped: number;
  floors_created: number;
  dry_run: boolean;
  preview: string[];
  conflicts: string[];
}

export interface StructureSummary {
  buildings: number;
  blocks: number;
  floors: number;
  flats: number;
  residents: number;
  total_area_sqft: number;
  occupancy: Record<string, number>;
  resident_types: Record<string, number>;
  flat_types: string[];
}

export interface StructureTreeNode {
  id: string;
  label: string;
  kind: "building" | "block" | "floor";
  flat_count: number;
  children: StructureTreeNode[];
}

/* -------------------------------------------------------------------------- */
/* Billing (Phase 3)                                                          */
/* -------------------------------------------------------------------------- */

export type BillingRunStatus =
  | "PENDING" | "RUNNING" | "COMPLETED" | "COMPLETED_WITH_ERRORS" | "FAILED" | "PUBLISHED";
export type BillStatus = "DRAFT" | "PUBLISHED" | "FAILED" | "VOID";
export type BillPaymentStatus =
  | "UNPAID" | "PARTIAL" | "PAID" | "OVERDUE" | "PENDING" | "SUCCESS" | "FAILED" | "REFUNDED";
export type PaymentMethod =
  | "CASH" | "CHEQUE" | "NEFT" | "UPI" | "CARD" | "NETBANKING" | "ADJUSTMENT";
export type AssignmentScope = "ALL" | "BUILDING" | "BLOCK" | "FLAT_TYPE" | "FLAT";
export type BillingFrequencyCode =
  | "MONTHLY" | "QUARTERLY" | "HALF_YEARLY" | "YEARLY" | "ONE_TIME";

/** A node of the formula AST. Structured JSON — never a string, never eval'd. */
export interface FormulaNode {
  type: string;
  label?: string | null;
  value?: string;
  text?: string;
  bool_value?: boolean;
  field?: string;
  children?: FormulaNode[];
  input?: FormulaNode;
  mode?: "PROGRESSIVE" | "FLAT";
  slabs?: { up_to: string | null; rate: string }[];
  decimal_places?: number;
}

export interface LineItemSpec {
  code: string;
  label: string;
  node: FormulaNode;
  is_credit?: boolean;
  quantity_field?: string | null;
  unit?: string | null;
  sort_order?: number;
}

export interface FormulaDefinition {
  root?: FormulaNode | null;
  line_items: LineItemSpec[];
}

export interface FieldSpec {
  key: string;
  label: string;
  kind: "MONEY" | "QUANTITY" | "COUNT" | "TEXT" | "BOOLEAN";
  unit: string | null;
  description: string;
  group: string;
}

export interface FormulaError {
  code: string;
  message: string;
  path: string;
}

export interface BillTemplate {
  id: string;
  name: string;
  description: string | null;
  frequency: BillingFrequencyCode;
  is_active: boolean;
  active_version_id: string | null;
  version_count: number;
  run_count: number;
  created_at: string;
}

export interface TemplateVersion {
  id: string;
  template_id: string;
  version_number: number;
  formula: FormulaDefinition;
  parameters: Record<string, unknown>;
  notes: string | null;
  is_published: boolean;
  is_active: boolean;
  bill_count: number;
  created_at: string;
}

export interface TemplateAssignment {
  id: string;
  template_id: string;
  scope: AssignmentScope;
  building_id: string | null;
  block_id: string | null;
  flat_id: string | null;
  flat_type: string | null;
  priority: number;
  is_active: boolean;
}

export interface BillTemplateDetail extends BillTemplate {
  versions: TemplateVersion[];
  assignments: TemplateAssignment[];
}

export interface PreviewLineItem {
  code: string;
  label: string;
  amount: string;
  is_credit: boolean;
  quantity: string | null;
  unit: string | null;
  rate: string | null;
  sort_order: number;
}

export interface PreviewResult {
  valid: boolean;
  errors: FormulaError[];
  flat: { id: string; flat_number: string; area_sqft?: string; flat_type?: string | null } | null;
  period?: { key: string; label: string; start: string; end: string };
  line_items: PreviewLineItem[];
  subtotal?: string;
  credits?: string;
  total: string;
  trace: TraceEntry[];
  inputs?: Record<string, string>;
  message?: string;
}

export interface TraceEntry {
  path: string;
  node_type: string;
  label: string | null;
  inputs: string[];
  result: string;
  detail: string | null;
}

export interface PeriodOption {
  frequency: string;
  key: string;
  label: string;
  start: string;
  end: string;
  already_billed: boolean;
  run_id: string | null;
}

export interface BillingRun {
  id: string;
  template_id: string;
  template_name: string | null;
  template_version_id: string;
  version_number: number | null;
  frequency: BillingFrequencyCode;
  period_key: string;
  period_label: string;
  period_start: string;
  period_end: string;
  due_date: string;
  status: BillingRunStatus;
  total_flats: number;
  bills_generated: number;
  bills_failed: number;
  total_amount: string;
  error_summary: { flat_number: string; message: string }[] | null;
  started_at: string | null;
  completed_at: string | null;
  published_at: string | null;
  created_at: string;
}

export interface BillLineItem {
  id?: string;
  sort_order: number;
  code: string;
  label: string;
  quantity: string | null;
  unit: string | null;
  rate: string | null;
  amount: string;
  is_credit: boolean;
}

export interface Bill {
  id: string;
  bill_number: string;
  billing_run_id: string;
  flat_id: string;
  flat_number: string | null;
  template_id: string;
  template_version_id: string;
  period_key: string;
  period_label: string;
  period_start: string;
  period_end: string;
  subtotal: string;
  penalty: string;
  discount: string;
  tax: string;
  total: string;
  amount_paid: string;
  balance_due: string;
  status: BillStatus;
  payment_status: BillPaymentStatus;
  issued_at: string | null;
  due_date: string;
  paid_at: string | null;
  failure_reason: string | null;
  created_at: string;
}

export interface BillDetail extends Bill {
  line_items: BillLineItem[];
}

export interface BillCalculation {
  bill_id: string;
  bill_number: string;
  period_label: string;
  inputs: Record<string, string>;
  formula: FormulaDefinition;
  trace: TraceEntry[];
  line_items: BillLineItem[];
  subtotal: string;
  discount: string;
  total: string;
}

export interface BillingSummary {
  total_bills: number;
  total_billed: string;
  total_collected: string;
  total_outstanding: string;
  collection_rate: number;
  by_payment_status: Record<string, number>;
}

export interface PaymentRecord {
  id: string;
  bill_id: string | null;
  bill_number: string | null;
  flat_id: string;
  amount: string;
  method: PaymentMethod;
  status: BillPaymentStatus;
  reference_number: string | null;
  paid_at: string | null;
  notes: string | null;
  created_at: string;
}

/* -------------------------------------------------------------------------- */
/* Phase 4 — utilities, assets and the resident dashboard                      */
/* -------------------------------------------------------------------------- */

export type Utility = "water" | "electricity";
export type SlotType = "TWO_WHEELER" | "FOUR_WHEELER" | "VISITOR" | "HANDICAPPED";
export type VehicleType = "TWO_WHEELER" | "FOUR_WHEELER" | "BICYCLE" | "OTHER";
export type PetType = "DOG" | "CAT" | "BIRD" | "OTHER";

export interface UtilityReading {
  id: string;
  flat_id: string;
  flat_number: string | null;
  reading_date: string;
  period_key: string | null;
  previous_reading: string | null;
  current_reading: string;
  /** Generated by the database from the two readings; never sent on input. */
  consumption: string;
  meter_number: string | null;
  remarks: string | null;
  amount: string | null;
  created_at: string;
}

export interface PendingFlat {
  flat_id: string;
  flat_number: string;
  building_name: string | null;
  previous_reading: string | null;
  last_reading_date: string | null;
}

export interface BulkReadingResult {
  created: number;
  skipped: number;
  skipped_flat_ids: string[];
}

export interface ConsumptionPoint {
  reading_date: string;
  label: string;
  consumption: string;
  current_reading: string | null;
  amount: string | null;
}

export interface ConsumptionStats {
  readings: number;
  average: string;
  highest: string;
  lowest: string;
  total: string;
}

export interface ConsumptionTrend {
  unit: "kL" | "kWh";
  points: ConsumptionPoint[];
  stats: ConsumptionStats;
  latest: string | null;
  previous: string | null;
  change_pct: string | null;
}

export interface SocietyConsumptionPoint {
  reading_date: string;
  label: string;
  total: string;
}

export interface ParkingSlot {
  id: string;
  slot_number: string;
  building_id: string | null;
  level: string | null;
  slot_type: SlotType;
  monthly_charge: string;
  flat_id: string | null;
  flat_number: string | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
}

export interface ParkingSummary {
  total: number;
  allotted: number;
  available: number;
}

export interface Vehicle {
  id: string;
  flat_id: string;
  flat_number: string | null;
  registration_number: string;
  vehicle_type: VehicleType;
  make: string | null;
  model: string | null;
  color: string | null;
  parking_slot_id: string | null;
  parking_slot_number: string | null;
  is_active: boolean;
  created_at: string;
}

export interface Pet {
  id: string;
  flat_id: string;
  flat_number: string | null;
  name: string;
  pet_type: PetType;
  breed: string | null;
  registration_number: string | null;
  vaccination_expiry: string | null;
  vaccination_due: boolean;
  monthly_fee: string;
  is_active: boolean;
  created_at: string;
}

export interface DashboardFlat {
  id: string;
  flat_number: string;
  building_name: string | null;
  block_name: string | null;
  floor_name: string | null;
  area_sqft: string;
}

export interface DashboardBill {
  id: string;
  bill_number: string;
  period_label: string;
  total_amount: string;
  amount_paid: string;
  balance: string;
  due_date: string;
  status: BillPaymentStatus;
  is_overdue: boolean;
  days_until_due: number;
}

export interface DashboardPayment {
  id: string;
  amount: string;
  paid_on: string;
  method: PaymentMethod;
  reference: string | null;
  bill_number: string | null;
}

export interface DashboardCharge {
  label: string;
  amount: string;
}

export interface ResidentDashboard {
  flats: DashboardFlat[];
  outstanding: string;
  overdue_count: number;
  next_due: DashboardBill | null;
  recent_bills: DashboardBill[];
  recent_payments: DashboardPayment[];
  charge_breakdown: DashboardCharge[];
  water: ConsumptionTrend | null;
  electricity: ConsumptionTrend | null;
  vehicles: number;
  parking_slots: number;
  pets: number;
  paid_this_year: string;
}

export interface UtilityDashboard {
  water: SocietyConsumptionPoint[];
  electricity: SocietyConsumptionPoint[];
  parking: ParkingSummary;
  vehicles_by_type: Record<string, number>;
  pets: number;
  flats_missing_water: number;
  flats_missing_electricity: number;
}

/* -------------------------------------------------------------------------- */
/* Phase 5 — operations                                                       */
/* -------------------------------------------------------------------------- */

export type Priority = "LOW" | "MEDIUM" | "HIGH" | "URGENT";

export type ComplaintCategory =
  | "PLUMBING"
  | "ELECTRICAL"
  | "LIFT"
  | "HOUSEKEEPING"
  | "SECURITY"
  | "PARKING"
  | "NOISE"
  | "WATER_SUPPLY"
  | "COMMON_AREA"
  | "BILLING"
  | "OTHER";

export type ComplaintStatus =
  | "OPEN"
  | "ACKNOWLEDGED"
  | "IN_PROGRESS"
  | "RESOLVED"
  | "CLOSED"
  | "REJECTED"
  | "REOPENED";

export type Department = "MAINTENANCE" | "HOUSEKEEPING";

export type TaskStatus =
  | "PENDING"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "VERIFIED"
  | "CANCELLED"
  | "SKIPPED";

export type Recurrence =
  | "DAILY"
  | "WEEKLY"
  | "FORTNIGHTLY"
  | "MONTHLY"
  | "QUARTERLY"
  | "HALF_YEARLY"
  | "YEARLY";

export type VisitorType =
  | "GUEST"
  | "DELIVERY"
  | "CAB"
  | "SERVICE"
  | "DOMESTIC_HELP"
  | "VENDOR"
  | "OTHER";

export type VisitorStatus =
  | "EXPECTED"
  | "AWAITING_APPROVAL"
  | "APPROVED"
  | "DENIED"
  | "CHECKED_IN"
  | "CHECKED_OUT"
  | "EXPIRED";

export type IncidentSeverity = "INFO" | "MINOR" | "MAJOR" | "CRITICAL";
export type IncidentStatus = "REPORTED" | "INVESTIGATING" | "RESOLVED" | "CLOSED";

export interface ComplaintComment {
  id: string;
  author_id: string | null;
  author_name: string;
  body: string;
  is_internal: boolean;
  is_system: boolean;
  created_at: string;
}

export interface Complaint {
  id: string;
  ticket_number: string;
  flat_id: string | null;
  flat_number: string | null;
  raised_by: string | null;
  raised_by_name: string;
  title: string;
  description: string;
  category: ComplaintCategory;
  priority: Priority;
  status: ComplaintStatus;
  location: string | null;
  assigned_to: string | null;
  assignee_name: string | null;
  assigned_department: Department | null;
  due_by: string | null;
  is_overdue: boolean;
  acknowledged_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  resolution_notes: string | null;
  reopen_count: number;
  rating: number | null;
  rating_comment: string | null;
  comment_count: number;
  age_hours: number;
  created_at: string;
  updated_at: string;
}

export interface ComplaintDetail extends Complaint {
  comments: ComplaintComment[];
  /** What this principal may do next — the client renders buttons from this. */
  allowed_transitions: ComplaintStatus[];
}

export interface ComplaintSummary {
  total: number;
  open: number;
  overdue: number;
  resolved_this_month: number;
  unassigned: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  by_priority: Record<string, number>;
  average_resolution_hours: string | null;
  satisfaction: string | null;
}

export interface WorkSchedule {
  id: string;
  department: Department;
  title: string;
  description: string | null;
  area: string | null;
  building_id: string | null;
  building_name: string | null;
  recurrence: Recurrence;
  priority: Priority;
  assigned_to: string | null;
  assignee_name: string | null;
  estimated_cost: string | null;
  vendor_name: string | null;
  vendor_phone: string | null;
  starts_on: string;
  next_due_on: string;
  ends_on: string | null;
  lead_days: number;
  is_active: boolean;
  open_tasks: number;
  created_at: string;
}

export interface WorkTask {
  id: string;
  department: Department;
  schedule_id: string | null;
  schedule_title: string | null;
  complaint_id: string | null;
  title: string;
  description: string | null;
  area: string | null;
  building_id: string | null;
  building_name: string | null;
  status: TaskStatus;
  priority: Priority;
  assigned_to: string | null;
  assignee_name: string | null;
  due_on: string;
  is_overdue: boolean;
  started_at: string | null;
  completed_at: string | null;
  verified_at: string | null;
  completion_notes: string | null;
  actual_cost: string | null;
  vendor_name: string | null;
  allowed_transitions: TaskStatus[];
  created_at: string;
}

export interface WorkSummary {
  department: Department;
  total: number;
  pending: number;
  in_progress: number;
  overdue: number;
  completed_this_month: number;
  awaiting_verification: number;
  active_schedules: number;
  cost_this_month: string;
}

export interface ScheduleRunResult {
  schedules_examined: number;
  tasks_created: number;
  schedules_advanced: number;
  skipped_existing: number;
}

export interface Visitor {
  id: string;
  pass_code: string | null;
  flat_id: string;
  flat_number: string | null;
  visitor_name: string;
  visitor_phone: string | null;
  visitor_type: VisitorType;
  company: string | null;
  purpose: string | null;
  accompanying_count: number;
  vehicle_number: string | null;
  status: VisitorStatus;
  expected_from: string | null;
  expected_to: string | null;
  approved_at: string | null;
  denial_reason: string | null;
  /** APP — the resident in the app; PHONE — the guard called the flat; GUARD — turned away by the guard. */
  approved_via: "APP" | "PHONE" | "GUARD" | null;
  /** The resident the guard spoke to, for PHONE decisions. */
  confirmed_with: string | null;
  checked_in_at: string | null;
  checked_out_at: string | null;
  duration_minutes: number | null;
  notes: string | null;
  created_at: string;
}

export interface VisitorSummary {
  on_premises: number;
  expected_today: number;
  awaiting_approval: number;
  entries_today: number;
  denied_today: number;
}

export interface SecurityIncident {
  id: string;
  title: string;
  description: string;
  severity: IncidentSeverity;
  status: IncidentStatus;
  location: string | null;
  building_id: string | null;
  building_name: string | null;
  flat_id: string | null;
  flat_number: string | null;
  occurred_at: string;
  reported_by: string | null;
  reported_by_name: string;
  action_taken: string | null;
  resolved_at: string | null;
  police_reference: string | null;
  people_involved: number | null;
  created_at: string;
}

export interface SecurityDashboard {
  visitors: VisitorSummary;
  open_incidents: number;
  critical_incidents: number;
  incidents_this_month: number;
  recent_incidents: SecurityIncident[];
  on_premises: Visitor[];
}

/* -------------------------------------------------------------------------- */
/* Phase 5 — community                                                        */
/* -------------------------------------------------------------------------- */

export type NoticeCategory =
  | "GENERAL"
  | "URGENT"
  | "MAINTENANCE"
  | "EVENT"
  | "MEETING"
  | "BILLING"
  | "SECURITY";

export type AudienceScope = "ALL" | "BUILDING" | "BLOCK" | "OWNERS" | "TENANTS" | "STAFF";

export type BookingStatus =
  | "PENDING"
  | "CONFIRMED"
  | "CANCELLED"
  | "REJECTED"
  | "COMPLETED"
  | "NO_SHOW";

export interface NoticeAttachment {
  name: string;
  url: string;
  size_bytes: number | null;
}

export interface Notice {
  id: string;
  title: string;
  body: string;
  category: NoticeCategory;
  priority: Priority;
  audience: AudienceScope;
  building_id: string | null;
  building_name: string | null;
  block_id: string | null;
  block_name: string | null;
  is_pinned: boolean;
  is_published: boolean;
  publish_at: string | null;
  expires_at: string | null;
  is_expired: boolean;
  attachments: NoticeAttachment[];
  author_id: string | null;
  author_name: string;
  is_read: boolean;
  /** Zero unless the caller can manage notices. */
  read_count: number;
  created_at: string;
}

export interface NoticeSummary {
  total: number;
  published: number;
  scheduled: number;
  expired: number;
  unread: number;
}

export interface Amenity {
  id: string;
  name: string;
  description: string | null;
  location: string | null;
  building_id: string | null;
  building_name: string | null;
  capacity: number | null;
  opens_at: string;
  closes_at: string;
  slot_minutes: number;
  booking_charge: string;
  max_advance_days: number;
  max_slots_per_booking: number;
  max_active_per_flat: number;
  requires_approval: boolean;
  rules: string | null;
  is_active: boolean;
  upcoming_bookings: number;
  created_at: string;
}

export interface AmenitySlot {
  starts_at: string;
  ends_at: string;
  label: string;
  available: boolean;
  /** Null for a neighbour: who is having a party is not public information. */
  booked_by_flat: string | null;
  is_own: boolean;
  booking_id: string | null;
}

export interface Availability {
  amenity_id: string;
  amenity_name: string;
  booking_date: string;
  slot_minutes: number;
  booking_charge: string;
  slots: AmenitySlot[];
}

export interface AmenityBooking {
  id: string;
  amenity_id: string;
  amenity_name: string | null;
  flat_id: string;
  flat_number: string | null;
  booked_by: string | null;
  booked_by_name: string;
  booking_date: string;
  starts_at: string;
  ends_at: string;
  slots: number;
  guests: number;
  purpose: string | null;
  status: BookingStatus;
  charge: string;
  approved_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  can_cancel: boolean;
  created_at: string;
}

export interface AmenitySummary {
  amenities: number;
  bookings_today: number;
  upcoming: number;
  pending_approval: number;
  revenue_this_month: string;
}

/* -------------------------------------------------------------------------- */
/* Phase 6 — notifications, realtime, reports                                 */
/* -------------------------------------------------------------------------- */

export interface Notification {
  id: string;
  channel: "IN_APP" | "EMAIL" | "PUSH" | "SMS" | "WHATSAPP";
  category: string;
  title: string;
  body: string | null;
  link: string | null;
  payload: Record<string, unknown> | null;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
}

export interface NotificationFeed {
  items: Notification[];
  unread: number;
  total: number;
}

/** What arrives down the `/ws` socket. */
export interface RealtimeMessage {
  type: "connected" | "ping" | "notification";
  data: {
    category?: string;
    title?: string;
    body?: string | null;
    link?: string | null;
    [key: string]: unknown;
  };
}

export type ReportColumnType = "text" | "number" | "money" | "date" | "percent" | "status";

export interface ReportColumn {
  key: string;
  label: string;
  type: ReportColumnType;
  total: boolean;
}

export interface ReportMeta {
  key: string;
  title: string;
  description: string;
  permission: string;
  accepts_period: boolean;
  accepts_dates: boolean;
}

export interface ReportResult {
  key: string;
  title: string;
  description: string;
  generated_at: string;
  period_label: string | null;
  from_date: string | null;
  to_date: string | null;
  columns: ReportColumn[];
  rows: Record<string, string | number | null>[];
  totals: Record<string, string | number>;
  summary: Record<string, string | number | null>;
  row_count: number;
  /** True when the row cap was hit — the screen says so rather than lying. */
  truncated: boolean;
}
