// Wire types for Bara spec v1.1.x, hand-written from spec/schemas (draft 2020-12).
// Schemas are open: every object may carry unknown fields, which clients ignore.
// Server-sent enums are typed as `Known | (string & {})` so values from a newer
// server type-check and get mapped to `unknown` at render time (SPEC 1, item 8).

export const SPEC_VERSION = "1.1.0";

/** A string enum that may contain values this client does not know. */
export type Open<T extends string> = T | (string & {});

export type Vec2 = number[];
export type Vec3 = number[];
export interface BBox {
  min: Vec3;
  max: Vec3;
}

export type Material = Open<"plastic" | "metal" | "pcb" | "rubber" | "glass" | "fabric" | "wood" | "unknown">;
export interface Color {
  hex: string;
  material?: Material;
  node?: string | null;
}

export const STAGE_IDS = ["classify", "reuse", "compose", "place", "enclose", "board", "firmware", "render"] as const;
export type BuildStageId = (typeof STAGE_IDS)[number];
export type StageId = Open<BuildStageId | "edit" | "unknown">;
export type Tier = Open<"exact" | "substitute" | "compose" | "unknown">;
export type Severity = Open<"info" | "warning" | "error" | "critical" | "unknown">;
export type CheckStatus = Open<"pass" | "fail" | "unknown">;
export type TriState = Open<"yes" | "no" | "unknown">;
export type Side = Open<"left" | "right" | "center" | "none" | "unknown">;
export type Criticality = Open<"critical" | "optional" | "unknown">;
export type Origin = Open<"design" | "compose" | "solver" | "user" | "unknown">;
export type Verified = Open<"geometry" | "human" | "datasheet" | "third_party" | "none" | "unknown">;
export type PartKind = Open<"module" | "component" | "pcb" | "mechanical" | "fastener" | "cable" | "other" | "unknown">;

export interface PortRef {
  instance_id: string;
  interface_id: string;
  index?: number | null;
}

export interface Subject {
  instance_id?: string;
  interface_id?: string;
  connection_id?: string;
  slot_id?: string;
  part_id?: string;
  enclosure_id?: string;
  board_id?: string;
}

export interface KeySpec {
  label: string;
  value: string | number | boolean;
  unit?: string | null;
}

export interface AssetRef {
  asset_id: string;
  kind: Open<
    | "glb" | "png" | "svg" | "stl" | "3mf" | "step" | "kicad_pcb" | "gerber_zip" | "firmware_src_zip"
    | "firmware_bin" | "uf2" | "bom_csv" | "log" | "zip" | "json" | "unknown"
  >;
  role?: Open<"model" | "model_lod1" | "thumbnail" | "render" | "export" | "source" | "binary" | "log" | "unknown">;
  url: string;
  content_type?: string;
  bytes?: number;
  sha256?: string | null;
  status?: Open<"ready" | "pending" | "missing" | "unknown">;
  nodes?: string[];
  origin?: Open<"design" | "generated" | "catalog" | "unknown">;
}

export interface PartCard {
  part_id: string;
  display_name: string;
  kind: PartKind;
  primary_function?: string;
  summary?: string | null;
  key_specs?: KeySpec[];
  thumbnail_url?: string | null;
  licence_spdx?: string;
  commercial_ok?: TriState;
  verified?: Verified;
  source_url?: string | null;
}

export interface Interface {
  id: string;
  type: string;
  role: Open<"provides" | "requires" | "unknown">;
  label?: string;
  params: Record<string, unknown>;
  pins?: string[];
  signals?: Record<string, string>;
  optional?: boolean;
  max_connections?: number | null;
}

export interface Licence {
  spdx: string;
  name?: string;
  url?: string | null;
  commercial_ok: TriState;
  copyleft?: TriState;
  attribution_required?: TriState;
  attribution?: string | null;
  notes?: string | null;
}

export interface Provenance {
  extractor?: string;
  verified?: Verified;
  confidence?: number;
  source_url?: string;
  dims_source_url?: string | null;
  retrieved_at?: string;
  [key: string]: unknown;
}

export interface Part {
  part_id: string;
  kind: PartKind;
  display_name: string;
  mpn?: string | null;
  manufacturer?: string | null;
  summary?: string | null;
  datasheet?: string;
  functions: { function_id: string; primary?: boolean; params?: Record<string, unknown> }[];
  interfaces: Interface[];
  electrical?: Record<string, number>;
  mechanical?: { bbox_mm?: BBox; mass_g?: number; standards?: string[] };
  render?: { default_color?: string; material?: Material; recolorable_nodes?: string[] };
  assets?: AssetRef[];
  licence: Licence;
  provenance: Provenance;
  facets?: Record<string, unknown>;
  status?: Open<"active" | "deprecated" | "unknown">;
}

// ---- Spec ----

export type RequirementSource = Open<"explicit" | "implicit" | "default" | "clarified" | "assumed" | "unknown">;
export interface Requirement {
  req_id: string;
  facet: string;
  op: Open<"eq" | "neq" | "in" | "lte" | "gte" | "range" | "has" | "unknown">;
  value: unknown;
  unit?: string | null;
  source?: RequirementSource;
  text_span?: number[] | null;
  label?: string;
}
export interface Assumption {
  assumption_id: string;
  facet: string;
  value: string | number | boolean;
  label: string;
  reason?: string | null;
}
export interface ClarifyOption {
  option_id: string;
  label: string;
  description?: string | null;
  implies?: Requirement[];
}
export interface ClarifyQuestion {
  question_id: string;
  question: string;
  options: ClarifyOption[];
  allow_free_text: boolean;
  allow_skip?: boolean;
  default_option_id?: string | null;
  reason: string;
  missing_facets: string[];
  timeout_ms?: number;
  round: number;
}
export interface ClarifyResolution {
  question_id: string;
  resolution: Open<"answered_option" | "answered_text" | "skipped" | "timeout" | "unknown">;
  option_id?: string | null;
  free_text?: string | null;
  assumptions: Assumption[];
}

export interface Spec {
  spec_id: string;
  prompt: string;
  normalized_prompt?: string;
  device_class: string;
  taxonomy_path: string[];
  functions: { function_id: string; required: boolean; count?: number; source?: RequirementSource }[];
  hard_requirements: Requirement[];
  soft_requirements: Requirement[];
  leftover_text?: string | null;
  classifier: {
    stage: Open<"rules" | "knn" | "llm" | "cache" | "unknown">;
    confidence: number;
    margin?: number | null;
    model?: string | null;
    latency_ms?: number;
    provider?: string | null;
    fallback?: boolean;
  };
  scope?: Open<"in_scope" | "out_of_scope" | "unknown">;
  scope_reason?: string | null;
  assumptions?: Assumption[];
  ambiguity?: { needs_clarify: boolean; missing_facets?: string[]; blocking_facet?: string | null };
  main_purpose?: string | null;
  reuse?: {
    candidate_design_id: string | null;
    covers_main_purpose: boolean;
    changes_needed: string[];
    verified: boolean;
  };
}

// ---- Slots and decisions ----

export type SlotState = Open<"pending" | "narrowing" | "decided" | "none" | "dead_end" | "unknown">;
export interface Slot {
  slot_id: string;
  label: string;
  function_id: string;
  criticality: Criticality;
  quantity?: number;
  side?: Side;
  order?: number | null;
  state: SlotState;
  candidates_total?: number | null;
  candidates_left?: number | null;
  chosen_part_id?: string | null;
  instance_ids?: string[];
  from_design?: boolean;
}
export interface Filter {
  facet: string;
  op: string;
  value: unknown;
  reason: Open<"requirement" | "propagated" | "compatibility" | "licence" | "relaxed" | "unknown">;
  from_slot_id?: string | null;
  req_id?: string | null;
  count_before?: number;
  count_after?: number;
  label?: string;
}
export interface Candidate {
  short_id: string;
  card: PartCard;
  score?: number | null;
  is_default?: boolean;
}
export interface Decision {
  decision_id: string;
  slot_id: string;
  step?: number;
  method: Open<"design" | "only_survivor" | "default" | "model_pick" | "solver" | "user" | "none" | "unknown">;
  chosen_part_id: string | null;
  chosen_short_id?: string | null;
  survivors?: number;
  reason: string;
  model?: {
    provider?: string;
    model?: string;
    latency_ms?: number;
    cached?: boolean;
    fallback?: boolean;
  } | null;
  propagated?: { slot_id: string; count_before: number; count_after: number; constraint?: string }[];
}

// ---- Build ----

export interface Placement {
  mode: Open<"single" | "layout" | "unknown">;
  position_mm: Vec3;
  rotation_deg: Vec3;
  layout_id?: string | null;
  /** Layout keys this instance covers, by key width in u (absent = every key). */
  key_widths_u?: number[];
  explode_offset_mm?: Vec3;
  source?: Open<"design" | "solver" | "intent" | "user" | "unknown">;
  locked?: boolean;
  intent?: Record<string, unknown> | null;
}

export interface LayoutKey {
  i: number;
  x_u: number;
  y_u: number;
  w_u?: number;
  h_u?: number;
  r_deg?: number;
  rx_u?: number;
  ry_u?: number;
  matrix?: number[];
}
export interface Layout {
  layout_id: string;
  name?: string;
  pitch_x_mm: number;
  pitch_y_mm: number;
  keys: LayoutKey[];
}

export type ObjStatus = Open<"ok" | "warning" | "failed" | "unknown">;
export interface BuildPart {
  instance_id: string;
  part_id: string;
  slot_id?: string | null;
  label?: string;
  quantity: number;
  side?: Side;
  color?: Color | null;
  placement: Placement;
  card: PartCard;
  assets?: AssetRef[];
  origin?: Origin;
  status?: ObjStatus;
}

export interface Connection {
  connection_id: string;
  type: string;
  kind: Open<"electrical" | "mechanical" | "wireless" | "unknown">;
  from: PortRef;
  to: PortRef;
  via_instance_id?: string | null;
  nets?: { signal: string; from_pin?: string | null; to_pin?: string | null }[];
  resolved?: Record<string, unknown>;
  label?: string;
  origin?: Origin;
  status?: ObjStatus;
}

export interface Cutout {
  cutout_id: string;
  for?: PortRef | null;
  feature?: string;
  face: string;
  shape: Open<"rect" | "circle" | "slot" | "unknown">;
  center_mm: Vec3;
  size_mm: Vec2;
}

export type BuildObjStatus = Open<"pending" | "ok" | "failed" | "unknown">;
export interface EnclosureParams {
  wall_mm?: number;
  floor_mm?: number;
  fillet_mm?: number;
  clearance_mm?: number;
  height_mm?: number | null;
  split?: Open<"none" | "lid_top" | "tray" | "halves" | "unknown">;
  standoff_height_mm?: number;
  screw?: string;
}
export interface Enclosure {
  enclosure_id: string;
  kind: Open<"generated" | "design" | "none" | "unknown">;
  side?: Side;
  for_instance_ids?: string[];
  params: EnclosureParams;
  outer_size_mm?: Vec3;
  position_mm?: Vec3;
  rotation_deg?: Vec3;
  explode_offset_mm?: Vec3;
  cutouts?: Cutout[];
  color?: Color | null;
  assets?: AssetRef[];
  status: BuildObjStatus;
  duration_ms?: number;
  revision: number;
  material?: Material;
  color_source?: Open<"default" | "user" | "design" | "unknown">;
}

export interface Net {
  name: string;
  kind?: Open<"power" | "ground" | "signal" | "unknown">;
  members: { instance_id: string; pin: string; index?: number | null }[];
}
export interface Board {
  board_id: string;
  source: Open<"design" | "prerouted" | "tscircuit" | "none" | "unknown">;
  side?: Side;
  part_instance_id?: string | null;
  for_instance_ids?: string[];
  outline_mm?: Vec2[];
  size_mm?: Vec2;
  thickness_mm?: number;
  layers?: number;
  position_mm?: Vec3;
  rotation_deg?: Vec3;
  nets?: Net[];
  routing?: {
    status?: Open<"routed" | "partial" | "unrouted" | "skipped" | "unknown">;
    unrouted_nets?: string[];
    duration_ms?: number;
    method?: Open<"design" | "autorouted" | "none" | "unknown">;
    cache_key?: string | null;
    cache_hit?: boolean;
    router?: string | null;
  };
  drc?: CheckStatus;
  assets?: AssetRef[];
  status: BuildObjStatus;
  revision: number;
}

export interface FirmwareFile {
  path: string;
  language: string;
  content?: string | null;
  asset?: AssetRef | null;
  bytes?: number;
}
export interface Firmware {
  firmware_id: string;
  framework: string;
  origin?: Open<"design" | "template" | "unknown">;
  targets?: { target_id: string; mcu_instance_id: string; side?: Side; label?: string }[];
  files: FirmwareFile[];
  drivers?: { part_id: string; library: string; version?: string | null; include?: string | null }[];
  pin_map?: {
    instance_id: string;
    interface_id?: string | null;
    signal: string;
    mcu_instance_id: string;
    mcu_pin: string;
  }[];
  compile: {
    status: Open<"pending" | "running" | "ok" | "failed" | "skipped" | "unknown">;
    duration_ms?: number;
    binaries?: AssetRef[];
    log?: AssetRef | null;
    message?: string | null;
  };
  revision: number;
  mode?: Open<"prebuilt" | "compiled" | "unknown">;
  mode_reason?: string | null;
}

export interface CheckResult {
  check_key: string;
  rule_id: string;
  status: CheckStatus;
  severity: Severity;
  message: string;
  subjects?: Subject[];
  measured?: number | string | boolean | null;
  limit?: number | string | boolean | null;
  unit?: string | null;
  fix_hint?: string | null;
  stage?: StageId;
  duration_ms?: number;
}

export interface Warning {
  warning_id: string;
  code: string;
  severity?: Severity;
  message: string;
  subjects?: Subject[];
  stage?: StageId;
}

export interface Scene {
  camera: { position_mm: Vec3; target_mm: Vec3; fov_deg?: number };
  assembly_bbox_mm: BBox;
  render?: AssetRef | null;
  preload?: string[];
}

export interface ErrorObject {
  code: string;
  message: string;
  retryable: boolean;
  stage?: StageId;
  subjects?: Subject[];
  details?: Record<string, unknown>;
}

export type BuildStatus = Open<"running" | "awaiting_input" | "done" | "failed" | "cancelled" | "unknown">;
export interface Build {
  build_id: string;
  prompt: string;
  status: BuildStatus;
  revision: number;
  created_at?: string;
  tier: Tier;
  spec?: Spec | null;
  design_id?: string | null;
  slots: Slot[];
  decisions?: Decision[];
  parts: BuildPart[];
  connections: Connection[];
  layouts?: Layout[];
  enclosures: Enclosure[];
  boards: Board[];
  firmware?: Firmware | null;
  checks: CheckResult[];
  warnings: Warning[];
  scene?: Scene | null;
  timings_ms?: Record<string, number>;
  error?: ErrorObject | null;
  last_seq: number;
  clarify?: ClarifyQuestion | null;
  clarifications?: ClarifyResolution[];
}

export interface DesignCard {
  design_id: string;
  name: string;
  summary?: string | null;
  device_class?: string;
  thumbnail_url?: string | null;
  repo_url?: string | null;
  licence_spdx?: string;
  commercial_ok?: TriState;
  key_specs?: KeySpec[];
}

// ---- Edit ops (client-only enums: closed) ----

export type EditOp =
  | { op: "swap_part"; instance_id: string; part_id: string }
  | { op: "connect"; from: PortRef; to: PortRef }
  | { op: "disconnect"; connection_id: string }
  | { op: "recolor"; instance_id?: string; enclosure_id?: string; color: Color }
  | {
      op: "move";
      instance_id: string;
      index?: number | null;
      position_mm?: Vec3;
      rotation_deg?: Vec3;
      mode: "absolute" | "delta";
      lock?: boolean;
    }
  | { op: "resize"; target: { enclosure_id?: string; board_id?: string }; params: Record<string, unknown> }
  | { op: "add_part"; part_id: string; slot_id?: string | null; quantity?: number; side?: Side }
  | { op: "remove_part"; instance_id: string };

export interface Suggestion {
  suggestion_id: string;
  kind: Open<"prompt" | "edit" | "design" | "unknown">;
  label: string;
  prompt?: string | null;
  ops?: EditOp[] | null;
  design_id?: string | null;
}

// ---- Envelopes ----

export interface BuildOptions {
  force_tier?: "exact" | "substitute" | "compose" | null;
  commercial_only?: boolean;
  seed?: number | null;
  mock_fixture?: string | null;
}

export interface ClientPayloads {
  "build.start": { prompt: string; options?: BuildOptions };
  "build.resume": { build_id: string; last_seq: number };
  "edit.apply": { build_id: string; base_revision?: number | null; ops: EditOp[] };
  "build.cancel": { build_id: string };
  ping: Record<string, never>;
  "clarify.answer": { build_id: string; question_id: string; option_id?: string; free_text?: string; skip?: true };
}
export type ClientType = keyof ClientPayloads;

export interface ClientEnvelope<T extends ClientType = ClientType> {
  spec_version: string;
  type: T;
  msg_id: string;
  ts?: string;
  payload: ClientPayloads[T];
}

export interface ServerEnvelope<P = Record<string, unknown>> {
  spec_version: string;
  type: string;
  seq: number;
  build_id: string | null;
  ts: string;
  stage?: StageId;
  revision?: number;
  cause?: { msg_id?: string; edit_id?: string };
  payload: P;
}

export interface ServerPayloads {
  hello: {
    server_version: string;
    session_id: string;
    mock?: boolean;
    limits?: { max_prompt_chars?: number; max_ops_per_edit?: number; msg_id_ttl_s?: number };
    capabilities?: string[];
  };
  ack: {
    msg_id: string;
    accepted: boolean;
    duplicate: boolean;
    build_id?: string | null;
    edit_id?: string | null;
    error?: ErrorObject | null;
  };
  pong: { msg_id: string; server_time?: string };
  error: { error: ErrorObject; msg_id?: string | null };
  "build.snapshot": { build: Build; reason: string };
  "stage.started": { stage: StageId; label?: string; budget_ms?: number };
  "stage.progress": { stage: StageId; message: string; fraction?: number | null };
  "stage.completed": {
    stage: StageId;
    status: Open<"ok" | "skipped" | "degraded" | "failed" | "needs_input" | "unknown">;
    duration_ms: number;
    message?: string | null;
  };
  "clarify.request": ClarifyQuestion;
  "clarify.resolved": ClarifyResolution;
  "spec.ready": { spec: Spec };
  "reuse.decided": {
    tier: Tier;
    design_id: string | null;
    design?: DesignCard | null;
    considered: { design_id: string; name: string; tier: Tier; score?: number | null; unmet?: string[] }[];
    unmet_hard: string[];
    reason: string;
  };
  "slots.ready": { slots: Slot[] };
  "slot.updated": { slot: Slot };
  "candidates.ready": {
    slot_id: string;
    step: number;
    filters: Filter[];
    count_before: number;
    count_after: number;
    survivors: Candidate[];
  };
  "decision.made": { decision: Decision };
  "decision.reverted": { decision_id: string; slot_id: string; reason: string };
  "layout.added": { layout: Layout };
  "part.added": { part: BuildPart };
  "part.updated": { part: BuildPart };
  "part.removed": { instance_id: string; reason?: string | null };
  "connection.added": { connection: Connection };
  "connection.removed": { connection_id: string; reason?: string | null };
  "placement.updated": {
    placements: { instance_id: string; placement: Placement }[];
    assembly_bbox_mm?: BBox;
    solver?: { status: string; duration_ms?: number };
  };
  "enclosure.updated": { enclosure: Enclosure };
  "board.updated": { board: Board };
  "firmware.ready": { firmware: Firmware };
  "firmware.progress": {
    firmware_id: string;
    phase: Open<"queued" | "fetching" | "compiling" | "linking" | "packaging" | "unknown">;
    fraction?: number | null;
    target_id?: string | null;
    message?: string | null;
  };
  "scene.ready": { scene: Scene };
  "check.result": { results: CheckResult[] };
  warning: { warning: Warning };
  "build.done": {
    summary: {
      part_count: number;
      instance_count: number;
      connection_count: number;
      warning_count?: number;
      checks: Record<string, number>;
    };
    timings_ms: Record<string, number>;
    total_ms?: number;
  };
  "build.failed": {
    error: ErrorObject;
    conflict?: {
      slot_id?: string;
      minimal_conflict?: Requirement[];
      explanation?: string;
      [key: string]: unknown;
    } | null;
    suggestions?: Suggestion[];
  };
  "edit.applied": { edit_id: string; msg_id: string; ops: EditOp[]; revision: number; duration_ms: number };
  "edit.rejected": {
    edit_id: string;
    msg_id: string;
    error: ErrorObject;
    failed_checks?: CheckResult[];
    suggestions?: Suggestion[];
  };
}
export type KnownServerType = keyof ServerPayloads;

export const CONNECTION_SCOPED = new Set(["hello", "ack", "pong", "error"]);

/** Narrow an envelope to a known type. */
export function isType<T extends KnownServerType>(
  env: ServerEnvelope<unknown>,
  type: T,
): env is ServerEnvelope<ServerPayloads[T]> {
  return env.type === type;
}

// ---- REST bodies ----

export interface VocabEntry {
  id: string;
  label: string;
  group?: string;
  description?: string;
  budget_ms?: number;
  severity?: Severity;
}
export interface Vocab {
  spec_version: string;
  functions: VocabEntry[];
  interface_types: VocabEntry[];
  device_classes: VocabEntry[];
  stages: VocabEntry[];
  check_rules: VocabEntry[];
  warning_codes: VocabEntry[];
  error_codes: VocabEntry[];
}
export interface Health {
  spec_version: string;
  status: string;
  server_version: string;
  mock?: boolean;
  llm?: { provider?: string; model?: string; status: string };
  llm_fallback?: { provider?: string; model?: string; status: string };
  part_count?: number;
  design_count?: number;
  uptime_s?: number;
}
export interface PartsPage {
  spec_version: string;
  items: PartCard[];
  next_cursor: string | null;
  total: number;
}
export interface Alternatives {
  spec_version: string;
  build_id: string;
  slot_id: string;
  instance_id?: string | null;
  current_part_id: string | null;
  items: {
    card: PartCard;
    compatible: boolean;
    failed_checks?: CheckResult[];
    deltas?: { label?: string; from?: unknown; to?: unknown }[];
  }[];
}
export interface ErrorResponse {
  spec_version: string;
  error: ErrorObject;
}

// ---- Fixtures ----

export type FixtureStep =
  | { dir: "client"; msg: ClientEnvelope }
  | { dir: "server"; delay_ms?: number; msg: ServerEnvelope };
export interface StreamFixture {
  fixture: string;
  spec_version: string;
  kind: "stream";
  description: string;
  match_prompts?: string[];
  requires_fixture?: string | null;
  steps: FixtureStep[];
}
export interface RestFixture {
  fixture: string;
  spec_version: string;
  kind: "rest";
  description: string;
  body_def?: string;
  request: { method: "GET" | "POST"; path: string; query?: Record<string, string>; body?: unknown };
  response: { status: number; body: Record<string, unknown> };
}
