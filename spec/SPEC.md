# Bara contract specification v1.1.1

Status: FROZEN at v1.1.0 (additive over v1.0.0). Owners: Pranav (backend, agent), Nithin (frontend, UI, 3D assets). Event: Cal Hacks 13.0, Oct 23 to 25 2026.

Product name: **Bara** (Hebrew, "to create", from Genesis 1:1). Decided by Pranav on 2026-10-18 (section 16).

Bara: a user types the device they want; the engine reuses an open design when one fits and otherwise engineers it from open-source parts, then shows every decision, part, case, board and firmware live.

## 0. About this document

This document is the contract between the backend and the frontend. If the frontend implements exactly what is written here, it works against the real backend and against mock mode without changes.

- The JSON Schema files in `spec/schemas/` (draft 2020-12) are the source of truth. Every table in sections 3 to 8 that lists fields was generated from those files. If this document and a schema disagree, the schema wins and this document has a bug.
- The fixtures in `spec/fixtures/` are complete, valid example sessions. Every one validates against the schemas in strict mode (section 15). Mock mode replays them (section 13).
- This document holds no implementation. Code, scripts and UI are written at the event.

Counts in v1.1.0: 18 schema files, 6 client message types, 35 server event types, 8 edit ops, 30 error codes, 29 check rules, 30 UI components, 8 stream fixtures, 12 REST fixtures.

## 1. Versioning and freeze policy

1. v1.1.0 is frozen. Both owners build against it for the whole event.
2. Every message (WebSocket, both directions) and every REST body carries `spec_version`. In v1.1 it is the string `"1.1.0"`. Every schema file carries `"x-spec-version": "1.1.0"`. Clients accept any 1.x.y.
3. Allowed without discussion (minor bump, 1.x.0): adding an optional field, adding a new event type, adding a new enum value, adding a new REST endpoint, adding a new check rule id or warning code. Additive changes must not change the meaning of an existing field.
4. Patch bump (1.0.x): description or documentation fixes, new fixtures. No shape change.
5. Breaking change (2.0.0): removing or renaming a field, making an optional field required, changing a type or unit, changing the meaning of a value, removing an enum value or event. A breaking change needs both owners to agree in writing and a major version bump. During the event the answer is no; find an additive route.
6. Clients ignore unknown fields at every level. The schemas are open (no `additionalProperties: false`) so a newer server still validates against an older client. Contract tests use a strict copy (section 15) to catch drift in our own code.
7. Clients ignore unknown event types (log them in C29 EventLog, change no state).
8. Every server-sent enum has the value `unknown`. A client that receives a value it does not know maps it to `unknown` and renders the neutral style for that enum. Client-only enums (edit op names, `Move.mode`, `BuildOptions.force_tier`, REST method) have no `unknown` value; the server rejects other values with `E_INVALID_EDIT` or `E_BAD_MESSAGE`.
9. The server rejects a message whose `spec_version` major is not 1 with `E_UNSUPPORTED_VERSION`. A newer minor or patch from the client is accepted.
10. Change process: edit the schema first, regenerate this document, rerun the contract tests, bump `spec_version` in the schemas and fixtures, and tell the other owner the exact change list.

### 1.1 Changelog

**1.1.1 (2026-10-19), documentation only.** No schema, field, event or fixture changes; `spec_version` on the wire stays `"1.1.0"`.

- Route derivation (section 8.12) rewritten from the held-out misses: deterministic stage 0 (catalog name match plus a top-3 design shortlist), the reuse check sees the shortlist instead of one design, `changes_needed` computed in code from card facets, reject wins over clarify when the request names a forbidden job, and a clear input-plus-output function set clears a blocking facet in code. Acceptance targets added.

**1.1.0 (2026-10-18), additive only.** Nothing was removed or renamed; every v1.0.0 message is still valid apart from the version string.

- Product name decided: Bara (replaces the `Bara` placeholder everywhere).
- Clarify flow (section 8.11): server event `clarify.request`, client message `clarify.answer`, server event `clarify.resolved`; `stage.completed.status` value `needs_input`; `Build.status` value `awaiting_input`; `Build.clarify` and `Build.clarifications`; Spec defs `ClarifyQuestion`, `ClarifyOption`, `ClarifyResolution`, `Assumption`; Spec fields `assumptions`, `scope`, `scope_reason`, `ambiguity`; `RequirementSource` values `clarified` and `assumed`; component C30 ClarifyCard; error codes `E_CLARIFY_NOT_PENDING`, `E_INVALID_ANSWER`, `E_OUT_OF_SCOPE`; warning code `assumption_made`; fixture `clarify_vague_gadget`.
- Enclosure policy: `Enclosure.material`, `Enclosure.color_source` (generated cases default to neutral gray `#9E9E9E`, no decoration); `Design.own_enclosure`; `AssetRef.origin`.
- Firmware policy: `Firmware.mode` (`prebuilt` or `compiled`) and `mode_reason`; server event `firmware.progress` for live compiles; `Design.prebuilt_firmware`.
- Board policy: `Board.routing.method` (`design` or `autorouted`), `cache_key`, `cache_hit`, `router`.
- Providers: Cerebras primary, Anthropic backup. `Spec.classifier.provider`, `Spec.classifier.fallback`, `Decision.model.fallback`, `Health.llm_fallback`.
- From the routing eval (calhacks-2026/eval/, 304 labeled prompts): `Spec.main_purpose`; `Spec.reuse` (`candidate_design_id`, `covers_main_purpose`, `changes_needed`, `verified`); `Spec.ambiguity.blocking_facet`; vocab `ClarifyFacet` (blocking and defaultable facets, `x-blocking`); vocab `FunctionId` annotation `x-search-terms` (library retrieval hints); route derivation rules (section 8.12); clarify criteria in section 8.11 replaced by the measured ones.

## 2. System overview

```
 Browser (Vite + React + React Three Fiber)                  Mac mini (FastAPI)
 +------------------------------------------+                +------------------------------------------------+
 |  PromptBar C02 ----- build.start ------->|--- WS /v1/ws ->| session: ack, seq, msg_id dedupe, event log    |
 |  Edit controls ----- edit.apply -------->|  (Cloudflare   |                                                |
 |  ConnectionBanner -- ping, build.resume >|  quick tunnel) |  pipeline, one build at a time per session:    |
 |                                          |                |                                                |
 |  store (reducer, section 9) <--- events -|<---------------|  0 classify   prompt -> Spec (rules, kNN, LLM) |
 |    |                                     |                |  1 reuse      Spec -> exact|substitute|compose |
 |    +-> StageTimeline, DecisionTrace,     |                |  2 compose    slots, filters, picks (Cerebras  |
 |        PartsList, Viewport3D, Checks...  |                |               enum C1..C8), constraint prop.   |
 |                                          |                |  3 place      CP-SAT poses                     |
 |  SwapDrawer, AddPartPicker, Inspector ---|---- REST ----->|  4 enclose    Manifold case                    |
 |    GET /v1/... (catalog, alternatives)   |                |  5 board      tscircuit or pre-routed board    |
 |                                          |                |  6 firmware   driver templates (+ async build) |
 |  Viewport3D loads /assets/*.glb ---------|---- HTTP ----->|  7 render     scene, camera, preload list      |
 |                                          |                |  8 edit       validate whole edit, then apply  |
 |  mock mode: fake socket replays          |                |                                                |
 |  spec/fixtures (section 13)              |                |  SQLite + FTS5 catalog, design library, assets |
 +------------------------------------------+                +------------------------------------------------+
```

Model providers: Cerebras is the primary (fast enum-constrained calls). Anthropic is the backup when Cerebras fails or times out: `claude-haiku-5-5` for the fast steps (classify, picks) and `claude-sonnet-5-5` only for a step that needs a stronger model. Every model call reports its provider (`Spec.classifier.provider`, `Decision.model.provider`) and whether the backup served it (`fallback`).

Classify may stop and ask: when a wrong guess would change the device, it ends with `needs_input` and the server sends `clarify.request` (section 8.11).

Policies by tier (v1.1):

| | exact | substitute | compose |
|---|---|---|---|
| Case | the design's own case (`Enclosure.kind design`, `color_source design`) | the design's own case | generated blank case, neutral gray `#9E9E9E`, no colours unless the user asks (`kind generated`, `color_source default` or `user`) |
| Board | the design's routed board (`routing.method design`) | the design's routed board | autorouted live (`routing.method autorouted`), cached by exact composition key (`routing.cache_key`) |
| Firmware | the design's prebuilt binary (`mode prebuilt`, compile skipped) | prebuilt, unless the swap changes the MCU or pin map, then compiled | compiled live (`mode compiled`, `firmware.progress` then a late `firmware.ready`) |

A compose build that keeps a design's board as its skeleton (for example the Corne PCB in `compose_wireless_split_oled`) keeps that board's routing (`method design`); firmware is compiled whenever the controller changed.

Transport is a WebSocket because Cloudflare quick tunnels do not support server-sent events. REST is used only for reads (catalog, designs, alternatives, replay, export) plus one fallback POST.

### 2.1 Stages

Stages run in the order below. At most one stage is open per build at any time. The `edit` stage runs once per accepted `edit.apply` after the build is done.

| # | StageId | UI label | Budget (ms, p95) | Runs for | Emits |
|---|---|---|---|---|---|
| 0 | `classify` | Understand | 50 | every build | spec.ready, or status needs_input followed by clarify.request (no stage open) |
| 1 | `reuse` | Find design | 30 | every build | reuse.decided, slots.ready |
| 2 | `compose` | Choose parts | 1500 | substitute and compose tiers (skipped for exact) | slot.updated, candidates.ready, decision.made, decision.reverted, part.added, layout.added, connection.added, check.result, warning |
| 3 | `place` | Place | 50 | every build | placement.updated, check.result |
| 4 | `enclose` | Case | 100 | every build | enclosure.updated, check.result |
| 5 | `board` | Board | 100 | every build | board.updated, check.result |
| 6 | `firmware` | Firmware | 50 | every build | firmware.ready, firmware.progress (compiled mode), check.result (fw.compile may arrive after build.done) |
| 7 | `render` | Scene | 50 | every build | scene.ready |
| 8 | `edit` | Edit | 50 | each edit.apply | part.*, connection.*, placement.updated, enclosure.updated, board.updated, layout.added, check.result, warning |

### 2.2 Tiers

The reuse stage decides the tier (`Tier` in common.schema.json):

- `exact`: one existing open design meets every hard requirement. Its parts, layout and case are used as they are. The compose stage is skipped (`stage.completed` with status `skipped`).
- `substitute`: one design is close; the compose stage fills only the slots whose design part fails a requirement.
- `compose`: no design is close enough. A design may still act as the skeleton (layout, case shape); every unmet slot is filled part by part.
- `unknown`: fallback for future tiers.

### 2.3 Lifecycle of one build

1. Client sends `build.start`. Server replies `ack` (seq 0) with the new `build_id`. If classify cannot build a useful spec without one more fact, it completes with status `needs_input` and the server sends `clarify.request` (section 8.11). The build waits (`status: awaiting_input`) until `clarify.resolved`, then classify starts again with the answer folded in. At most 2 rounds.
2. Server streams build-scoped events with seq 1, 2, 3, and so on: `stage.started`, the stage's own events, `stage.completed`, for each stage in order.
3. The build ends with exactly one terminal event: `build.done` (revision becomes 1) or `build.failed`.
4. After `build.done`, two kinds of events can still arrive: late firmware results (`firmware.progress`, `firmware.ready`, `check.result` for `fw.compile`) and edit events caused by `edit.apply`. After `build.failed` nothing more arrives for that build.

## 3. Conventions

### 3.1 Units

All quantities are SI style numbers with the unit in the field name suffix. No field mixes units.

| Suffix | Unit | Example |
|---|---|---|
| `_mm` | millimetre | `position_mm`, `wall_mm` |
| `_deg` | degree | `rotation_deg`, `r_deg` |
| `_v` | volt | `v_logic_v` |
| `_a` | ampere | `i_max_a` |
| `_w` | watt | |
| `_g` | gram | `mass_g` |
| `_hz` | hertz | `speed_max_hz` |
| `_ms` | millisecond | `duration_ms`, `budget_ms` |
| `_mah` | milliamp hour | `capacity_mah` |
| `_u` | keyboard unit (1u = 19.05 mm) | `x_u`, `w_u` |

Timestamps are RFC 3339 strings in UTC (`Timestamp`). Durations are integer milliseconds (`DurationMs`).

### 3.2 Coordinates

- Build space is right handed, Z up, units mm. The origin is the centre of the assembly footprint on the desk plane. +X is to the user's right, +Y is away from the user.
- `rotation_deg` is intrinsic Euler XYZ in degrees (three.js Euler order `XYZ`).
- GLB assets are authored in glTF convention: metres, Y up. The viewer converts each GLB once at load: scale by 1000, then rotate +90 deg about X. After that, an asset sits in build space at its part origin.
- `bbox_mm` is `{min: Vec3, max: Vec3}` in the part's own frame (before placement).
- Before the `place` stage completes, poses in `part.added` are provisional (taken from the source design or the placement intent). The viewer draws them at 50 percent opacity until `placement.updated` arrives or `stage.completed` for `place`.

### 3.3 Layout math (arrayed instances)

An instance with `quantity > 1` must use `placement.mode = "layout"` and reference a Layout already sent by `layout.added`. The Layout has one key per array element; element `i` of the instance sits at the key whose `i` equals that index, and the number of keys equals `quantity`. Single instances use `placement.mode = "single"`.

For key `k` with pitches `px = layout.pitch_x_mm` and `py = layout.pitch_y_mm` (both 19.05 for keyboards):

```
centre_local = ((k.x_u + k.w_u / 2) * px,  -(k.y_u + k.h_u / 2) * py,  0)
pivot        = (k.rx_u * px, -k.ry_u * py, 0)
centre       = rotate_z(centre_local - pivot, -k.r_deg) + pivot
world        = placement.position_mm + rotate_xyz(centre, placement.rotation_deg)
element yaw  = -k.r_deg (plus the placement rotation)
```

Y is negated because layout rows grow downward (KLE convention) while build space +Y points away from the user. `r_deg` is clockwise as seen from above, which is why it is negated for the right-handed Z rotation. `w_u` and `h_u` default to 1; `r_deg`, `rx_u`, `ry_u` default to 0. `matrix` is the electrical `[row, col]` of the key and is not used for drawing.

### 3.4 Identifiers

| Thing | Format | Example |
|---|---|---|
| build_id | `b_` + 8 to 32 of [A-Za-z0-9] | `b_exact001A` |
| instance_id | slug, unique within the build; by convention starts with `u_` | `u_sw_l` |
| connection_id | `c_` + slug | `c_oled_l_i2c` |
| enclosure_id | `e_` + slug | `e_case_l` |
| board_id | `pcb_` + slug | `pcb_l` |
| firmware_id | `fw_` + slug | `fw_1` |
| msg_id | client generated, 8 to 64 of [A-Za-z0-9_-], unique per session | `m_start_01` |
| part_id | catalog key, `prefix:name`, URL encode in paths | `mod:nice_nano_v2` |
| slot_id | slug | `controller` |
| check_key | `rule_id:subject` | `elec.i2c.address_clash:u_oled_l` |

The exact patterns are in the common defs table below.

### 3.5 Null, missing and unknown

- A field listed as required is always present. An optional field may be missing; treat missing as the documented default, or as "not known" when there is no default.
- `null` is only allowed where the type says `| null`. It means "known to be empty" (for example `chosen_part_id: null` for an optional slot left empty).
- `TriState` (`yes`, `no`, `unknown`) is used for facts about parts that the catalog may not know, such as `commercial_ok`.
- `unknown` in any enum: see section 1 item 8.

### 3.6 Common defs

Source: `common.schema.json`.

| Def | Type | Constraint | Notes |
|---|---|---|---|
| `SpecVersion` | string | pattern `^1\.[0-9]+\.[0-9]+$` | Semantic version of this spec. Clients accept any 1.x.y and reject other majors with E_UNSUPPORTED_VERSION. |
| `Id` | string | pattern `^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,199}$` | Generic stable identifier. Case sensitive. Part ids imported from Etch keep the Etch key verbatim (for example kicad:4xxx:14528@DIP-16_W10.16mm). URL-encode when used in a path. |
| `Slug` | string | pattern `^[a-z0-9][a-z0-9_.\-]{0,79}$` | Lowercase machine name. |
| `BuildId` | string | pattern `^b_[A-Za-z0-9]{8,32}$` |  |
| `InstanceId` | string | pattern `^[a-z][a-z0-9_]{0,63}$` | Part instance id, unique within one build. |
| `MsgId` | string | pattern `^[A-Za-z0-9_\-]{8,64}$` | Client generated message id (UUID v4 recommended). Used for idempotency. |
| `Timestamp` | string | format date-time | RFC 3339 UTC timestamp with milliseconds, for example 2026-10-24T18:02:11.120Z. |
| `DurationMs` | number | minimum 0 |  |
| `Vec2` | number[] | minItems 2 |  |
| `Vec3` | number[] | minItems 3 |  |
| `BBox` | object |  | Axis aligned box in mm. |
| `HexColor` | string | pattern `^#[0-9a-fA-F]{6}$` |  |
| `Material` | enum | `plastic`, `metal`, `pcb`, `rubber`, `glass`, `fabric`, `wood`, `unknown` |  |
| `Color` | object |  | hex, material, node, and an optional finish: `finish.preset` (matte, satin, gloss, silk, frosted, clear, smoke, metal, unknown), `finish.clarity` (0 to 1, how much light a see-through finish passes) and `finish.frost` (0 polished to 1 frosted). Cases use the finish for printable and cut materials, including see-through ones. |
| `StageId` | enum | `classify`, `reuse`, `compose`, `place`, `enclose`, `board`, `firmware`, `render`, `edit`, `unknown` |  |
| `Tier` | enum | `exact`, `substitute`, `compose`, `unknown` | exact: an open design satisfies every hard requirement and there are no soft ones. substitute: hard requirements met, soft ones applied as whitelisted transforms. compose: built from parts. |
| `Severity` | enum | `info`, `warning`, `error`, `critical`, `unknown` |  |
| `CheckStatus` | enum | `pass`, `fail`, `unknown` |  |
| `TriState` | enum | `yes`, `no`, `unknown` |  |
| `Side` | enum | `left`, `right`, `center`, `none`, `unknown` | Which half of a split device an instance belongs to. none for non-split devices. |
| `Criticality` | enum | `critical`, `optional`, `unknown` |  |
| `Origin` | enum | `design`, `compose`, `solver`, `user`, `unknown` | Who introduced an object into the build. |
| `PortRef` | object |  | One interface on one part instance. index selects one element of an arrayed instance (quantity > 1); null means the whole array, mapped element to element. |
| `Subject` | object |  | What a check, warning or error is about. All fields optional; the UI highlights whatever is present. |
| `KeySpec` | object |  | One short spec line on a part card, for example {label: Voltage, value: 3.3, unit: V}. |

## 4. Data model

Tables are generated from the schemas. Column Req: `yes` means required. Nested objects are expanded one level with dotted names; `[]` marks an array of objects. A Type naming another def (for example `PartCard`) refers to the table of that name in this section or in section 3.6.

### 4.1 Part

#### Part

Source: `part.schema.json`.

One sourced part. Strict superset of the Etch record in pcb-loop/engine/parts/kicad_library.json: every Etch field keeps its name and type (block 1). Block 2 adds what makes a part Lego shaped: functions, typed interfaces, ratings, mechanics, drivers, assets, structured licence. For Etch imported parts part_id equals key.

| Field | Type | Req | Notes |
|---|---|---|---|
| `key` | string |  | Etch: unique key, for example kicad:4xxx:14528@DIP-16_W10.16mm. |
| `lib_id` | string |  | Etch: KiCad symbol id. |
| `footprint` | string |  | Etch: KiCad footprint id, for example Package_DIP:DIP-16_W10.16mm. |
| `family` | string |  | Etch: library family. |
| `name` | string |  | Etch: symbol / footprint name. |
| `descr` | string |  | Etch: description. |
| `kw` | string |  | Etch: keywords. |
| `pins` | map<string, string> |  | Etch: pin number to pin name. |
| `pads_ok` | boolean |  | Etch. |
| `model` | string \| null |  | Etch: server local STEP path. Never sent to the browser as a URL; use assets. |
| `spice` | object |  | Etch. |
| `spice.prefix` | string |  |  |
| `spice.pins` | string[] |  |  |
| `spice.role` | string |  |  |
| `spice_note` | string |  | Etch. |
| `datasheet` | string |  | Etch: datasheet URL or empty string. |
| `source` | string |  | Etch: library source, for example kicad-lib or extra:sparkfun-kicad. |
| `tags` | string[] |  | Etch. |
| `fp_ok` | boolean |  | Etch. |
| `part_id` | Id | yes |  |
| `kind` | enum | yes | module: a ready board (breakout, dev board, display module). component: a bare electronic part. pcb: a whole board from an open design. mechanical: plate, keycap, case part. fastener: screws, standoffs, nuts. cable: wires and cables. Values: `module`, `component`, `pcb`, `mechanical`, `fastener`, `cable`, `other`, `unknown`. |
| `display_name` | string | yes | Short UI name, for example nice!nano v2. (max length 80) |
| `mpn` | string \| null |  |  |
| `manufacturer` | string \| null |  |  |
| `vendor_urls` | string[] |  |  |
| `summary` | string \| null |  | One line for the part card. (max length 200) |
| `functions` | object[] | yes | (min items 1) |
| `functions[].function_id` | FunctionId | yes |  |
| `functions[].primary` | boolean |  | Default `false`. |
| `functions[].params` | object |  |  |
| `interfaces` | Interface[] | yes |  |
| `electrical` | object |  |  |
| `electrical.v_in_min_v` | number |  |  |
| `electrical.v_in_max_v` | number |  |  |
| `electrical.v_logic_v` | number |  |  |
| `electrical.i_typ_a` | number |  | (min 0) |
| `electrical.i_max_a` | number |  | (min 0) |
| `electrical.i_sleep_a` | number |  | (min 0) |
| `mechanical` | object |  |  |
| `mechanical.bbox_mm` | BBox |  | In the part's local frame, which equals the GLB frame after the fixed asset transform. |
| `mechanical.mass_g` | number |  | (min 0) |
| `mechanical.standards` | string[] |  | Standard tags such as MX, Qwiic, M2.5, pro_micro, 2.54mm_header. |
| `mechanical.mating_features` | object[] |  |  |
| `mechanical.keepouts` | BBox[] |  | Volumes that must stay clear (antenna, connector mating space). |
| `drivers` | object[] |  | Per framework driver templates used by the firmware stage. |
| `drivers[].framework` | Framework | yes |  |
| `drivers[].library` | string | yes |  |
| `drivers[].version` | string \| null |  |  |
| `drivers[].include` | string \| null |  |  |
| `drivers[].class_name` | string \| null |  |  |
| `drivers[].init_snippet` | string \| null |  |  |
| `drivers[].loop_snippet` | string \| null |  |  |
| `drivers[].config_keys` | object |  | For config based firmware (QMK, ZMK, ESPHome): keys this part adds. |
| `render` | object |  |  |
| `render.default_color` | HexColor |  |  |
| `render.material` | Material |  |  |
| `render.recolorable_nodes` | string[] |  |  |
| `assets` | AssetRef[] |  |  |
| `licence` | Licence | yes |  |
| `provenance` | Provenance | yes |  |
| `facets` | map<string, string \| number \| boolean \| any[] \| null> |  | Flat facet record derived from the fields above, used for filtering. Keys are facet keys from GET /v1/facets. |
| `compatible_with` | object[] |  |  |
| `compatible_with[].part_id` | Id | yes |  |
| `compatible_with[].relation` | enum | yes | Values: `mates_with`, `drives`, `used_with`, `substitute_for`, `unknown`. |
| `compatible_with[].evidence` | string \| null |  | design_id or rule that established the edge. |
| `popularity` | object |  |  |
| `popularity.stars` | integer |  | (min 0) |
| `popularity.designs_using` | integer |  | (min 0) |
| `status` | enum |  | Values: `active`, `deprecated`, `unknown`. Default `"active"`. |

#### PartCard

Source: `part.schema.json#/$defs/PartCard`.

Compact part summary used in lists, candidates and the swap drawer.

| Field | Type | Req | Notes |
|---|---|---|---|
| `part_id` | Id | yes |  |
| `display_name` | string | yes |  |
| `kind` | enum | yes | Values: `module`, `component`, `pcb`, `mechanical`, `fastener`, `cable`, `other`, `unknown`. |
| `primary_function` | FunctionId |  |  |
| `summary` | string \| null |  |  |
| `key_specs` | KeySpec[] |  | (max items 6) |
| `thumbnail_url` | string \| null |  |  |
| `licence_spdx` | string |  |  |
| `commercial_ok` | TriState |  |  |
| `verified` | Verified |  |  |
| `source_url` | string \| null |  |  |

#### Framework

Source: `part.schema.json#/$defs/Framework`.

Values: `qmk`, `zmk`, `kmk`, `arduino`, `circuitpython`, `micropython`, `esphome`, `zephyr`, `esp_idf`, `other`, `unknown`.

### 4.2 Interface

#### Interface

Source: `interface.schema.json`.

A typed port on a part. params shape depends on type (see vocab.schema.json Params_<type>). Unknown params keys are ignored by clients.

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | string | yes | Unique within the part, for example i2c0, vin, sw_socket. (min length 1, max length 64) |
| `type` | InterfaceType | yes |  |
| `role` | Role | yes |  |
| `label` | string |  | Human label for the UI, for example Qwiic port A. (max length 60) |
| `params` | object | yes |  |
| `pins` | string[] |  | Pin numbers (keys of Part.pins) that carry this interface. Empty for mechanical interfaces. |
| `signals` | map<string, string> |  | Signal name to pin number, for example {SDA: '2', SCL: '3'}. |
| `optional` | boolean |  | true when a requires port may stay unconnected without failing slot.critical_filled. Default `false`. |
| `max_connections` | integer \| null |  | How many peers this port can take. null means limited only by type rules (I2C addresses, current budget). (min 1) |

Conditional rules: if {"properties":{"type":{"const":"power_in"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_power_in"}}}; if {"properties":{"type":{"const":"power_out"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_power_out"}}}; if {"properties":{"type":{"const":"gpio"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_gpio"}}}; if {"properties":{"type":{"const":"analog"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_analog"}}}; if {"properties":{"type":{"const":"i2c"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_i2c"}}}; if {"properties":{"type":{"const":"spi"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_spi"}}}; if {"properties":{"type":{"const":"uart"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_uart"}}}; if {"properties":{"type":{"const":"i2s"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_i2s"}}}; if {"properties":{"type":{"const":"usb"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_usb"}}}; if {"properties":{"type":{"const":"qwiic"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_qwiic"}}}; if {"properties":{"type":{"const":"radio"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_radio"}}}; if {"properties":{"type":{"const":"module_footprint"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_module_footprint"}}}; if {"properties":{"type":{"const":"switch_socket"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_switch_socket"}}}; if {"properties":{"type":{"const":"switch_stem"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_switch_stem"}}}; if {"properties":{"type":{"const":"plate_cutout"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_plate_cutout"}}}; if {"properties":{"type":{"const":"layout"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_layout"}}}; if {"properties":{"type":{"const":"stabilizer"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_stabilizer"}}}; if {"properties":{"type":{"const":"mounting_holes"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_mounting_holes"}}}; if {"properties":{"type":{"const":"fastener"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_fastener"}}}; if {"properties":{"type":{"const":"battery"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_battery"}}}; if {"properties":{"type":{"const":"addressable_led"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_addressable_led"}}}; if {"properties":{"type":{"const":"motor"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_motor"}}}; if {"properties":{"type":{"const":"jack"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_jack"}}}; if {"properties":{"type":{"const":"panel_access"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_panel_access"}}}; if {"properties":{"type":{"const":"other"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_other"}}}; if {"properties":{"type":{"const":"unknown"}},"required":["type"]} then {"properties":{"params":{"$ref":"vocab.schema.json#/$defs/Params_unknown"}}}

### 4.3 Licence and provenance

#### Licence

Source: `provenance.schema.json#/$defs/Licence`.

Licence of one part or design, stored per part (not per project).

| Field | Type | Req | Notes |
|---|---|---|---|
| `spdx` | string | yes | SPDX id, NOASSERTION, or LicenseRef-<name>. |
| `name` | string |  |  |
| `url` | string \| null |  | (format uri) |
| `commercial_ok` | TriState | yes |  |
| `copyleft` | TriState |  |  |
| `attribution_required` | TriState |  |  |
| `attribution` | string \| null |  | Exact attribution text to show in the BOM and export. |
| `notes` | string \| null |  |  |

#### Extractor

Source: `provenance.schema.json#/$defs/Extractor`.

Values: `kicad_parse`, `occ_geometry`, `fritzing`, `qmk_info`, `datasheet`, `llm`, `human`, `design_import`, `unknown`.

#### Verified

Source: `provenance.schema.json#/$defs/Verified`.

geometry: checked against STEP or footprint geometry. human: checked by a person. datasheet: copied from an official datasheet. third_party: from a non official source; shown as a warning. none: unchecked.

Values: `geometry`, `human`, `datasheet`, `third_party`, `none`, `unknown`.

#### FieldSource

Source: `provenance.schema.json#/$defs/FieldSource`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `extractor` | Extractor | yes |  |
| `verified` | Verified | yes |  |
| `confidence` | number |  | (min 0, max 1) |
| `source_url` | string \| null |  |  |

#### Provenance

Source: `provenance.schema.json#/$defs/Provenance`.

Superset of the Etch provenance record. The first block of fields is Etch's, unchanged; the second block is new.

| Field | Type | Req | Notes |
|---|---|---|---|
| `route` | string |  | Etch: how the record entered the library. |
| `licence` | string |  | Etch: free text licence line. The structured licence is Part.licence. |
| `copyleft` | boolean |  | Etch. |
| `symbol_url` | string |  | Etch. |
| `source_url` | string |  | Etch. |
| `model_url` | string |  | Etch. |
| `version` | string |  | Etch. |
| `url` | string |  | Etch. |
| `commit` | string |  | Etch. |
| `licence_flag` | string \| boolean \| null |  | Etch. |
| `attribution` | string \| null |  | Etch. |
| `attribution_required` | boolean \| null |  | Etch. |
| `model_note` | string |  | Etch. |
| `symbol` | string |  | Etch. |
| `extractor` | Extractor |  |  |
| `verified` | Verified |  |  |
| `confidence` | number |  | (min 0, max 1) |
| `dims_source_url` | string \| null |  |  |
| `sha256` | string \| null |  | (pattern `^[0-9a-f]{64}$`) |
| `retrieved_at` | Timestamp |  |  |
| `field_sources` | map<string, FieldSource> |  | Per field provenance keyed by a JSON pointer into the part, for example /mechanical/bbox_mm. Geometry derived numbers must never be overwritten by llm values. |

### 4.4 AssetRef

#### AssetRef

Source: `asset.schema.json`.

Reference to a static file served by the backend under /assets/. Paths are content addressed and immutable, so the client may cache forever. GLB files are standard glTF 2.0 (meters, Y up); the viewer maps them to build space with one fixed transform: scale 1000, rotate +90 deg about X.

| Field | Type | Req | Notes |
|---|---|---|---|
| `asset_id` | string | yes | (min length 1, max length 128) |
| `kind` | enum | yes | Values: `glb`, `png`, `svg`, `stl`, `3mf`, `step`, `kicad_pcb`, `gerber_zip`, `firmware_src_zip`, `firmware_bin`, `uf2`, `bom_csv`, `log`, `zip`, `json`, `unknown`. |
| `role` | enum |  | What the file is for. model is the full detail GLB, model_lod1 the decimated one, thumbnail a square PNG (256 px), render a large PNG placeholder of the assembled object. Values: `model`, `model_lod1`, `thumbnail`, `render`, `export`, `source`, `binary`, `log`, `unknown`. |
| `url` | string | yes | Path relative to the server origin, beginning with /assets/, for example /assets/parts/3f9a2c/model.glb. Absolute https URLs are allowed for mock mode. (pattern `^(/assets/|https://)`) |
| `content_type` | string |  |  |
| `bytes` | integer |  | (min 0) |
| `sha256` | string \| null |  | (pattern `^[0-9a-f]{64}$`) |
| `status` | enum |  | ready: fetchable now. pending: will be produced; a later event carries the ready ref. missing: will not exist; show the placeholder. Values: `ready`, `pending`, `missing`, `unknown`. Default `"ready"`. |
| `nodes` | string[] |  | GLB node names that are addressable (for recolor and highlight). |
| `origin` | enum |  | design: a file from the open design repo. generated: produced by this build (case, autorouted board, compiled binary). catalog: a part library file. Values: `design`, `generated`, `catalog`, `unknown`. |

### 4.5 Spec

#### Spec

Source: `spec.schema.json`.

Output of the classify stage: what the user asked for, as a taxonomy path, a function list and typed requirements. Requirements use facet keys and values from GET /v1/facets only; free text that maps to no facet stays in leftover_text and only influences ranking.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_id` | string | yes |  |
| `prompt` | string | yes | (max length 2000) |
| `normalized_prompt` | string |  |  |
| `device_class` | DeviceClass | yes |  |
| `taxonomy_path` | Slug[] | yes | device class > form > subsystem, as slugs. The first element equals device_class. (min items 1) |
| `functions` | object[] | yes |  |
| `functions[].function_id` | FunctionId | yes |  |
| `functions[].required` | boolean | yes | true: the device must have it (becomes a critical slot). false: nice to have (optional slot). |
| `functions[].count` | integer |  | (min 1) Default `1`. |
| `functions[].source` | RequirementSource |  |  |
| `hard_requirements` | Requirement[] | yes |  |
| `soft_requirements` | Requirement[] | yes |  |
| `leftover_text` | string \| null |  | Words that matched no facet. |
| `classifier` | object | yes |  |
| `classifier.stage` | enum | yes | Which cascade step decided. Values: `rules`, `knn`, `llm`, `cache`, `unknown`. |
| `classifier.confidence` | number | yes | (min 0, max 1) |
| `classifier.margin` | number \| null |  | Top 1 minus top 2 score. |
| `classifier.model` | string \| null |  |  |
| `classifier.latency_ms` | DurationMs |  |  |
| `classifier.provider` | string \| null |  | LLM provider that served the call: cerebras (primary), anthropic (backup), openai (offline evaluation only). |
| `classifier.fallback` | boolean |  | true when the backup provider answered because the primary failed or timed out. |
| `scope` | enum |  | out_of_scope: the request cannot be built from electronics and printable parts (the build then fails with E_OUT_OF_SCOPE). Values: `in_scope`, `out_of_scope`, `unknown`. |
| `scope_reason` | string \| null |  | (max length 300) |
| `assumptions` | Assumption[] |  | Facts the engine assumed instead of asking, shown to the user as editable chips. |
| `ambiguity` | object |  | Classifier output that drives the clarify flow (SPEC.md section 8.11). |
| `ambiguity.needs_clarify` | boolean | yes |  |
| `ambiguity.missing_facets` | Slug[] |  | Every facet left open, as ClarifyFacet values (blocking and defaultable). |
| `ambiguity.blocking_facet` | ClarifyFacet \| null |  | The one blocking facet to ask about, or null. needs_clarify is true exactly when this is set, unless a catalog design that does the same job identifies the device (then it is cleared). |
| `main_purpose` | string \| null |  | The device's core job in one sentence, without the user's tweaks (wireless, battery, colour, extra buttons, size). The reuse test compares this with each candidate design's own job. |
| `reuse` | object |  | Reuse test that decides the tier (SPEC.md section 8.12). exact: covers_main_purpose and no changes_needed. substitute: covers_main_purpose with changes_needed. compose: no candidate covers the main purpose. |
| `reuse.candidate_design_id` | Id \| null | yes |  |
| `reuse.covers_main_purpose` | boolean | yes | True only when the candidate is the same kind of device doing the same core job. Shared parts (buttons, a screen, LEDs, a sensor) are not enough; a firmware-only design does not cover a request for hardware. |
| `reuse.changes_needed` | string[] | yes | Concrete part changes for stated requirements the candidate's default build does not meet. |
| `reuse.verified` | boolean | yes | True when a second, single-design check confirmed the reuse decision. |

#### RequirementSource

Source: `spec.schema.json#/$defs/RequirementSource`.

explicit: stated in the prompt. implicit: implied by another requirement (wireless implies battery). default: taken from the device class default. clarified: from the user's answer to a clarify question. assumed: the engine's best guess after a skipped or timed out clarify question (also listed in assumptions).

Values: `explicit`, `implicit`, `default`, `clarified`, `assumed`, `unknown`.

#### Requirement

Source: `spec.schema.json#/$defs/Requirement`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `req_id` | string | yes |  |
| `facet` | Slug | yes |  |
| `op` | enum | yes | Values: `eq`, `neq`, `in`, `lte`, `gte`, `range`, `has`, `unknown`. |
| `value` | any | yes | Scalar for eq/neq/lte/gte/has, array for in, [min, max] for range. |
| `unit` | string \| null |  |  |
| `source` | RequirementSource |  |  |
| `text_span` | integer[] \| null |  | [start, end) character offsets into prompt, for highlighting. (min items 2, max items 2) |
| `label` | string |  | Human chip text, for example Wireless (BLE). |

#### Assumption

Source: `spec.schema.json#/$defs/Assumption`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `assumption_id` | string | yes | (pattern `^as_[a-z0-9_]{1,31}$`) |
| `facet` | Slug | yes |  |
| `value` | string \| number \| boolean | yes |  |
| `label` | string | yes | (max length 80) |
| `reason` | string \| null |  | (max length 200) |

#### ClarifyQuestion

Source: `spec.schema.json#/$defs/ClarifyQuestion`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `question_id` | string | yes | (pattern `^q_[a-z0-9_]{1,31}$`) |
| `question` | string | yes | (max length 200) |
| `options` | ClarifyOption[] | yes | (min items 2, max items 4) |
| `allow_free_text` | boolean | yes |  |
| `allow_skip` | boolean |  | true: the card shows Just pick, which resolves as skipped with the default option. Default `true`. |
| `default_option_id` | string \| null |  | Best guess used on skip or timeout. |
| `reason` | string | yes | Why the engine is asking instead of guessing. (max length 200) |
| `missing_facets` | Slug[] | yes | (min items 1) |
| `timeout_ms` | integer |  | After this long with no answer the server resolves with timeout. (min 0) Default `60000`. |
| `round` | integer | yes | (min 1, max 2) |

#### ClarifyOption

Source: `spec.schema.json#/$defs/ClarifyOption`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `option_id` | string | yes | (pattern `^o_[a-z0-9_]{1,31}$`) |
| `label` | string | yes | (max length 80) |
| `description` | string \| null |  | (max length 200) |
| `implies` | Requirement[] |  | Requirements added to the spec if this option is picked. |

#### ClarifyResolution

Source: `spec.schema.json#/$defs/ClarifyResolution`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `question_id` | string | yes | (pattern `^q_[a-z0-9_]{1,31}$`) |
| `resolution` | enum | yes | Values: `answered_option`, `answered_text`, `skipped`, `timeout`, `unknown`. |
| `option_id` | string \| null |  |  |
| `free_text` | string \| null |  | (max length 300) |
| `assumptions` | Assumption[] | yes | Filled on skipped and timeout: what the engine picked in the user's place. |

### 4.6 Slots, candidates and decisions

#### SlotState

Source: `slot.schema.json#/$defs/SlotState`.

pending: not yet considered. narrowing: filters are being applied. decided: a part is chosen. none: optional slot left empty on purpose. dead_end: zero survivors (critical: build fails unless backtracking finds a way).

Values: `pending`, `narrowing`, `decided`, `none`, `dead_end`, `unknown`.

#### Slot

Source: `slot.schema.json#/$defs/Slot`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `slot_id` | string | yes | (pattern `^[a-z][a-z0-9_]{0,63}$`) |
| `label` | string | yes | (max length 40) |
| `function_id` | FunctionId | yes |  |
| `criticality` | Criticality | yes |  |
| `quantity` | integer |  | (min 1) Default `1`. |
| `side` | Side |  |  |
| `order` | integer \| null |  | Decision order. 0 is decided first (most constraining). (min 0) |
| `state` | SlotState | yes |  |
| `candidates_total` | integer \| null |  | Parts matching the slot function before any filter. (min 0) |
| `candidates_left` | integer \| null |  | (min 0) |
| `chosen_part_id` | string \| null |  |  |
| `instance_ids` | InstanceId[] |  | Instances that fill this slot once decided. |
| `from_design` | boolean |  | true when the slot was filled from the reused or skeleton design. Default `false`. |

#### Filter

Source: `slot.schema.json#/$defs/Filter`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `facet` | Slug | yes |  |
| `op` | enum | yes | Values: `eq`, `neq`, `in`, `lte`, `gte`, `range`, `has`, `unknown`. |
| `value` | any | yes |  |
| `reason` | enum | yes | requirement: from the Spec. propagated: implied by an earlier pick. compatibility: needed to mate with an already chosen part. licence: commercial_only option. relaxed: a soft filter that was dropped (count_after then grows). Values: `requirement`, `propagated`, `compatibility`, `licence`, `relaxed`, `unknown`. |
| `from_slot_id` | string \| null |  | For propagated and compatibility filters: the slot whose pick caused it. |
| `req_id` | string \| null |  |  |
| `count_before` | integer |  | (min 0) |
| `count_after` | integer |  | (min 0) |
| `label` | string |  | Chip text, for example Pro Micro footprint. |

#### Candidate

Source: `slot.schema.json#/$defs/Candidate`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `short_id` | string | yes | C1..C8, the enum value the model answers with. (pattern `^C[0-9]{1,2}$`) |
| `card` | PartCard | yes |  |
| `score` | number \| null |  |  |
| `is_default` | boolean |  | Default `false`. |

#### Decision

Source: `slot.schema.json#/$defs/Decision`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `decision_id` | string | yes |  |
| `slot_id` | string | yes |  |
| `step` | integer |  | (min 0) |
| `method` | enum | yes | design: taken from the reused or skeleton design. only_survivor: one candidate left. default: a clear default (popularity prior), no model call. model_pick: the LLM picked among survivors by enum. solver: CP-SAT repair chose it. user: an edit. none: optional slot left empty. Values: `design`, `only_survivor`, `default`, `model_pick`, `solver`, `user`, `none`, `unknown`. |
| `chosen_part_id` | string \| null | yes | null when method is none. |
| `chosen_short_id` | string \| null |  |  |
| `survivors` | integer |  | (min 0) |
| `reason` | string | yes | (max length 240) |
| `model` | object \| null |  |  |
| `model.provider` | string |  | LLM provider that served the call: cerebras (primary), anthropic (backup), openai (offline evaluation only). |
| `model.model` | string |  |  |
| `model.latency_ms` | DurationMs |  |  |
| `model.cached` | boolean |  |  |
| `model.fallback` | boolean |  | true when the backup provider answered. |
| `propagated` | object[] |  | Effect of this pick on other slots. |
| `propagated[].slot_id` | string | yes |  |
| `propagated[].count_before` | integer | yes | (min 0) |
| `propagated[].count_after` | integer | yes | (min 0) |
| `propagated[].constraint` | string |  | Short human text, for example needs a 3.7 V LiPo. |

### 4.7 Build

#### Build

Source: `build.schema.json#/$defs/Build`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `build_id` | BuildId | yes |  |
| `prompt` | string | yes |  |
| `status` | enum | yes | awaiting_input: a clarify.request is open and the build waits for clarify.answer (see clarify). Values: `running`, `awaiting_input`, `done`, `failed`, `cancelled`, `unknown`. |
| `revision` | integer | yes | 0 while the build runs. build.done sets 1. Each edit.applied adds 1. Late firmware.ready and check.result events never change it. (min 0) |
| `created_at` | Timestamp |  |  |
| `tier` | Tier | yes |  |
| `spec` | Spec \| null |  |  |
| `design_id` | string \| null |  | Reused design (exact, substitute) or skeleton design (compose). |
| `slots` | Slot[] | yes |  |
| `decisions` | Decision[] |  |  |
| `parts` | BuildPart[] | yes |  |
| `connections` | Connection[] | yes |  |
| `layouts` | Layout[] |  |  |
| `enclosures` | Enclosure[] | yes |  |
| `boards` | Board[] | yes |  |
| `firmware` | Firmware \| null |  |  |
| `checks` | CheckResult[] | yes |  |
| `warnings` | Warning[] | yes |  |
| `scene` | Scene \| null |  |  |
| `timings_ms` | map<string, DurationMs> |  | Stage id to wall time in ms. |
| `error` | ErrorObject \| null |  |  |
| `last_seq` | integer | yes | seq of the last event folded into this snapshot. (min 0) |
| `clarify` | ClarifyQuestion \| null |  | The open clarify question while status is awaiting_input, else null. |
| `clarifications` | ClarifyResolution[] |  | Every resolved clarify round, oldest first. |

#### Placement

Source: `build.schema.json#/$defs/Placement`.

Pose of an instance in build space. rotation_deg is intrinsic Euler XYZ in degrees (three.js order XYZ). mode layout: the pose is the layout origin and each array element sits at its key position (SPEC.md 3.3).

| Field | Type | Req | Notes |
|---|---|---|---|
| `mode` | enum | yes | Values: `single`, `layout`, `unknown`. |
| `position_mm` | Vec3 | yes |  |
| `rotation_deg` | Vec3 | yes |  |
| `layout_id` | string \| null |  |  |
| `explode_offset_mm` | Vec3 |  | Offset at explode factor 1.0. The viewer adds factor * offset. |
| `source` | enum |  | Values: `design`, `solver`, `intent`, `user`, `unknown`. |
| `locked` | boolean |  | true after a user move: the solver keeps this pose fixed. Default `false`. |
| `intent` | PlacementIntent \| null |  |  |

#### PlacementIntent

Source: `build.schema.json#/$defs/PlacementIntent`.

What the agent wants; the CP-SAT solver turns it into exact coordinates.

| Field | Type | Req | Notes |
|---|---|---|---|
| `region` | enum |  | Values: `top`, `bottom`, `left`, `right`, `front`, `back`, `center`, `any`, `unknown`. |
| `near_instance_id` | string \| null |  |  |
| `face_wall` | Face |  |  |
| `layer` | integer \| null |  | Stack order from the base, 0 = bottom. |
| `note` | string \| null |  |  |

#### Layout

Source: `build.schema.json#/$defs/Layout`.

Key positions in key units, KLE / QMK info.json convention (x right, y down, origin top left).

| Field | Type | Req | Notes |
|---|---|---|---|
| `layout_id` | string | yes |  |
| `name` | string |  |  |
| `pitch_x_mm` | number | yes | (>  0) |
| `pitch_y_mm` | number | yes | (>  0) |
| `keys` | object[] | yes |  |
| `keys[].i` | integer | yes | Array index; equals PortRef.index and the element index of arrayed instances. (min 0) |
| `keys[].x_u` | number | yes |  |
| `keys[].y_u` | number | yes |  |
| `keys[].w_u` | number |  | Default `1`. |
| `keys[].h_u` | number |  | Default `1`. |
| `keys[].r_deg` | number |  | Default `0`. |
| `keys[].rx_u` | number |  | Default `0`. |
| `keys[].ry_u` | number |  | Default `0`. |
| `keys[].matrix` | integer[] |  | (min items 2, max items 2) |

#### BuildPart

Source: `build.schema.json#/$defs/BuildPart`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `instance_id` | InstanceId | yes |  |
| `part_id` | Id | yes |  |
| `slot_id` | string \| null |  |  |
| `label` | string |  | (max length 60) |
| `quantity` | integer | yes | Number of physical copies. quantity > 1 requires placement.mode layout with that many keys. (min 1) |
| `side` | Side |  |  |
| `color` | Color \| null |  | null: use Part.render.default_color. |
| `placement` | Placement | yes |  |
| `card` | PartCard | yes |  |
| `assets` | AssetRef[] |  |  |
| `origin` | Origin |  |  |
| `status` | enum |  | Values: `ok`, `warning`, `failed`, `unknown`. Default `"ok"`. |

#### Connection

Source: `build.schema.json#/$defs/Connection`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `connection_id` | string | yes | (pattern `^c_[a-z0-9_]{1,63}$`) |
| `type` | InterfaceType | yes |  |
| `kind` | enum | yes | Values: `electrical`, `mechanical`, `wireless`, `unknown`. |
| `from` | PortRef | yes | The provides side. |
| `to` | PortRef | yes | The requires side. |
| `via_instance_id` | string \| null |  | Cable, fastener or adapter instance that physically carries the connection. |
| `nets` | object[] |  |  |
| `nets[].signal` | string | yes |  |
| `nets[].from_pin` | string \| null |  |  |
| `nets[].to_pin` | string \| null |  |  |
| `resolved` | object |  | Parameters fixed by the connection, for example {address: 60} or {rail: 3v3}. |
| `label` | string |  |  |
| `origin` | Origin |  |  |
| `status` | enum |  | Values: `ok`, `warning`, `failed`, `unknown`. Default `"ok"`. |

#### Cutout

Source: `build.schema.json#/$defs/Cutout`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `cutout_id` | string | yes |  |
| `for` | PortRef \| null |  |  |
| `feature` | string |  |  |
| `face` | Face | yes |  |
| `shape` | enum | yes | Values: `rect`, `circle`, `slot`, `unknown`. |
| `center_mm` | Vec3 | yes |  |
| `size_mm` | Vec2 | yes |  |

#### Enclosure

Source: `build.schema.json#/$defs/Enclosure`.

The one generated object. design: the open design's own case, unchanged. generated: Manifold shell minus cutouts, computed from the parts. none: no enclosure.

| Field | Type | Req | Notes |
|---|---|---|---|
| `enclosure_id` | string | yes | (pattern `^e_[a-z0-9_]{1,63}$`) |
| `kind` | enum | yes | design: the open design's own case, kept unchanged (exact and substitute tiers). generated: a blank parametric case (compose tier). none: no case. Values: `generated`, `design`, `none`, `unknown`. |
| `side` | Side |  |  |
| `for_instance_ids` | InstanceId[] |  |  |
| `params` | object | yes |  |
| `params.wall_mm` | number |  | (min 0.8, max 10) |
| `params.floor_mm` | number |  | (min 0.8, max 10) |
| `params.fillet_mm` | number |  | (min 0, max 20) |
| `params.clearance_mm` | number |  | (min 0, max 10) |
| `params.height_mm` | number \| null |  | null: fit to contents. (min 1) |
| `params.split` | enum |  | Values: `none`, `lid_top`, `tray`, `halves`, `unknown`. |
| `params.standoff_height_mm` | number |  | (min 0) |
| `params.screw` | Screw |  |  |
| `outer_size_mm` | Vec3 |  |  |
| `position_mm` | Vec3 |  |  |
| `rotation_deg` | Vec3 |  |  |
| `explode_offset_mm` | Vec3 |  |  |
| `cutouts` | Cutout[] |  |  |
| `color` | Color \| null |  |  |
| `assets` | AssetRef[] |  |  |
| `status` | enum | yes | Values: `pending`, `ok`, `failed`, `unknown`. |
| `duration_ms` | DurationMs |  |  |
| `revision` | integer | yes | Increments on every rebuild of this enclosure. (min 0) |
| `material` | Material |  | Render material of the case. Default `"plastic"`. |
| `color_source` | enum |  | default: neutral gray #9E9E9E, no decoration (every generated case unless the user asked for a colour). user: the user asked for this colour in the prompt or an edit. design: colour taken from the open design. Values: `default`, `user`, `design`, `unknown`. Default `"default"`. |

#### Net

Source: `build.schema.json#/$defs/Net`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `name` | string | yes |  |
| `kind` | enum |  | Values: `power`, `ground`, `signal`, `unknown`. |
| `members` | object[] | yes |  |
| `members[].instance_id` | InstanceId | yes |  |
| `members[].pin` | string | yes |  |
| `members[].index` | integer \| null |  | (min 0) |

#### Board

Source: `build.schema.json#/$defs/Board`.

A PCB. When part_instance_id is set, the board is also a BuildPart (from a design) and the viewport renders that part; the board view uses this record. When null, the viewport renders this record's own model asset.

| Field | Type | Req | Notes |
|---|---|---|---|
| `board_id` | string | yes | (pattern `^pcb_[a-z0-9_]{1,63}$`) |
| `source` | enum | yes | Values: `design`, `prerouted`, `tscircuit`, `none`, `unknown`. |
| `side` | Side |  |  |
| `part_instance_id` | string \| null |  |  |
| `for_instance_ids` | InstanceId[] |  | Instances mounted on or wired through this board. |
| `outline_mm` | Vec2[] |  |  |
| `size_mm` | Vec2 |  |  |
| `thickness_mm` | number |  | (min 0) |
| `layers` | integer |  | (min 1) |
| `position_mm` | Vec3 |  |  |
| `rotation_deg` | Vec3 |  |  |
| `nets` | Net[] |  |  |
| `footprints` | object[] |  | Footprints on the board in build space. The viewport draws them on the placeholder board before the model exists, and names what the pointer hovers. A board is sent with status pending and its footprints as soon as it is laid out, before routing. |
| `footprints[].ref` | string | yes | KiCad reference designator, e.g. SW3. Matches the footprint's node name in the board GLB. |
| `footprints[].label` | string \| null |  |  |
| `footprints[].role` | string \| null |  |  |
| `footprints[].lib_id` | string \| null |  | KiCad footprint id, e.g. Diode_SMD:D_SOD-123. |
| `footprints[].instance_id` | InstanceId \| null |  | The BuildPart this footprint mounts, when there is one. |
| `footprints[].center_mm` | Vec2 |  | Courtyard centre. |
| `footprints[].size_mm` | Vec2 |  | Courtyard size before rotation. |
| `footprints[].rot_deg` | number |  |  |
| `routing` | object |  |  |
| `routing.status` | enum |  | Values: `routed`, `partial`, `unrouted`, `skipped`, `unknown`. |
| `routing.unrouted_nets` | string[] |  |  |
| `routing.duration_ms` | DurationMs |  |  |
| `routing.method` | enum |  | design: the reused design's own routed board, loaded as is. autorouted: a new composition routed live by the autorouter. none: no board to route. Values: `design`, `autorouted`, `none`, `unknown`. |
| `routing.cache_key` | string \| null |  | Exact composition key (hash of sorted part ids, connections and board outline). Autorouted results are cached under it; null for design boards. |
| `routing.cache_hit` | boolean |  | true when an autorouted result came from the cache. |
| `routing.router` | string \| null |  | Autorouter that produced the result, e.g. freerouting or tscircuit. null for design boards. |
| `drc` | CheckStatus |  |  |
| `assets` | AssetRef[] |  |  |
| `status` | enum | yes | Values: `pending`, `ok`, `failed`, `unknown`. |
| `revision` | integer | yes | (min 0) |

#### Firmware

Source: `build.schema.json#/$defs/Firmware`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `firmware_id` | string | yes | (pattern `^fw_[a-z0-9_]{1,63}$`) |
| `framework` | Framework | yes |  |
| `origin` | enum |  | design: the open design's own firmware (keymap or config). template: filled from per part driver templates. Values: `design`, `template`, `unknown`. |
| `targets` | object[] |  |  |
| `targets[].target_id` | string | yes |  |
| `targets[].mcu_instance_id` | InstanceId | yes |  |
| `targets[].side` | Side |  |  |
| `targets[].label` | string |  |  |
| `files` | object[] | yes |  |
| `files[].path` | string | yes | Relative path, forward slashes, no .. segments. |
| `files[].language` | enum | yes | Values: `c`, `cpp`, `python`, `yaml`, `devicetree`, `keymap`, `json`, `kconfig`, `text`, `unknown`. |
| `files[].content` | string \| null |  | Inline text up to 256 KiB; otherwise null and asset is set. (max length 262144) |
| `files[].asset` | AssetRef \| null |  |  |
| `files[].bytes` | integer |  | (min 0) |
| `drivers` | object[] |  |  |
| `drivers[].part_id` | Id | yes |  |
| `drivers[].library` | string | yes |  |
| `drivers[].version` | string \| null |  |  |
| `drivers[].include` | string \| null |  |  |
| `pin_map` | object[] |  |  |
| `pin_map[].instance_id` | InstanceId | yes |  |
| `pin_map[].interface_id` | string \| null |  |  |
| `pin_map[].signal` | string | yes |  |
| `pin_map[].mcu_instance_id` | InstanceId | yes |  |
| `pin_map[].mcu_pin` | string | yes |  |
| `compile` | object | yes |  |
| `compile.status` | enum | yes | Values: `pending`, `running`, `ok`, `failed`, `skipped`, `unknown`. |
| `compile.duration_ms` | DurationMs |  |  |
| `compile.binaries` | AssetRef[] |  |  |
| `compile.log` | AssetRef \| null |  |  |
| `compile.message` | string \| null |  |  |
| `revision` | integer | yes | (min 0) |
| `mode` | enum |  | prebuilt: the known design's own binary, served as is, compile.status skipped. compiled: generated source compiled live (only when routing sends the build there: compose tier, or a substitute that changes the MCU or pin map). Values: `prebuilt`, `compiled`, `unknown`. |
| `mode_reason` | string \| null |  | One line on why this mode was chosen. (max length 200) |

#### Warning

Source: `build.schema.json#/$defs/Warning`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `warning_id` | string | yes |  |
| `code` | enum | yes | Values: `optional_part_missing`, `licence_unknown`, `licence_noncommercial`, `dims_third_party`, `data_unverified`, `constraint_relaxed`, `substitute_used`, `llm_fallback`, `llm_degraded`, `slow_stage`, `asset_missing`, `compile_skipped`, `assumption_made`, `other`, `unknown`. |
| `severity` | Severity |  |  |
| `message` | string | yes | (max length 300) |
| `subjects` | Subject[] |  |  |
| `stage` | StageId |  |  |

#### Scene

Source: `build.schema.json#/$defs/Scene`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `camera` | object | yes |  |
| `camera.position_mm` | Vec3 | yes |  |
| `camera.target_mm` | Vec3 | yes |  |
| `camera.fov_deg` | number |  | Default `35`. |
| `assembly_bbox_mm` | BBox | yes |  |
| `render` | AssetRef \| null |  | Large PNG of the assembled device, shown until GLBs finish loading. |
| `preload` | string[] |  | Asset urls to fetch first, in priority order. |

### 4.8 Design

#### Design

Source: `design.schema.json`.

A complete open hardware design in the catalog (for example Corne). The reuse stage returns one of these as is (exact), with substitutions (substitute), or as the skeleton for compose. Parts, connections and layouts use the same shapes as Build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `design_id` | Id | yes |  |
| `name` | string | yes |  |
| `aliases` | string[] |  |  |
| `summary` | string \| null |  |  |
| `repo_url` | string \| null |  |  |
| `device_class` | DeviceClass | yes |  |
| `taxonomy_path` | Slug[] | yes | (min items 1) |
| `functions` | FunctionId[] | yes |  |
| `attributes` | object |  | Facet record of the design (facet key to value), matched against Spec requirements by the reuse stage. |
| `popularity` | number \| null |  | Prior used for underspecified prompts. 1 = most popular in its class. (min 0, max 1) |
| `slots` | Slot[] |  |  |
| `parts` | BuildPart[] | yes |  |
| `connections` | Connection[] | yes |  |
| `layouts` | Layout[] |  |  |
| `enclosures` | Enclosure[] |  |  |
| `boards` | Board[] |  |  |
| `firmware` | Firmware \| null |  |  |
| `variants` | object[] |  | Changes the design allows without leaving the exact tier. |
| `variants[].kind` | enum | yes | Values: `recolor`, `material`, `resize`, `swap`, `unknown`. |
| `variants[].target` | Subject |  |  |
| `variants[].allowed` | any |  | List of allowed values, or {min, max} for resize. |
| `variants[].label` | string |  |  |
| `assets` | AssetRef[] |  |  |
| `card` | DesignCard |  |  |
| `licence` | Licence | yes |  |
| `provenance` | Provenance | yes |  |
| `own_enclosure` | boolean |  | true when the design ships its own case files. Exact and substitute builds keep that case; false means a generated blank case is used. |
| `prebuilt_firmware` | boolean |  | true when the design ships a binary that the firmware stage can serve as is (firmware.mode prebuilt). |

#### DesignCard

Source: `design.schema.json#/$defs/DesignCard`.

Compact design summary for lists and the reuse card.

| Field | Type | Req | Notes |
|---|---|---|---|
| `design_id` | Id | yes |  |
| `name` | string | yes |  |
| `summary` | string \| null |  |  |
| `device_class` | DeviceClass |  |  |
| `thumbnail_url` | string \| null |  |  |
| `repo_url` | string \| null |  |  |
| `licence_spdx` | string |  |  |
| `commercial_ok` | TriState |  |  |
| `key_specs` | KeySpec[] |  | (max items 6) |

### 4.9 CheckResult

#### CheckResult

Source: `check.schema.json`.

Result of one deterministic rule applied to one subject. check_key identifies the (rule, subject) pair; a newer result with the same check_key replaces the older one in the client store. rule_id is an open string so new rules never break clients; v1 rule ids are listed in SPEC.md section 6.1.

| Field | Type | Req | Notes |
|---|---|---|---|
| `check_key` | string | yes | rule_id plus subject, for example elec.i2c.address_clash:u_oled_l. (min length 1, max length 200) |
| `rule_id` | string | yes | (pattern `^[a-z]+(\.[a-z0-9_]+){1,3}$`) |
| `status` | CheckStatus | yes |  |
| `severity` | Severity | yes | How bad a fail would be. A pass keeps the severity of the rule. |
| `message` | string | yes | (max length 300) |
| `subjects` | Subject[] |  |  |
| `measured` | number \| string \| boolean \| null |  |  |
| `limit` | number \| string \| boolean \| null |  |  |
| `unit` | string \| null |  |  |
| `fix_hint` | string \| null |  | (max length 200) |
| `stage` | StageId |  |  |
| `duration_ms` | DurationMs |  |  |

### 4.10 ErrorObject

#### ErrorObject

Source: `error.schema.json`.

Error body used by REST responses (status >= 400), the WS error event, ack (accepted false), edit.rejected and build.failed.

| Field | Type | Req | Notes |
|---|---|---|---|
| `code` | ErrorCode | yes |  |
| `message` | string | yes | (max length 500) |
| `retryable` | boolean | yes | true when sending the same request again later may succeed. |
| `stage` | StageId |  |  |
| `subjects` | Subject[] |  |  |
| `details` | object |  |  |


## 5. Vocabularies

The UI must take display labels from `GET /v1/vocab` (fixture `rest/vocab`) rather than hard coding them. The id lists below are the v1 values; new values may be added (section 1).

### 5.1 Device classes

DeviceClass (first element of `Spec.taxonomy_path`): `input_device`, `wearable`, `handheld`, `display_device`, `sensor_station`, `audio`, `robot`, `vehicle`, `tool`, `lighting`, `home`, `computer`, `radio`, `instrument`, `other`, `unknown`.

### 5.2 Function taxonomy

107 FunctionIds, grouped by prefix. A slot fills exactly one function.

| Group | FunctionIds (label) |
|---|---|
| `compute` | `compute.mcu` (MCU), `compute.sbc` (SBC), `compute.fpga` (FPGA) |
| `comms` | `comms.ble` (BLE), `comms.wifi` (WiFi), `comms.lora` (LoRa), `comms.cellular` (Cellular), `comms.nfc` (NFC), `comms.ir` (IR), `comms.zigbee_thread` (Zigbee thread), `comms.ethernet` (Ethernet), `comms.can` (CAN), `comms.rs485` (RS485), `comms.usb_device` (USB device), `comms.usb_host` (USB host), `comms.wired_link` (Wired link) |
| `input` | `input.key` (Key), `input.key_matrix` (Key matrix), `input.button` (Button), `input.rotary_encoder` (Rotary encoder), `input.joystick` (Joystick), `input.potentiometer` (Potentiometer), `input.touch` (Touch), `input.trackball` (Trackball), `input.toggle_switch` (Toggle switch) |
| `sense` | `sense.temperature` (Temperature), `sense.humidity` (Humidity), `sense.pressure` (Pressure), `sense.gas` (Gas), `sense.co2` (CO2), `sense.particulate` (Particulate), `sense.light` (Light), `sense.color` (Color), `sense.uv` (UV), `sense.proximity` (Proximity), `sense.distance` (Distance), `sense.imu` (IMU), `sense.magnetic` (Magnetic), `sense.gnss` (GNSS), `sense.sound` (Sound), `sense.camera` (Camera), `sense.current` (Current), `sense.weight` (Weight), `sense.soil_moisture` (Soil moisture), `sense.heart_rate` (Heart rate), `sense.presence` (Presence), `sense.water_level` (Water level) |
| `display` | `display.oled` (OLED), `display.lcd_char` (LCD char), `display.tft` (TFT), `display.memory_lcd` (Memory lcd), `display.epaper` (Epaper), `display.led_matrix` (LED matrix), `display.seven_segment` (Seven segment), `display.indicator_led` (Indicator led) |
| `output` | `output.rgb_led` (RGB LED), `output.speaker` (Speaker), `output.buzzer` (Buzzer), `output.haptic` (Haptic), `output.motor_dc` (Motor dc), `output.motor_servo` (Motor servo), `output.motor_stepper` (Motor stepper), `output.relay` (Relay), `output.pump` (Pump), `output.solenoid` (Solenoid), `output.heater` (Heater), `output.fan` (Fan) |
| `power` | `power.battery` (Battery), `power.coin_cell` (Coin cell), `power.charger` (Charger), `power.regulator` (Regulator), `power.usb_in` (USB in), `power.solar` (Solar), `power.switch` (Switch), `power.fuel_gauge` (Fuel gauge), `power.protection` (Protection) |
| `storage` | `storage.sd_card` (SD card), `storage.flash` (Flash), `storage.eeprom` (EEPROM) |
| `mech` | `mech.enclosure` (Enclosure), `mech.plate` (Plate), `mech.keycap` (Keycap), `mech.stabilizer` (Stabilizer), `mech.fastener` (Fastener), `mech.standoff` (Standoff), `mech.foam` (Foam), `mech.foot` (Foot), `mech.mount` (Mount), `mech.chassis` (Chassis), `mech.wheel` (Wheel), `mech.knob` (Knob) |
| `interconnect` | `interconnect.pcb` (PCB), `interconnect.cable` (Cable), `interconnect.connector` (Connector), `interconnect.header` (Header), `interconnect.jack` (Jack) |
| `component` | `component.resistor` (Resistor), `component.capacitor` (Capacitor), `component.inductor` (Inductor), `component.diode` (Diode), `component.transistor` (Transistor), `component.ic` (IC), `component.crystal` (Crystal), `component.led` (LED), `component.other` (Other) |
| `other` | `other` (Other) |
| `unknown` | `unknown` (Unknown) |

### 5.3 Interface types and params

Role: provides: the side that offers the resource (supply, bus controller, socket, hole pattern, port). requires: the side that consumes it. A connection joins one provides port to one requires port of the same type.

`Interface.params` shape depends on `Interface.type` (`vocab.schema.json#/$defs/Params_<type>`). Unknown params keys are ignored.

| InterfaceType | Required params | Optional params |
|---|---|---|
| `power_in` | `v_min_v`: number, `v_max_v`: number | `rail`: Rail, `i_typ_a`: number, `i_max_a`: number |
| `power_out` | `v_nom_v`: number, `i_max_a`: number | `rail`: Rail, `v_min_v`: number, `v_max_v`: number |
| `gpio` | `count`: integer | `v_logic_v`: number, `capabilities`: enum[] |
| `analog` | `count`: integer | `v_min_v`: number, `v_max_v`: number, `resolution_bits`: integer |
| `i2c` | `v_logic_v`: number | `addresses`: integer[], `address_options`: integer[], `speed_max_hz`: number |
| `spi` | `v_logic_v`: number | `cs_count`: integer, `speed_max_hz`: number, `mode`: integer |
| `uart` | `v_logic_v`: number | `baud_max`: integer, `flow_control`: boolean |
| `i2s` | none | `v_logic_v`: number, `direction`: enum |
| `usb` | `connector`: enum | `usb_role`: enum, `speed`: enum, `power_v`: number |
| `qwiic` | none | `connector`: enum, `v_logic_v`: number, `addresses`: integer[], `passthrough`: boolean |
| `radio` | `protocol`: enum | `link_role`: enum |
| `module_footprint` | `form_factor`: enum | `mount`: enum, `pin_count`: integer |
| `switch_socket` | `family`: SwitchFamily | `hotswap`: boolean, `count`: integer, `pitch_x_mm`: number, `pitch_y_mm`: number, `led`: boolean |
| `switch_stem` | `stem`: enum | `family`: SwitchFamily, `travel_mm`: number |
| `plate_cutout` | `family`: SwitchFamily | `cutout_mm`: number, `thickness_mm`: number, `count`: integer |
| `layout` | `layout_id`: string | `key_count`: integer, `size`: enum |
| `stabilizer` | none | `size_u`: number, `mount`: enum, `count`: integer |
| `mounting_holes` | `screw`: Screw | `pattern_id`: string, `hole_diameter_mm`: number, `holes_mm`: Vec2[], `count`: integer |
| `fastener` | `thread`: Screw | `length_mm`: number, `head`: enum, `standoff_height_mm`: number |
| `battery` | `chemistry`: enum, `v_nom_v`: number | `connector`: enum, `capacity_mah`: number, `cells`: integer |
| `addressable_led` | `protocol`: enum | `count`: integer, `v_logic_v`: number |
| `motor` | `kind`: enum | `v_max_v`: number, `i_max_a`: number, `channels`: integer |
| `jack` | `kind`: enum | `poles`: integer, `use`: enum |
| `panel_access` | `feature`: enum | `face`: Face, `size_mm`: Vec2, `center_mm`: Vec3, `shape`: enum |
| `other` | none | none |
| `unknown` | none | none |

Supporting enums: Rail: `3v3`, `5v`, `vbat`, `vin`, `vbus`, `12v`, `other`, `unknown`. SwitchFamily: `mx`, `choc_v1`, `choc_v2`, `alps`, `gateron_lp`, `other`, `unknown`. Screw: `m2`, `m2_5`, `m3`, `m4`, `other`, `unknown`. Face: `pos_x`, `neg_x`, `pos_y`, `neg_y`, `pos_z`, `neg_z`, `any`, `unknown`.

### 5.4 Facets

Requirements and filters use facet keys from `GET /v1/facets`. The v1 excerpt in `rest/facets`:

| Facet | Label | Value type | Example values |
|---|---|---|---|
| `switch_family` | Switch family | enum | `mx`, `choc_v1` |
| `layout_size` | Layout | enum | `percent_60`, `split` |
| `wireless` | Wireless | enum | `ble`, `none` |
| `max_width_mm` | Width | number |  |

## 6. Checks and warnings

Every check is a deterministic rule applied to one subject. A newer `CheckResult` with the same `check_key` replaces the older one. `status` is `pass`, `fail` or `unknown`. `severity` is how bad a fail would be: `critical` blocks the build or the edit, `error` blocks an edit and marks the build red, `warning` and `info` never block.

### 6.1 Check rules (v1)

`rule_id` is an open string; a client shows an unknown rule id with its `message` and the neutral style.

| rule_id | What it checks | Severity of a fail | Stage |
|---|---|---|---|
| `elec.power.voltage_range` | Supply voltage within input range | critical | `compose` |
| `elec.power.current_budget` | Total current within supply limit | error | `compose` |
| `elec.logic.level_mismatch` | Logic levels match | error | `compose` |
| `elec.i2c.address_clash` | No two I2C devices share an address | error | `compose` |
| `elec.i2c.address_range` | I2C address supported by the device | error | `compose` |
| `elec.spi.cs_available` | A chip select pin is free for each SPI device | error | `compose` |
| `elec.gpio.pins_available` | Enough free MCU pins | error | `compose` |
| `elec.uart.pairing` | UART TX goes to RX | error | `compose` |
| `elec.usb.present` | Device has a USB port for power or flashing | warning | `compose` |
| `elec.battery.charger_present` | A battery has a charger | error | `compose` |
| `mech.switch.family_match` | Switches fit the sockets | critical | `compose` |
| `mech.keycap.stem_match` | Keycaps fit the switch stems | error | `compose` |
| `mech.layout.match` | Switch count matches key positions | error | `compose` |
| `mech.plate.thickness` | Plate thickness suits the switch clips | warning | `compose` |
| `mech.mount.hole_pattern` | Mounting holes line up | error | `place` |
| `mech.fit.collision` | No parts overlap | error | `place` |
| `mech.fit.enclosure` | Parts fit inside the case | error | `enclose` |
| `mech.access.panel` | Ports and controls reachable through the case | warning | `enclose` |
| `mech.stabilizer.required` | Keys 2u and wider have stabilizers | warning | `compose` |
| `board.drc` | Board passes design rule check | error | `board` |
| `board.routing.complete` | All nets routed | error | `board` |
| `fw.driver.available` | A driver exists for each part | error | `firmware` |
| `fw.compile` | Firmware compiles | error | `firmware` |
| `lic.commercial_ok` | Licences allow commercial use | warning | `compose` |
| `lic.attribution` | Attribution recorded where required | info | `compose` |
| `data.dims_verified` | Dimensions come from a verified source | info | `compose` |
| `data.interface_unknown` | Every interface has a known type | warning | `compose` |
| `slot.critical_filled` | Every critical slot has a part | critical | `compose` |
| `slot.optional_missing` | Optional slots left empty | info | `compose` |

### 6.2 Warning codes

`Warning.code` values: `optional_part_missing`, `licence_unknown`, `licence_noncommercial`, `dims_third_party`, `data_unverified`, `constraint_relaxed`, `substitute_used`, `llm_fallback`, `llm_degraded`, `slow_stage`, `asset_missing`, `compile_skipped`, `assumption_made`, `other`, `unknown`. Warnings never block. `warning_id` is stable; a newer warning with the same id replaces the old one.

## 7. REST API

Base URL is the backend origin (the tunnel URL in the demo). Every JSON response carries `spec_version`. Every non 2xx response body is `ErrorResponse` (`{spec_version, error: ErrorObject}`). REST is read only except `POST /v1/builds`.

| Method | Path | Query or body | Response (rest.schema.json def) | Notes |
|---|---|---|---|---|
| GET | `/v1/health` |  | Health | Liveness, catalog size, model status. |
| GET | `/v1/vocab` |  | Vocab | Every enum with display labels. Fetch once at boot; cache for the session. |
| GET | `/v1/facets` |  | Facets | Facet keys, value types and counts. |
| GET | `/v1/parts` | q, function, interface, facet.KEY=VALUE (repeatable), limit (default 20, max 100), cursor | PartsPage | Catalog search. Results are PartCards. |
| GET | `/v1/parts/{part_id}` | part_id is URL encoded (mod%3Anice_nano_v2) | PartResponse | Full Part. |
| GET | `/v1/designs` | q, device_class, limit, cursor | DesignsPage | Design list. |
| GET | `/v1/designs/{design_id}` |  | DesignResponse | Full Design. |
| POST | `/v1/builds` | body CreateBuildRequest | CreateBuildResponse (201) | Fallback only. The normal path is the WebSocket build.start. |
| GET | `/v1/builds/{build_id}` |  | BuildResponse | Current Build. Equal to reducing every event so far. |
| GET | `/v1/builds/{build_id}/events` | after_seq (default 0), limit (default 500) | EventsPage | Event log replay; the same messages the WebSocket sent. |
| GET | `/v1/builds/{build_id}/slots/{slot_id}/alternatives` | instance_id (optional), limit (default 8) | Alternatives | SwapDrawer contents, already checked against the current build. |
| GET | `/v1/builds/{build_id}/export` | format = bom_csv \| stl \| 3mf \| step \| kicad \| firmware_zip \| zip | file download | Content-Disposition attachment. 409 E_BUILD_NOT_READY before build.done. |
| GET | `/assets/...` |  | static file | GLB, PNG, STL and other assets. Immutable: a changed file gets a new URL (revision suffix). |
| GET | `/v1/ws` |  | WebSocket upgrade | The only streaming channel (section 8). |

Paging: list endpoints return `next_cursor` (string or null). Pass it back as `cursor` to get the next page.

CORS: the backend allows the frontend origin and `http://localhost:5173`.

### 7.1 REST bodies

#### ErrorResponse

Source: `rest.schema.json#/$defs/ErrorResponse`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `error` | ErrorObject | yes |  |

#### Health

Source: `rest.schema.json#/$defs/Health`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `status` | enum | yes | Values: `ok`, `degraded`, `down`, `unknown`. |
| `server_version` | string | yes |  |
| `mock` | boolean |  |  |
| `llm` | object |  |  |
| `llm.provider` | string |  |  |
| `llm.model` | string |  |  |
| `llm.status` | enum | yes | Values: `ok`, `degraded`, `down`, `unknown`. |
| `llm_fallback` | object |  | Backup provider (anthropic) used when the primary fails or times out. |
| `llm_fallback.provider` | string |  |  |
| `llm_fallback.model` | string |  |  |
| `llm_fallback.status` | enum | yes | Values: `ok`, `degraded`, `down`, `unknown`. |
| `part_count` | integer |  | (min 0) |
| `design_count` | integer |  | (min 0) |
| `uptime_s` | integer |  | (min 0) |

#### PartsPage

Source: `rest.schema.json#/$defs/PartsPage`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `items` | PartCard[] | yes |  |
| `next_cursor` | string \| null | yes |  |
| `total` | integer | yes | (min 0) |

#### PartResponse

Source: `rest.schema.json#/$defs/PartResponse`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `part` | Part | yes |  |

#### Facets

Source: `rest.schema.json#/$defs/Facets`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `facets` | object[] | yes |  |
| `facets[].facet` | Slug | yes |  |
| `facets[].label` | string | yes |  |
| `facets[].value_type` | enum | yes | Values: `enum`, `number`, `bool`, `string`, `unknown`. |
| `facets[].unit` | string \| null |  |  |
| `facets[].values` | object[] |  |  |
| `facets[].min` | number \| null |  |  |
| `facets[].max` | number \| null |  |  |
| `facets[].applies_to` | FunctionId[] |  |  |

#### Vocab

Source: `rest.schema.json#/$defs/Vocab`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `functions` | object[] | yes |  |
| `functions[].id` | string | yes |  |
| `functions[].label` | string | yes |  |
| `functions[].group` | string |  |  |
| `functions[].description` | string |  |  |
| `interface_types` | object[] | yes |  |
| `interface_types[].id` | string | yes |  |
| `interface_types[].label` | string | yes |  |
| `interface_types[].group` | string |  |  |
| `interface_types[].description` | string |  |  |
| `device_classes` | object[] | yes |  |
| `device_classes[].id` | string | yes |  |
| `device_classes[].label` | string | yes |  |
| `device_classes[].group` | string |  |  |
| `device_classes[].description` | string |  |  |
| `stages` | object[] | yes |  |
| `stages[].id` | StageId | yes |  |
| `stages[].label` | string | yes |  |
| `stages[].budget_ms` | DurationMs |  |  |
| `check_rules` | object[] | yes |  |
| `check_rules[].id` | string | yes |  |
| `check_rules[].label` | string | yes |  |
| `check_rules[].severity` | Severity |  |  |
| `warning_codes` | object[] | yes |  |
| `warning_codes[].id` | string | yes |  |
| `warning_codes[].label` | string | yes |  |
| `warning_codes[].group` | string |  |  |
| `warning_codes[].description` | string |  |  |
| `error_codes` | object[] | yes |  |
| `error_codes[].id` | string | yes |  |
| `error_codes[].label` | string | yes |  |
| `error_codes[].group` | string |  |  |
| `error_codes[].description` | string |  |  |

#### DesignsPage

Source: `rest.schema.json#/$defs/DesignsPage`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `items` | DesignCard[] | yes |  |
| `next_cursor` | string \| null | yes |  |
| `total` | integer | yes | (min 0) |

#### DesignResponse

Source: `rest.schema.json#/$defs/DesignResponse`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `design` | Design | yes |  |

#### CreateBuildRequest

Source: `rest.schema.json#/$defs/CreateBuildRequest`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `prompt` | string | yes | (min length 1, max length 2000) |
| `options` | BuildOptions |  |  |

#### CreateBuildResponse

Source: `rest.schema.json#/$defs/CreateBuildResponse`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `build_id` | BuildId | yes |  |
| `ws_url` | string | yes | Connect and send build.resume with last_seq 0. |
| `events_url` | string | yes |  |

#### BuildResponse

Source: `rest.schema.json#/$defs/BuildResponse`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `build` | Build | yes |  |

#### EventsPage

Source: `rest.schema.json#/$defs/EventsPage`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `build_id` | BuildId | yes |  |
| `events` | WebSocket server events[] | yes |  |
| `next_after_seq` | integer | yes | (min 0) |
| `complete` | boolean | yes | true when the terminal event is included and no later events exist yet. |

#### Alternatives

Source: `rest.schema.json#/$defs/Alternatives`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `build_id` | BuildId | yes |  |
| `slot_id` | string | yes |  |
| `instance_id` | string \| null |  |  |
| `current_part_id` | string \| null | yes |  |
| `items` | object[] | yes |  |
| `items[].card` | PartCard | yes |  |
| `items[].compatible` | boolean | yes | false: swapping would fail the listed checks (edit.rejected). |
| `items[].failed_checks` | CheckResult[] |  |  |
| `items[].deltas` | object[] |  | (max items 4) |


## 8. WebSocket protocol

One socket per browser tab at `wss://<backend>/v1/ws`. Text frames only, one JSON message per frame.

### 8.1 Envelopes

Client to server (`ws_envelope.schema.json#/$defs/ClientEnvelope`):

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `type` | string | yes | (pattern `^[a-z]+(\.[a-z_]+)*$`) |
| `msg_id` | MsgId | yes |  |
| `ts` | Timestamp |  |  |
| `payload` | object | yes |  |

Server to client (`ws_envelope.schema.json#/$defs/ServerEnvelope`):

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec_version` | SpecVersion | yes |  |
| `type` | string | yes | (pattern `^[a-z]+(\.[a-z_]+)*$`) |
| `seq` | integer | yes | Per build, contiguous from 1. 0 for connection scoped events (hello, ack, pong, error without a build). (min 0) |
| `build_id` | BuildId \| null | yes |  |
| `ts` | Timestamp | yes |  |
| `stage` | StageId |  |  |
| `revision` | integer |  | Build revision after this event was applied. (min 0) |
| `cause` | object |  | Set on every event caused by a client message (an edit, a cancel). |
| `cause.msg_id` | MsgId |  |  |
| `cause.edit_id` | string |  |  |
| `payload` | object | yes |  |

### 8.2 Client messages

| Type | Payload fields (? = optional) | Meaning |
|---|---|---|
| `build.start` | `prompt`, `options`? | Start a new build from a prompt. The server answers ack (with build_id) and then streams events. |
| `build.resume` | `build_id`, `last_seq` | Re-attach to a build after reconnect. The server replays every event with seq > last_seq, or sends error E_RESUME_GAP plus build.snapshot. |
| `edit.apply` | `build_id`, `base_revision`?, `ops` | Apply edit ops atomically. Allowed once the build has reached build.done (otherwise E_BUILD_NOT_READY). |
| `build.cancel` | `build_id` | Stop a running build. The server ends the stream with build.failed (E_CANCELLED). |
| `ping` |  | Keepalive. The server answers pong with the same msg_id. |
| `clarify.answer` | `build_id`, `question_id`, `option_id`?, `free_text`?, `skip`? | Answer the open clarify.request: exactly one of option_id, free_text or skip. Free text that only asks the engine to choose (for example just pick) is treated as skip. Wrong question_id or no open question: ack accepted false with E_CLARIFY_NOT_PENDING; an option_id not in the question: E_INVALID_ANSWER. |

#### build.start

Source: `ws_client.schema.json#/$defs/C_build_start`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `prompt` | string | yes | (min length 1, max length 2000) |
| `options` | BuildOptions |  |  |

#### build.resume

Source: `ws_client.schema.json#/$defs/C_build_resume`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `build_id` | BuildId | yes |  |
| `last_seq` | integer | yes | (min 0) |

#### edit.apply

Source: `ws_client.schema.json#/$defs/C_edit_apply`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `build_id` | BuildId | yes |  |
| `base_revision` | integer \| null |  | When set and not equal to the current revision, the edit is rejected with E_STALE_REVISION. null: apply to whatever is current. (min 0) |
| `ops` | EditOp[] | yes | (min items 1, max items 20) |

#### build.cancel

Source: `ws_client.schema.json#/$defs/C_build_cancel`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `build_id` | BuildId | yes |  |

#### ping

Source: `ws_client.schema.json#/$defs/C_ping`.

| Field | Type | Req | Notes |
|---|---|---|---|

#### clarify.answer

Source: `ws_client.schema.json#/$defs/C_clarify_answer`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `build_id` | BuildId | yes |  |
| `question_id` | string | yes | (pattern `^q_[a-z0-9_]{1,31}$`) |
| `option_id` | string |  | (pattern `^o_[a-z0-9_]{1,31}$`) |
| `free_text` | string |  | (min length 1, max length 300) |
| `skip` | true |  |  |

#### BuildOptions

Source: `ws_client.schema.json#/$defs/BuildOptions`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `force_tier` | enum |  | Debug and demo only. null: the reuse stage decides. Values: `exact`, `substitute`, `compose`; or null. |
| `commercial_only` | boolean |  | Drop candidates whose commercial_ok is no (and unknown, flagged). Default `false`. |
| `seed` | integer \| null |  | Makes tie breaks and model sampling repeatable. |
| `mock_fixture` | string \| null |  | Mock mode only: fixture name to replay. |


### 8.3 Server events

Scope `connection`: about the socket, not a build. Always `seq: 0`, not stored in the event log, not replayed. Scope `build`: stored in the build's event log with a contiguous seq.

| # | Type | Scope | Payload fields (? = optional) | Meaning |
|---|---|---|---|---|
| 1 | `hello` | connection | `server_version`, `session_id`, `mock`?, `limits`?, `capabilities`? | First message on every connection. |
| 2 | `ack` | connection | `msg_id`, `accepted`, `duplicate`, `build_id`?, `edit_id`?, `error`? | Answer to every client message except ping. |
| 3 | `pong` | connection | `msg_id`, `server_time`? | Answer to ping. |
| 4 | `error` | connection | `error`, `msg_id`? | A problem that is not tied to one build result (bad message, resume gap). Build failures use build.failed. |
| 5 | `build.snapshot` | build | `build`, `reason` | Full build state. Replace the whole client store for this build, then continue with seq > build.last_seq. |
| 6 | `stage.started` | build | `stage`, `label`?, `budget_ms`? | A pipeline stage began. |
| 7 | `stage.progress` | build | `stage`, `message`, `fraction`? | Optional progress inside a long stage. |
| 8 | `stage.completed` | build | `stage`, `status`, `duration_ms`, `message`? | A stage ended. A skipped stage sends only this event, with status skipped. |
| 9 | `clarify.request` | build | `question_id`, `question`, `options`, `allow_free_text`, `allow_skip`?, `default_option_id`?, `reason`, `missing_facets`, `timeout_ms`?, `round` | The engine asks instead of guessing. Sent right after stage.completed classify (needs_input) with no stage open. The build waits (status awaiting_input) until clarify.resolved. |
| 10 | `clarify.resolved` | build | `question_id`, `resolution`, `option_id`?, `free_text`?, `assumptions` | Closes the open question: answered, skipped (best guess with stated assumptions) or timed out. Classify then restarts with the answer folded in. |
| 11 | `spec.ready` | build | `spec` | Classify result. |
| 12 | `reuse.decided` | build | `tier`, `design_id`, `design`?, `considered`, `unmet_hard`, `reason` | Reuse tier decision. |
| 13 | `slots.ready` | build | `slots` | All slots for the build, in decision order. |
| 14 | `slot.updated` | build | `slot` | Full slot object after a change of state or counts. Replaces the slot with the same slot_id. |
| 15 | `candidates.ready` | build | `slot_id`, `step`, `filters`, `count_before`, `count_after`, `survivors` | Filtering result for one slot at one step. |
| 16 | `decision.made` | build | `decision` | A slot was decided. |
| 17 | `decision.reverted` | build | `decision_id`, `slot_id`, `reason` | Backtracking undid an earlier decision. The slot returns to narrowing; parts it added are removed by separate part.removed events. |
| 18 | `layout.added` | build | `layout` | A key layout. Sent before any part that places on it. |
| 19 | `part.added` | build | `part` | A new instance. |
| 20 | `part.updated` | build | `part` | Full instance after any change (swap, recolor, status). Replace by instance_id. |
| 21 | `part.removed` | build | `instance_id`, `reason`? | Instance removed. Its connections were removed by earlier connection.removed events. |
| 22 | `connection.added` | build | `connection` | A new connection. |
| 23 | `connection.removed` | build | `connection_id`, `reason`? | Connection removed. |
| 24 | `placement.updated` | build | `placements`, `assembly_bbox_mm`?, `solver`? | New poses for some or all instances (solver run or move edit). Replace placement by instance_id; others are unchanged. |
| 25 | `enclosure.updated` | build | `enclosure` | Full enclosure. Replace by enclosure_id. |
| 26 | `board.updated` | build | `board` | Full board. Replace by board_id. |
| 27 | `firmware.ready` | build | `firmware` | Full firmware object. May repeat (compile status changes) and may arrive after build.done. |
| 28 | `firmware.progress` | build | `firmware_id`, `phase`, `fraction`?, `target_id`?, `message`? | Live compile progress (firmware.mode compiled only). Optional, may repeat and may arrive after build.done; the final state always comes in firmware.ready. |
| 29 | `scene.ready` | build | `scene` | Camera, bounding box and asset preload list. Sent once all parts of the first full assembly exist. |
| 30 | `check.result` | build | `results` | One or more check results. Replace by check_key. |
| 31 | `warning` | build | `warning` | A non fatal problem. Append; warning_id is unique per build. |
| 32 | `build.done` | build | `summary`, `timings_ms`, `total_ms`? | Terminal: the build finished. Exactly one of build.done or build.failed per build. |
| 33 | `build.failed` | build | `error`, `conflict`?, `suggestions`? | Terminal: the build could not finish. |
| 34 | `edit.applied` | build | `edit_id`, `msg_id`, `ops`, `revision`, `duration_ms` | All ops of an edit succeeded. Sent after every granular event of that edit. |
| 35 | `edit.rejected` | build | `edit_id`, `msg_id`, `error`, `failed_checks`?, `suggestions`? | The edit changed nothing. |

#### hello

Source: `ws_server.schema.json#/$defs/S_hello`. Scope: connection.

| Field | Type | Req | Notes |
|---|---|---|---|
| `server_version` | string | yes |  |
| `session_id` | string | yes |  |
| `mock` | boolean |  | Default `false`. |
| `limits` | object |  |  |
| `limits.max_prompt_chars` | integer |  |  |
| `limits.max_ops_per_edit` | integer |  |  |
| `limits.msg_id_ttl_s` | integer |  |  |
| `capabilities` | string[] |  | Optional server features, for example compile, tscircuit. |

#### ack

Source: `ws_server.schema.json#/$defs/S_ack`. Scope: connection.

| Field | Type | Req | Notes |
|---|---|---|---|
| `msg_id` | MsgId | yes |  |
| `accepted` | boolean | yes |  |
| `duplicate` | boolean | yes | true: this msg_id was already processed; nothing was done again. |
| `build_id` | BuildId \| null |  |  |
| `edit_id` | string \| null |  | Set when the message was edit.apply and accepted. |
| `error` | ErrorObject \| null |  |  |

#### pong

Source: `ws_server.schema.json#/$defs/S_pong`. Scope: connection.

| Field | Type | Req | Notes |
|---|---|---|---|
| `msg_id` | MsgId | yes |  |
| `server_time` | Timestamp |  |  |

#### error

Source: `ws_server.schema.json#/$defs/S_error`. Scope: connection.

| Field | Type | Req | Notes |
|---|---|---|---|
| `error` | ErrorObject | yes |  |
| `msg_id` | MsgId \| null |  |  |

#### build.snapshot

Source: `ws_server.schema.json#/$defs/S_build_snapshot`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `build` | Build | yes |  |
| `reason` | enum | yes | Values: `resume_gap`, `resume`, `late_join`, `unknown`. |

#### stage.started

Source: `ws_server.schema.json#/$defs/S_stage_started`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `stage` | StageId | yes |  |
| `label` | string |  |  |
| `budget_ms` | DurationMs |  |  |

#### stage.progress

Source: `ws_server.schema.json#/$defs/S_stage_progress`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `stage` | StageId | yes |  |
| `message` | string | yes | (max length 120) |
| `fraction` | number \| null |  | (min 0, max 1) |

#### stage.completed

Source: `ws_server.schema.json#/$defs/S_stage_completed`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `stage` | StageId | yes |  |
| `status` | enum | yes | needs_input: classify only; the stage ends without spec.ready and clarify.request follows. Values: `ok`, `skipped`, `degraded`, `failed`, `needs_input`, `unknown`. |
| `duration_ms` | DurationMs | yes |  |
| `message` | string \| null |  |  |

#### clarify.request

Source: `ws_server.schema.json#/$defs/S_clarify_request`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `question_id` | string | yes | (pattern `^q_[a-z0-9_]{1,31}$`) |
| `question` | string | yes | (max length 200) |
| `options` | ClarifyOption[] | yes | (min items 2, max items 4) |
| `allow_free_text` | boolean | yes |  |
| `allow_skip` | boolean |  | true: the card shows Just pick, which resolves as skipped with the default option. Default `true`. |
| `default_option_id` | string \| null |  | Best guess used on skip or timeout. |
| `reason` | string | yes | Why the engine is asking instead of guessing. (max length 200) |
| `missing_facets` | Slug[] | yes | (min items 1) |
| `timeout_ms` | integer |  | After this long with no answer the server resolves with timeout. (min 0) Default `60000`. |
| `round` | integer | yes | (min 1, max 2) |

#### clarify.resolved

Source: `ws_server.schema.json#/$defs/S_clarify_resolved`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `question_id` | string | yes | (pattern `^q_[a-z0-9_]{1,31}$`) |
| `resolution` | enum | yes | Values: `answered_option`, `answered_text`, `skipped`, `timeout`, `unknown`. |
| `option_id` | string \| null |  |  |
| `free_text` | string \| null |  | (max length 300) |
| `assumptions` | Assumption[] | yes | Filled on skipped and timeout: what the engine picked in the user's place. |

#### spec.ready

Source: `ws_server.schema.json#/$defs/S_spec_ready`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `spec` | Spec | yes |  |

#### reuse.decided

Source: `ws_server.schema.json#/$defs/S_reuse_decided`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `tier` | Tier | yes |  |
| `design_id` | string \| null | yes | Design used as is (exact), with changes (substitute), or as skeleton (compose). null: compose from nothing. |
| `design` | DesignCard \| null |  |  |
| `considered` | object[] | yes | (max items 5) |
| `considered[].design_id` | string | yes |  |
| `considered[].name` | string | yes |  |
| `considered[].tier` | Tier | yes |  |
| `considered[].score` | number \| null |  |  |
| `considered[].unmet` | string[] |  | req_ids of the Spec this design does not meet. |
| `unmet_hard` | string[] | yes | req_ids of hard requirements the chosen design does not meet. Non empty means compose. |
| `reason` | string | yes | (max length 240) |

#### slots.ready

Source: `ws_server.schema.json#/$defs/S_slots_ready`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `slots` | Slot[] | yes |  |

#### slot.updated

Source: `ws_server.schema.json#/$defs/S_slot_updated`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `slot` | Slot | yes |  |

#### candidates.ready

Source: `ws_server.schema.json#/$defs/S_candidates_ready`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `slot_id` | string | yes |  |
| `step` | integer | yes | (min 0) |
| `filters` | Filter[] | yes |  |
| `count_before` | integer | yes | (min 0) |
| `count_after` | integer | yes | (min 0) |
| `survivors` | Candidate[] | yes | Top survivors, at most 8, as shown to the model (C1..C8). (max items 8) |

#### decision.made

Source: `ws_server.schema.json#/$defs/S_decision_made`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `decision` | Decision | yes |  |

#### decision.reverted

Source: `ws_server.schema.json#/$defs/S_decision_reverted`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `decision_id` | string | yes |  |
| `slot_id` | string | yes |  |
| `reason` | string | yes | (max length 240) |

#### layout.added

Source: `ws_server.schema.json#/$defs/S_layout_added`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `layout` | Layout | yes |  |

#### part.added

Source: `ws_server.schema.json#/$defs/S_part_added`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `part` | BuildPart | yes |  |

#### part.updated

Source: `ws_server.schema.json#/$defs/S_part_updated`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `part` | BuildPart | yes |  |

#### part.removed

Source: `ws_server.schema.json#/$defs/S_part_removed`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `instance_id` | InstanceId | yes |  |
| `reason` | string \| null |  |  |

#### connection.added

Source: `ws_server.schema.json#/$defs/S_connection_added`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `connection` | Connection | yes |  |

#### connection.removed

Source: `ws_server.schema.json#/$defs/S_connection_removed`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `connection_id` | string | yes |  |
| `reason` | string \| null |  |  |

#### placement.updated

Source: `ws_server.schema.json#/$defs/S_placement_updated`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `placements` | object[] | yes |  |
| `placements[].instance_id` | InstanceId | yes |  |
| `placements[].placement` | Placement | yes |  |
| `assembly_bbox_mm` | BBox |  |  |
| `solver` | object |  |  |
| `solver.status` | enum | yes | Values: `optimal`, `feasible`, `fallback`, `skipped`, `unknown`. |
| `solver.duration_ms` | DurationMs |  |  |

#### enclosure.updated

Source: `ws_server.schema.json#/$defs/S_enclosure_updated`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `enclosure` | Enclosure | yes |  |

#### board.updated

Source: `ws_server.schema.json#/$defs/S_board_updated`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `board` | Board | yes |  |

#### firmware.ready

Source: `ws_server.schema.json#/$defs/S_firmware_ready`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `firmware` | Firmware | yes |  |

#### firmware.progress

Source: `ws_server.schema.json#/$defs/S_firmware_progress`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `firmware_id` | string | yes | (pattern `^fw_[a-z0-9_]{1,63}$`) |
| `phase` | enum | yes | Values: `queued`, `fetching`, `compiling`, `linking`, `packaging`, `unknown`. |
| `fraction` | number \| null |  | (min 0, max 1) |
| `target_id` | string \| null |  |  |
| `message` | string \| null |  | (max length 120) |

#### scene.ready

Source: `ws_server.schema.json#/$defs/S_scene_ready`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `scene` | Scene | yes |  |

#### check.result

Source: `ws_server.schema.json#/$defs/S_check_result`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `results` | CheckResult[] | yes | (min items 1) |

#### warning

Source: `ws_server.schema.json#/$defs/S_warning`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `warning` | Warning | yes |  |

#### build.done

Source: `ws_server.schema.json#/$defs/S_build_done`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `summary` | object | yes |  |
| `summary.part_count` | integer | yes | Physical items (sum of quantity). (min 0) |
| `summary.instance_count` | integer | yes | (min 0) |
| `summary.connection_count` | integer | yes | (min 0) |
| `summary.warning_count` | integer |  | (min 0) |
| `summary.checks` | object | yes |  |
| `timings_ms` | map<string, DurationMs> | yes |  |
| `total_ms` | DurationMs |  |  |

#### build.failed

Source: `ws_server.schema.json#/$defs/S_build_failed`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `error` | ErrorObject | yes |  |
| `conflict` | object \| null |  |  |
| `suggestions` | Suggestion[] |  | (max items 4) |

#### edit.applied

Source: `ws_server.schema.json#/$defs/S_edit_applied`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `edit_id` | string | yes |  |
| `msg_id` | MsgId | yes |  |
| `ops` | EditOp[] | yes | (min items 1) |
| `revision` | integer | yes | (min 0) |
| `duration_ms` | DurationMs | yes |  |

#### edit.rejected

Source: `ws_server.schema.json#/$defs/S_edit_rejected`. Scope: build.

| Field | Type | Req | Notes |
|---|---|---|---|
| `edit_id` | string | yes |  |
| `msg_id` | MsgId | yes |  |
| `error` | ErrorObject | yes |  |
| `failed_checks` | CheckResult[] |  |  |
| `suggestions` | Suggestion[] |  | (max items 4) |

#### Suggestion

Source: `ws_server.schema.json#/$defs/Suggestion`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `suggestion_id` | string | yes |  |
| `kind` | enum | yes | prompt: start a new build with prompt. edit: send edit.apply with ops. design: open the design (a new build with force_tier exact). Values: `prompt`, `edit`, `design`, `unknown`. |
| `label` | string | yes | (max length 80) |
| `prompt` | string \| null |  |  |
| `ops` | EditOp[] \| null |  |  |
| `design_id` | string \| null |  |  |


### 8.4 Edit ops

`edit.apply` carries 1 to 20 ops, applied atomically. Op names (client only enum): `swap_part`, `connect`, `disconnect`, `recolor`, `move`, `resize`, `add_part`, `remove_part`.

#### SwapPart

Source: `edit.schema.json#/$defs/SwapPart`.

Replace the part of an instance. instance_id stays the same; connections are re-resolved; enclosure rebuilds if geometry changed.

| Field | Type | Req | Notes |
|---|---|---|---|
| `op` | "swap_part" | yes |  |
| `instance_id` | InstanceId | yes |  |
| `part_id` | Id | yes |  |

#### Connect

Source: `edit.schema.json#/$defs/Connect`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `op` | "connect" | yes |  |
| `from` | PortRef | yes |  |
| `to` | PortRef | yes |  |

#### Disconnect

Source: `edit.schema.json#/$defs/Disconnect`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `op` | "disconnect" | yes |  |
| `connection_id` | string | yes |  |

#### Recolor

Source: `edit.schema.json#/$defs/Recolor`.

Exactly one of instance_id or enclosure_id.

| Field | Type | Req | Notes |
|---|---|---|---|
| `op` | "recolor" | yes |  |
| `instance_id` | InstanceId |  |  |
| `enclosure_id` | string |  |  |
| `color` | Color | yes |  |

#### Move

Source: `edit.schema.json#/$defs/Move`.

Set or nudge a pose. index targets one element of an arrayed instance. lock true keeps the pose fixed in later solver runs.

| Field | Type | Req | Notes |
|---|---|---|---|
| `op` | "move" | yes |  |
| `instance_id` | InstanceId | yes |  |
| `index` | integer \| null |  | (min 0) |
| `position_mm` | Vec3 |  |  |
| `rotation_deg` | Vec3 |  |  |
| `mode` | enum | yes | Values: `absolute`, `delta`. |
| `lock` | boolean |  | Default `true`. |

#### Resize

Source: `edit.schema.json#/$defs/Resize`.

Change parameters of a generated enclosure or a board. Only keys present change.

| Field | Type | Req | Notes |
|---|---|---|---|
| `op` | "resize" | yes |  |
| `target` | any | yes |  |
| `target.enclosure_id` | string |  |  |
| `target.board_id` | string |  |  |
| `params` | object | yes | Enclosure: any key of Enclosure.params. Board: size_mm, thickness_mm. |

#### AddPart

Source: `edit.schema.json#/$defs/AddPart`.

Add a new instance. The server picks instance_id, placement and connections, and reports them as part.added and connection.added.

| Field | Type | Req | Notes |
|---|---|---|---|
| `op` | "add_part" | yes |  |
| `part_id` | Id | yes |  |
| `slot_id` | string \| null |  |  |
| `quantity` | integer |  | (min 1) Default `1`. |
| `side` | Side |  |  |

#### RemovePart

Source: `edit.schema.json#/$defs/RemovePart`.

Remove an instance and its connections. Removing the only part of a critical slot is rejected with E_CRITICAL_PART_MISSING.

| Field | Type | Req | Notes |
|---|---|---|---|
| `op` | "remove_part" | yes |  |
| `instance_id` | InstanceId | yes |  |


### 8.5 Ordering guarantees

The server guarantees all of these. The contract tests check every one against the fixtures and against recorded backend output.

1. Per build, build-scoped events have `seq` starting at 1, contiguous and strictly increasing. `build.snapshot` is the exception: it carries `seq = build.last_seq` and does not advance the sequence.
2. Connection-scoped events (`hello`, `ack`, `pong`, `error`) have `seq: 0`.
3. `hello` is the first message on every socket. Clients send nothing until `hello` arrives.
4. Every client message except `ping` gets exactly one `ack`. The `ack` for `build.start` comes before any event of the new build. The `ack` for `edit.apply` comes before any event caused by that edit.
5. At most one stage is open per build. `stage.started` comes first; every event with `stage: X` in its envelope comes after `stage.started` X and before `stage.completed` X. A skipped stage sends only `stage.completed` with status `skipped`, with no stage open.
6. A build has exactly one terminal event, `build.done` or `build.failed`, sent when no stage is open.
7. After `build.failed`, nothing more is sent for that build.
8. After `build.done`, only these may arrive: `firmware.progress`, `firmware.ready`, `check.result` and `warning` from the background firmware compile, and edit events (`stage.started`/`stage.completed` for `edit`, model change events, `check.result`, `warning`, `edit.applied`, `edit.rejected`). Model change events after `build.done` always carry `cause.edit_id`.
9. References resolve: a slot is announced by `slots.ready` before any event names it; an instance is announced by `part.added` before any event names it; a layout is sent by `layout.added` before a part references it; a connection is removed before either of its parts is removed.
10. `revision` never decreases. It is 0 while the build runs, 1 from `build.done`, and each `edit.applied` adds 1. Late firmware events and `check.result` never change it.
11. In `candidates.ready`, the filter chain is consistent: the first filter's `count_before` equals the payload `count_before`, each filter's `count_before` equals the previous `count_after`, and the last `count_after` equals the payload `count_after`. `survivors` has at most min(8, count_after) entries.
12. `build.done.summary.instance_count` and `connection_count` equal the instances and connections in the store at that moment.
13. `*.updated` events carry the full object; the client replaces its copy, never merges.
14. Clarify: `stage.completed` with status `needs_input` (classify only) is immediately followed by `clarify.request`, sent with no stage open and no envelope `stage`. While a question is open only `warning`, `clarify.resolved` or a cancel-driven `build.failed` may arrive. `clarify.resolved` names the open `question_id`; when it answers a `clarify.answer`, the `ack` for that answer comes first and `clarify.resolved` carries `cause.msg_id`. Skipped and timeout resolutions list at least one assumption.

### 8.6 Idempotency

- `msg_id` is generated by the client, unique per session (a UUID or a counter with a session prefix).
- The server remembers each `msg_id` for `limits.msg_id_ttl_s` seconds (600 by default, sent in `hello`).
- A message resent with a known `msg_id` is not processed again. The server replies `ack` with `duplicate: true` and the same `build_id`/`edit_id` as the first ack.
- So a client may resend any message whose ack it did not see (for example after a reconnect) without creating a second build or applying an edit twice.

### 8.7 Edit lifecycle

1. Client sends `edit.apply` with `base_revision` set to the revision it shows. Edit controls stay disabled until `build.done`.
2. Server sends `ack`. `accepted: true` means parsed and queued (not yet applied), with an `edit_id`. `accepted: false` carries an `error` (for example `E_BUILD_NOT_READY`, `E_BAD_MESSAGE`); nothing else follows.
3. Server validates the whole edit first (every op, then every critical and error check on the result).
4. Accepted path: `stage.started` (edit), then granular events (part.*, connection.*, placement.updated, enclosure.updated, board.updated, layout.added, check.result, warning), each with `cause.edit_id` and the new `revision`, then `stage.completed` (edit, ok), then `edit.applied` with the new `revision`.
5. Rejected path: `stage.started` (edit), `stage.completed` (edit, status `failed`), then `edit.rejected` with `error`, `failed_checks` and up to 4 `suggestions`. No model change events and no `check.result` are sent. `revision` does not change.
6. The p95 budget from `edit.apply` sent to `edit.applied` received is 50 ms of server time (section 12).

Example `edit.apply`, from `edit_swap_switches`:

```json
{
  "spec_version": "1.1.0",
  "type": "edit.apply",
  "msg_id": "m_edit_swap_01",
  "ts": "2026-10-24T20:00:20.267Z",
  "payload": {
    "build_id": "b_exact001A",
    "base_revision": 1,
    "ops": [
      {
        "op": "swap_part",
        "instance_id": "u_sw_l",
        "part_id": "sw:cherry_mx2a_brown"
      },
      {
        "op": "swap_part",
        "instance_id": "u_sw_r",
        "part_id": "sw:cherry_mx2a_brown"
      }
    ]
  }
}
```

`edit.applied`:

```json
{
  "spec_version": "1.1.0",
  "type": "edit.applied",
  "seq": 68,
  "build_id": "b_exact001A",
  "ts": "2026-10-24T20:00:20.295Z",
  "revision": 2,
  "cause": {
    "msg_id": "m_edit_swap_01",
    "edit_id": "ed_1"
  },
  "payload": {
    "edit_id": "ed_1",
    "msg_id": "m_edit_swap_01",
    "ops": [
      {
        "op": "swap_part",
        "instance_id": "u_sw_l",
        "part_id": "sw:cherry_mx2a_brown"
      },
      {
        "op": "swap_part",
        "instance_id": "u_sw_r",
        "part_id": "sw:cherry_mx2a_brown"
      }
    ],
    "revision": 2,
    "duration_ms": 21
  }
}
```

`edit.rejected`, from `edit_rejected_choc`:

```json
{
  "spec_version": "1.1.0",
  "type": "edit.rejected",
  "seq": 65,
  "build_id": "b_exact001A",
  "ts": "2026-10-24T20:00:20.280Z",
  "cause": {
    "msg_id": "m_edit_choc_01",
    "edit_id": "ed_1"
  },
  "payload": {
    "edit_id": "ed_1",
    "msg_id": "m_edit_choc_01",
    "error": {
      "code": "E_INCOMPATIBLE",
      "message": "Kailh Choc v1 Red does not fit the left PCB's MX sockets.",
      "retryable": false,
      "stage": "edit",
      "subjects": [
        {
          "instance_id": "u_sw_l"
        },
        {
          "part_id": "sw:kailh_choc_red"
        }
      ],
      "details": {
        "rule_id": "mech.switch.family_match"
      }
    },
    "failed_checks": [
      {
        "check_key": "mech.switch.family_match:u_sw_l",
        "rule_id": "mech.switch.family_match",
        "status": "fail",
        "severity": "critical",
        "message": "Choc v1 switches do not fit the Corne's MX hotswap sockets.",
        "subjects": [
          {
            "instance_id": "u_sw_l"
          },
          {
            "instance_id": "u_pcb_l"
          }
        ],
        "measured": "choc_v1",
        "limit": "mx",
        "fix_hint": "Pick an MX switch, or start a Choc build.",
        "stage": "edit"
      }
    ],
    "suggestions": [
      {
        "suggestion_id": "sg1",
        "kind": "edit",
        "label": "Use Cherry MX2A Brown instead",
        "prompt": null,
        "ops": [
          {
            "op": "swap_part",
            "instance_id": "u_sw_l",
            "part_id": "sw:cherry_mx2a_brown"
          }
        ],
        "design_id": null
      },
      {
        "suggestion_id": "sg2",
        "kind": "prompt",
        "label": "Build a Choc split keyboard",
        "prompt": "a split keyboard with Choc switches",
        "ops": null,
        "design_id": null
      }
    ]
  }
}
```

### 8.8 Connection, keepalive and reconnect

Owned by C26 ConnectionBanner.

- Keepalive: the client sends `ping` every 15 s. If no `pong` arrives within 10 s, the client treats the socket as dead, closes it, and reconnects.
- Backoff: reconnect after 0.5, 1, 2, 4, 8 s, then every 8 s, with up to 20 percent random jitter. Reset to 0.5 s after `hello`.
- Resume: after `hello` on the new socket, if a build is open in the store, send `build.resume` with `build_id` and `last_seq` (the highest build seq applied). The server then either replays every event with seq greater than `last_seq` in order, or, when those events are no longer kept, sends `error` with `E_RESUME_GAP` followed by `build.snapshot` (reason `resume_gap`). After a snapshot, the client replaces the whole build in its store and continues with seq greater than `build.last_seq`.
- Gap detection: if a build event arrives with seq greater than last applied seq + 1, the client stops applying events for that build and sends `build.resume` with its last applied seq.
- Duplicate detection: a build event with seq less than or equal to the last applied seq is dropped.
- Unacked messages: after resume, the client resends any message (same `msg_id`) it never saw an `ack` for. Section 8.6 makes this safe.
- REST fallback: `GET /v1/builds/{id}` (full state) and `GET /v1/builds/{id}/events?after_seq=N` (replay) give the same data when the socket cannot connect.

### 8.9 Cancel

`build.cancel` while a build runs: `ack`, then the open stage completes with status `failed`, then `build.failed` with `E_CANCELLED`. The store sets status `cancelled`. Cancel after a terminal event is acked and ignored.

### 8.10 Examples

`hello`:

```json
{
  "spec_version": "1.1.0",
  "type": "hello",
  "seq": 0,
  "build_id": null,
  "ts": "2026-10-24T20:00:00.020Z",
  "payload": {
    "server_version": "0.1.0",
    "session_id": "s_demo01",
    "mock": true,
    "limits": {
      "max_prompt_chars": 2000,
      "max_ops_per_edit": 20,
      "msg_id_ttl_s": 600
    },
    "capabilities": [
      "compile",
      "solver"
    ]
  }
}
```

`build.start`:

```json
{
  "spec_version": "1.1.0",
  "type": "build.start",
  "msg_id": "m_exact_start_01",
  "ts": "2026-10-24T20:00:00.020Z",
  "payload": {
    "prompt": "a keyboard",
    "options": {
      "force_tier": null,
      "commercial_only": false,
      "seed": null
    }
  }
}
```

`ack`:

```json
{
  "spec_version": "1.1.0",
  "type": "ack",
  "seq": 0,
  "build_id": "b_exact001A",
  "ts": "2026-10-24T20:00:00.028Z",
  "payload": {
    "msg_id": "m_exact_start_01",
    "accepted": true,
    "duplicate": false,
    "build_id": "b_exact001A",
    "edit_id": null,
    "error": null
  }
}
```

First `stage.started`:

```json
{
  "spec_version": "1.1.0",
  "type": "stage.started",
  "seq": 1,
  "build_id": "b_exact001A",
  "ts": "2026-10-24T20:00:00.033Z",
  "stage": "classify",
  "payload": {
    "stage": "classify",
    "label": "Understanding the request",
    "budget_ms": 50
  }
}
```

### 8.11 Clarify

The engine asks a question instead of guessing when a wrong guess would change the device. Owned by C30 ClarifyCard.

When classify asks: the classifier answers one test, "would two competent builders reading this request build devices that do the same job?" If not, it names exactly one blocking facet (`Spec.ambiguity.blocking_facet`, a `ClarifyFacet` listed in `x-blocking`):

- `primary_function`: the words give only a mood, place, recipient or vague wish, not a job ("something cool for my desk", "a thing for my dog").
- `which_device`: two or more unrelated devices offered as alternatives.
- `sensed_quantity`: a monitor or sensor where nothing says what it measures ("a monitor for my room").
- `controlled_output`: a controller where nothing says what it controls.

Rules:

- When the user says what the device senses or does and what it shows, signals or controls, nothing is blocking, however many details are missing.
- Defaultable facets (`power_source`, `connectivity`, `size`, `colour`, `layout`, `mounting`, `display_type`, `input_method`, `quantity`, `enclosure`) never block. The engine assumes a safe default (USB power, gray case, no radio unless a phone or the internet is implied) and records an `Assumption`.
- A request for a named product never blocks. If the reuse test (section 8.12) finds a catalog design that does the same job, any blocking facet is cleared.
- One question per round, at most 2 rounds.
- Out of scope (not buildable from hobby electronics and printed or off-the-shelf mechanical parts, physically impossible, or needing a regulated or unsafe capability such as medical diagnosis, weapons, jamming, mains appliances (whose own circuit switches, heats or drives mains power; a product running on low voltage behind a wall adapter or certified AC-DC module is in scope) or rideable vehicles): no question; `build.failed` with `E_OUT_OF_SCOPE` and `Spec.scope out_of_scope`. A vague request is never out of scope; it gets a question.

Flow:

1. classify ends with `stage.completed` status `needs_input` (no `spec.ready`).
2. `clarify.request` (build scope, no stage): `question_id`, `question`, 2 to 4 `options` (each with `option_id`, `label`, optional `description` and `implies` requirements), `allow_free_text`, `allow_skip`, `default_option_id` (the best guess), `reason`, `missing_facets`, `timeout_ms` (default 60000), `round` (1 or 2).
3. The client sends `clarify.answer` with `build_id`, `question_id` and exactly one of `option_id`, `free_text` or `skip: true`. Free text that only asks the engine to choose ("just pick", "whatever", "you decide") counts as skip.
4. The server acks (errors: `E_CLARIFY_NOT_PENDING` when nothing is open or the id is stale; `E_INVALID_ANSWER` for an option not offered, or free text when `allow_free_text` is false), then sends `clarify.resolved` with `resolution` `answered_option`, `answered_text`, `skipped` or `timeout`.
5. Skip and timeout: the engine uses `default_option_id` and states what it assumed in `assumptions`; the same assumptions appear in `Spec.assumptions` and in a `warning` with code `assumption_made`. A build is never blocked forever: after `timeout_ms` with no answer the server resolves with `timeout`.
6. classify starts again (`stage.started` classify, `cause.msg_id` = the answer) and either asks round 2 or sends `spec.ready`. After round 2 the engine always builds its best guess.
7. `build.cancel` while waiting: `ack`, then `build.failed` with `E_CANCELLED` (no stage is open, so no `stage.completed`).

Example `clarify.request` (from `clarify_vague_gadget`):

```json
{
  "spec_version": "1.1.0",
  "type": "clarify.request",
  "seq": 3,
  "build_id": "b_clarify01A",
  "ts": "2026-10-24T20:00:00.076Z",
  "payload": {
    "question_id": "q_function",
    "question": "What should it do?",
    "round": 1,
    "options": [
      {
        "option_id": "o_weather",
        "label": "Show the weather in the room",
        "description": "Temperature and humidity on a small screen.",
        "implies": [
          {
            "req_id": "r1",
            "facet": "measures",
            "op": "has",
            "value": "temperature",
            "unit": null,
            "source": "clarified",
            "text_span": null,
            "label": "Shows temperature and humidity"
          }
        ]
      },
      {
        "option_id": "o_clock",
        "label": "Be a clock",
        "description": "Time on a small display, synced over Wi-Fi.",
        "implies": []
      },
      {
        "option_id": "o_plant",
        "label": "Watch a plant",
        "description": "Soil moisture with a light when it needs water.",
        "implies": []
      },
      {
        "option_id": "o_light",
        "label": "Be a desk light",
        "description": "Colour LEDs you can change.",
        "implies": []
      }
    ],
    "allow_free_text": true,
    "allow_skip": true,
    "default_option_id": "o_weather",
    "reason": "No device function in the prompt, and four common desk devices fit equally well.",
    "missing_facets": [
      "function"
    ],
    "timeout_ms": 60000
  }
}
```

### 8.12 Route derivation

The tier is derived in code from Spec fields. No device-specific code: design names, aliases and cards are catalog data loaded at run time, never written into router logic or prompts. v1.1.1 changes the server's internal order to fix every unambiguous held-out miss from the 10-18 paper eval (eval/rounds.md); no field or event changes shape.

**Stage 0, deterministic, before any model call (target under 30 ms):**

- Name match: normalize the prompt (lowercase, strip punctuation and the words "kit", "build", "style", "like a") and look for any catalog design `name` or `aliases` entry, exact first, then token-set fuzzy at 0.9 or above. A hit is passed to the reuse check as candidate 1 and records the matched text.
- Design shortlist: embedding kNN of the prompt against the design cards, top 3 above a similarity floor, added after the name match (deduplicated). The reuse check sees this shortlist, never one design.

**Stage 1, classify (one model call, enum-constrained JSON):** fills `scope`, `functions`, `main_purpose`, `hard_requirements`, `ambiguity.blocking_facet` exactly as before.

**Stage 2, reuse check (second model call, runs whenever the shortlist is non-empty):** sees the request and the shortlist cards only. Answers, per card, "same kind of device doing the same core job?" and picks at most one `candidate_design_id`. `changes_needed` is then computed in code: every hard requirement the chosen design's default build does not meet (from its card facets) becomes a change; the model fills a change only where the card has no value for that facet.

**Derivation, in this order:**

1. `scope` is `out_of_scope` and `functions` is non-empty: reject (`E_OUT_OF_SCOPE`). A request that names a job the engine must not do (medical diagnosis, weapons, jamming, mains, rideable) is rejected, not questioned. (Held-out miss q217.)
2. `ambiguity.blocking_facet` set: clarify (section 8.11), unless one of these clears it in code:
   - a name match exists and the reuse check accepted it;
   - `functions` holds at least one input-side function (`sense.*` or `input.*`) and at least one output-side function (`display.*`, `output.*` or `comms.*`). The user has said what it senses and what it does, so the section 8.11 rule "nothing is blocking" applies by construction instead of by model judgement. (Held-out misses q074, q248.)
3. `scope` is `out_of_scope` with no functions: clarify with facet `primary_function` (a vague request is never rejected).
4. Reuse check accepted a candidate: `exact` when `changes_needed` is empty, else `substitute`.
5. A name match exists but the reuse check rejected every card: `substitute` from the name-matched design when its device class equals `device_class`, else `compose`. Naming a product is the strongest signal of intent; adapting it beats building fresh. (Held-out misses q267, q278.)
6. Otherwise: `compose`.

`main_purpose` states the core job without the user's tweaks, so "a Corne but wireless" is still a split keyboard and reaches `substitute`. A candidate covers the main purpose only when it is the same kind of device doing the same job: shared parts never qualify, and a firmware-only design never covers a request for hardware. When classify and the reuse check disagree on whether any design fits, the build composes, except for rule 5: a wrong compose costs time, a wrong reuse ships the wrong device.

Latency: stage 0 is local; the two model calls run in parallel when stage 0 already has a shortlist (the reuse check does not need classify's output except `hard_requirements`, which only feeds the code step after both return). Target p50 under 1.5 s on Cerebras, down from 2.4 s sequential on the gpt-4.1-mini stand-in.

**Acceptance (measured at the event):** these fixes were designed by reading the 10-18 held-out misses, so that held-out set is now spent and only counts as tuning data. Before Friday a fresh blind held-out of 100 prompts is written (same 7 personas, same route mix, labelled twice blind, frozen with a sha1 before the router exists), and it is run once, after tuning freezes. Targets: route accuracy >= 90% on the 304 tuning prompts and >= 88% on the fresh held-out; 0 novel-to-reuse leaks; clarify precision >= 80%; p50 under 1.5 s. On the old held-out the paper fixes would turn the 6 unambiguous misses (q074, q099, q217, q248, q267, q278) into hits (88.0% to about 94.6%) and lift clarify precision from 9 of 14 to 9 of 11, which is an upper bound, not a forecast.

## 9. Client store and reducer rules

The frontend keeps one Build object per build_id, the same shape as `build.schema.json`. Applying every event of a build in seq order with the rules below must produce exactly the body of `GET /v1/builds/{id}` (contract test C6).

| Message | Store change |
|---|---|
| `ack` for a `build.start` | Create the Build: `build_id` from the ack, `prompt` from the build.start, `status: running`, `revision: 0`, `tier: unknown`, `spec`, `design_id`, `firmware`, `scene`, `error` null, every list empty, `timings_ms: {}`, `clarify: null`, `clarifications: []`, `last_seq: 0`. |
| any connection-scoped event | No build change. |
| `build.snapshot` | Replace the whole Build with `payload.build`. |
| `spec.ready` | `spec = payload.spec`. |
| `reuse.decided` | `tier`, `design_id` from the payload. |
| `slots.ready` | `slots = payload.slots`. |
| `slot.updated` | Replace the slot with the same `slot_id` (append when new). |
| `candidates.ready` | No Build change (view state for C06 only). |
| `decision.made` | Replace or append in `decisions` by `decision_id`. |
| `decision.reverted` | Remove that `decision_id` from `decisions`. |
| `layout.added` | Replace or append in `layouts` by `layout_id`. |
| `part.added`, `part.updated` | Replace or append in `parts` by `instance_id`. |
| `part.removed` | Remove that `instance_id` from `parts`. |
| `connection.added` | Replace or append in `connections` by `connection_id`. |
| `connection.removed` | Remove that `connection_id`. |
| `placement.updated` | For each entry, set `parts[instance_id].placement`. |
| `enclosure.updated` | Replace or append in `enclosures` by `enclosure_id`. |
| `board.updated` | Replace or append in `boards` by `board_id`. |
| `firmware.ready` | `firmware = payload.firmware`. |
| `scene.ready` | `scene = payload.scene`. |
| `check.result` | For each result, replace or append in `checks` by `check_key`. |
| `warning` | Replace or append in `warnings` by `warning_id`. |
| `stage.started`, `stage.progress` | No Build change (view state for C04). |
| `stage.completed` | When `stage` is not `edit`: `timings_ms[stage] = duration_ms`. |
| `clarify.request` | `clarify = payload`; `status = awaiting_input`. |
| `clarify.resolved` | Append the payload to `clarifications`; `clarify = null`; `status = running`. |
| `firmware.progress` | No Build change (view state for C16; the final state comes in `firmware.ready`). |
| `build.done` | `status = done`. |
| `build.failed` | `status = cancelled` when the code is `E_CANCELLED`, else `failed`; `error = payload.error`; `clarify = null`. |
| `edit.applied`, `edit.rejected` | No Build change beyond the envelope rules (view state for C19). |
| every build-scoped event | Afterwards: when the envelope has `revision`, set `revision`; set `last_seq = seq`. |
| unknown event type | No change; log in C29. |

View state that is not part of Build (stage status per stage, candidate lists per slot, the edit currently pending, selection, explode amount, camera) lives in separate UI stores and is rebuilt from the same events.

## 10. Error codes

`ErrorObject` (section 4.10) is the error body everywhere: REST responses with status >= 400, the `error` event, `ack` with `accepted: false`, `edit.rejected` and `build.failed`. A code the client does not know is treated as `E_UNKNOWN`.

| Code | HTTP | Retryable | Arrives in | Meaning | UI action |
|---|---|---|---|---|---|
| `E_BAD_MESSAGE` | 400 | no | error, ack | Message is not valid JSON or fails its schema. | Log it; this is a client bug. |
| `E_UNSUPPORTED_VERSION` | 400 | no | error, ack | spec_version major is not 1. | Show a full screen 'reload the app' notice. |
| `E_NOT_FOUND` | 404 | no | REST | Path or resource does not exist. | Show an empty state. |
| `E_UNKNOWN_BUILD` | 404 | no | REST, ack | No build with this build_id. | Go to Home. |
| `E_BUILD_NOT_READY` | 409 | yes | ack, edit.rejected | edit.apply sent before build.done. | Keep edit controls disabled until build.done. |
| `E_STALE_REVISION` | 409 | yes | edit.rejected | base_revision is not the current revision. | Refetch nothing; the events already arrived. Let the user retry. |
| `E_UNKNOWN_PART` | 404 | no | REST, edit.rejected | part_id not in the catalog. | Toast. |
| `E_UNKNOWN_INSTANCE` | 409 | no | edit.rejected | instance_id not in the build. | Toast; the store is stale, so request build.resume. |
| `E_UNKNOWN_INTERFACE` | 409 | no | edit.rejected | interface_id not on that part. | Toast. |
| `E_INVALID_EDIT` | 400 | no | edit.rejected | Op is malformed, unknown, or not allowed on that target. | Toast. |
| `E_INCOMPATIBLE` | 409 | no | edit.rejected | The edit would fail a critical or error check. | EditStatus shows failed_checks and suggestions. |
| `E_CRITICAL_PART_MISSING` | 422 | no | build.failed, edit.rejected | A critical slot has no part that meets the requirements. | FailureCard with conflict and suggestions. |
| `E_CLASSIFY_FAILED` | 422 | no | build.failed | The prompt maps to no device class. | FailureCard asks for a rephrase; show ExampleChips. |
| `E_LLM_UNAVAILABLE` | 503 | yes | build.failed, warning | Every model provider failed. | FailureCard with Retry. |
| `E_LLM_TIMEOUT` | 504 | yes | build.failed | Model call over its deadline after the fallback. | FailureCard with Retry. |
| `E_SOLVER_INFEASIBLE` | 422 | no | build.failed, edit.rejected | Placement has no solution (parts cannot fit). | FailureCard or EditStatus. |
| `E_SOLVER_TIMEOUT` | 504 | yes | build.failed | Solver over its deadline with no feasible answer. | FailureCard with Retry. |
| `E_ENCLOSURE_FAILED` | 500 | yes | build.failed, edit.rejected | Manifold could not build the case. | FailureCard or EditStatus. |
| `E_BOARD_FAILED` | 500 | yes | build.failed | Board generation failed. | FailureCard. |
| `E_FIRMWARE_FAILED` | 500 | yes | build.failed | No firmware could be produced (compile failures are fw.compile checks, not this). | FailureCard. |
| `E_ASSET_MISSING` | 404 | no | warning, REST | A referenced asset file does not exist. | Viewport draws the bbox placeholder. |
| `E_LICENCE_BLOCKED` | 422 | no | build.failed, edit.rejected | commercial_only removed every candidate for a critical slot. | FailureCard suggests turning commercial_only off. |
| `E_RESUME_GAP` | 409 | no | error | Events after last_seq are no longer kept. | Wait for the build.snapshot that follows. |
| `E_CANCELLED` | 409 | no | build.failed | The client sent build.cancel. | Return to the prompt, no error styling. |
| `E_CLARIFY_NOT_PENDING` | 409 | no | ack | clarify.answer sent with no open question, or with a question_id that is not the open one. | Close ClarifyCard; the store already has the resolution. |
| `E_INVALID_ANSWER` | 400 | no | ack | clarify.answer option_id is not one of the question's options, or free text is not allowed. | Keep ClarifyCard open and show the message inline. |
| `E_OUT_OF_SCOPE` | 422 | no | build.failed | The request cannot be built from electronics and printable parts (reject route). | FailureCard says why and shows ExampleChips. |
| `E_RATE_LIMITED` | 429 | yes | ack, REST | Too many builds or messages. | Toast; retry after details.retry_after_ms. |
| `E_INTERNAL` | 500 | yes | any | Server bug. | Generic error state with Retry. |
| `E_UNKNOWN` | 500 | yes | any | Fallback for codes this client does not know. | Treat as E_INTERNAL. |

## 11. UI screens and components

### 11.1 Screens

- Home: TopBar (C01), centred PromptBar (C02), ExampleChips (C03) below it. Sending a prompt moves to Workspace immediately (on `ack`), so the first events render there.
- Workspace, three columns:
  - Left (about 320 px): StageTimeline (C04), SpecCard (C07), ReuseCard (C08), DecisionTrace (C06), scrolls as one column.
  - Centre: Viewport3D (C10) filling the space, with LatencyHUD (C05) top right, WarningBanner (C18) top, ViewportToolbar (C11) bottom, EditStatus (C19) bottom centre, FailureCard (C25) centred when the build fails, PromptBar (C02) docked at the bottom for the next prompt.
  - Right (about 360 px), tabs: Parts (C09), Connections (C14), Board (C15), Firmware (C16), Checks (C17). The tab badge shows the count of failing checks for that area.
  - Overlays: PartInspector (C12), SwapDrawer (C13), ResizePanel (C21) slide over the right column; ConnectDialog (C23) and AddPartPicker (C28) are modals; ColorPicker (C22) is a popover; MoveGizmo (C20) lives in the viewport.
- Disconnected overlay: C26 shows a top banner while reconnecting or resyncing and keeps the last state visible (no blank screen). Edit controls are disabled until resync completes.
- Debug: C29 EventLog drawer, toggled with the L key.

Selection is shared UI state: selecting an instance in C09, C10, C17 or C06 selects it everywhere and opens C12.

### 11.2 Component inventory

The Etch panel id column names the matching element in the Etch studio UI, so naming stays consistent with Nithin's existing work.

| ID | Component | Etch panel id | Where | States | Consumes (server events) | Sends (client messages) | REST | Behaviour |
|---|---|---|---|---|---|---|---|---|
| C01 | TopBar | top / home | all screens | idle, running, done, failed | `hello`, `build.done`, `build.failed` | none | `GET /v1/health` | App name (Bara), connection pill (from C26), build id, Home button, ExportMenu trigger. |
| C02 | PromptBar | dock / ask / send | Home center, Workspace bottom dock | empty, typing, submitting, running (shows Stop), done (new prompt) | `ack`, `build.done`, `build.failed` | `build.start`, `build.cancel` | none | Enter sends build.start. While running the send button becomes Stop (build.cancel). Disabled until hello. |
| C03 | ExampleChips | home | Home | static | none | `build.start` | none | One chip per demo prompt: the match_prompts of each stream fixture. |
| C04 | StageTimeline | log (top strip) | Workspace left | per stage: pending, active, ok, skipped, degraded, failed | `stage.started`, `stage.progress`, `stage.completed`, `build.done`, `build.failed` | none | `GET /v1/vocab (labels, budgets)` | Eight build stages in pipeline order; the edit stage shows only in C19. Active stage shows elapsed ms against budget_ms. |
| C05 | LatencyHUD | hud | Viewport top right | hidden, live, final | `stage.completed`, `decision.made`, `build.done` | none | none | Per stage ms and total; model latency from decision.model. Demo element: shows the time to first part. |
| C06 | DecisionTrace | log | Workspace left | per slot: pending, narrowing, decided, none, dead_end | `slots.ready`, `slot.updated`, `candidates.ready`, `decision.made`, `decision.reverted` | none | none | One row per slot in order. Narrowing shows filter chips with count_before to count_after. Decided shows the chosen card and reason; model picks show the C1..C8 list with the winner. Click a candidate to open C12 for that part. |
| C07 | SpecCard | specs / specrow | Workspace left | empty, ready | `spec.ready` | none | none | Device class, taxonomy path, requirement chips (hard solid, soft outline). Hover a chip highlights text_span in the prompt. |
| C08 | ReuseCard | specs | Workspace left | empty, exact, substitute, compose | `reuse.decided` | none | `GET /v1/designs/{id}` | Tier badge, design card, considered designs with unmet requirement chips, reason. |
| C09 | PartsList | specs (Parts tab) | Workspace right, Parts tab | empty, filling, done | `part.added`, `part.updated`, `part.removed`, `check.result`, `warning` | `edit.apply (remove_part)` | `GET /v1/builds/{id}/export?format=bom_csv` | Grouped by slot, quantity, status dot from checks on that instance, ProvenanceBadge. Row click selects the instance. Add part opens C28. |
| C10 | Viewport3D | view / gl | Workspace center | empty, loading, provisional, assembled, exploded, failed | `layout.added`, `part.added`, `part.updated`, `part.removed`, `placement.updated`, `enclosure.updated`, `board.updated`, `scene.ready`, `check.result` | none | `GET /assets/...` | React Three Fiber scene in build space (section 3.2). Parts appear at their poses as part.added arrives; before place completes they render at 50 percent opacity. Instances with a failing check get a red outline. Click selects. |
| C11 | ViewportToolbar | view | Viewport bottom | local only | `scene.ready` | none | none | Explode slider 0 to 1, view presets (iso, top, front, side), toggles: case, board, keycaps, labels. Reset camera to scene.camera. |
| C12 | PartInspector | card (ref, val, why, meta) | Right overlay | closed, loading, open | `part.updated`, `part.removed`, `decision.made`, `check.result` | `edit.apply (remove_part)` | `GET /v1/parts/{part_id}` | ref = instance label, val = display name and key specs, why = decision reason, meta = interfaces, licence, provenance, datasheet. Buttons: Swap (opens C13), Recolor (C22), Move (C20), Remove. |
| C13 | SwapDrawer | card | Right overlay | closed, loading, list, applying, rejected | `edit.applied`, `edit.rejected` | `edit.apply (swap_part)` | `GET /v1/builds/{id}/slots/{slot_id}/alternatives` | Lists alternatives; incompatible ones are greyed with their failed checks. Click a compatible one to send swap_part. |
| C14 | ConnectionView | specs (Connections tab) | Workspace right, Connections tab | empty, list | `connection.added`, `connection.removed`, `check.result` | `edit.apply (disconnect)` | none | Rows: from, to, type, resolved params (address, rail), status. Hover highlights both ends in C10. New connection opens C23. |
| C15 | BoardView | specs (Board tab) | Workspace right, Board tab | empty, pending, ok, failed | `board.updated` | none | none | 2D outline, nets, routing status, DRC. Download kicad_pcb from assets. |
| C16 | FirmwareView | specs (Firmware tab) | Workspace right, Firmware tab | empty, ready, compiling, compiled, compile_failed, skipped | `firmware.ready`, `firmware.progress` | none | none | File tree with read only code view, pin map table, compile status, binary download buttons. Badge shows firmware.mode: Prebuilt (the design's own binary) or Compiled live; while compiling, a progress bar follows firmware.progress phase and fraction. |
| C17 | ChecksPanel | checks / cklist | Workspace right, Checks tab | empty, list | `check.result` | none | none | Grouped fail, unknown, pass; sorted by severity. Click selects the subjects in C10. Shows fix_hint. |
| C18 | WarningBanner | checks | Viewport top | hidden, shown | `warning` | none | none | Stacked warnings, highest severity first, dismissible per warning_id. |
| C19 | EditStatus | log (toast) | Viewport bottom center | hidden, pending, applying, applied, rejected | `ack`, `stage.started`, `stage.completed`, `edit.applied`, `edit.rejected` | `edit.apply (suggestion ops)`, `build.start (suggestion prompt)` | none | Tracks the edit by msg_id and edit_id. Rejected shows the error, failed checks and suggestion buttons. |
| C20 | MoveGizmo | view | Viewport, on the selected instance | hidden, dragging, committing | `placement.updated` | `edit.apply (move)` | none | Translate and rotate handles. Sends one move op with mode absolute on drag end, lock true. Shows the dragged pose locally until placement.updated or edit.rejected. |
| C21 | ResizePanel | specs | Right overlay | closed, open, applying | `enclosure.updated`, `board.updated` | `edit.apply (resize)` | none | Sliders for wall_mm, fillet_mm, clearance_mm, height_mm and the split select. Sends on release. |
| C22 | ColorPicker | card | Popover | closed, open | `part.updated`, `enclosure.updated` | `edit.apply (recolor)` | none | Swatches plus hex input and material select. |
| C23 | ConnectDialog | card | Modal | closed, picking_from, picking_to, applying, rejected | `connection.added`, `edit.rejected` | `edit.apply (connect)` | `GET /v1/parts/{part_id} (interfaces)` | Pick two ports by clicking interfaces in C12 or C10. |
| C24 | ExportMenu | top | TopBar menu | disabled (until build.done), ready | `build.done` | none | `GET /v1/builds/{id}/export` | BOM CSV, STL, 3MF, STEP, KiCad, firmware zip, everything zip. |
| C25 | FailureCard | card | Viewport center | hidden, shown | `build.failed` | `build.start (suggestion prompt)` | none | Error message, the minimal conflict as chips (each chip is a requirement), explanation, suggestion buttons. |
| C26 | ConnectionBanner | top | Top of screen | connecting, open, reconnecting, resyncing, offline | `hello`, `pong`, `error`, `build.snapshot` | `ping`, `build.resume` | none | Owns the socket: keepalive, backoff, resume. See 8.8. |
| C27 | ProvenanceBadge | meta | Inside C06, C09, C12, C13 | verified, third_party, unverified, licence_warning | none | none | none | Pure view of PartCard.verified, licence_spdx and commercial_ok. No events of its own. |
| C28 | AddPartPicker | ask | Modal from C09 | closed, searching, results, applying | `edit.applied`, `edit.rejected` | `edit.apply (add_part)` | `GET /v1/parts` | Search the catalog, pick a part, optional slot. |
| C30 | ClarifyCard | card / ask | Workspace left, above SpecCard (Home: under PromptBar) | hidden, asking, sending, resolved, timed_out | `clarify.request`, `clarify.resolved`, `ack`, `build.failed` | `clarify.answer`, `build.cancel` | none | Shows the question, 2 to 4 option buttons, a free text field when allow_free_text, a Just pick button when allow_skip, and a countdown from timeout_ms. Sends clarify.answer once; disables until ack. On clarify.resolved shows the chosen option or the stated assumptions as chips, then collapses. Closes on build.failed (cancel). |
| C29 | EventLog | log | Debug drawer (key L) | collapsed, open | `*` | none | none | One line per message received or sent, including unknown types. For the demo and for debugging contract drift. |

### 11.3 Event to component mapping

Every server event and every client message has at least one owner. Generated from the table above; the generator fails if any event or message is unowned.

| Server event | Scope | Components that consume it (C29 EventLog consumes every event) |
|---|---|---|
| `hello` | connection | C01 TopBar, C26 ConnectionBanner |
| `ack` | connection | C02 PromptBar, C19 EditStatus, C30 ClarifyCard |
| `pong` | connection | C26 ConnectionBanner |
| `error` | connection | C26 ConnectionBanner |
| `build.snapshot` | build | C26 ConnectionBanner |
| `stage.started` | build | C04 StageTimeline, C19 EditStatus |
| `stage.progress` | build | C04 StageTimeline |
| `stage.completed` | build | C04 StageTimeline, C05 LatencyHUD, C19 EditStatus |
| `clarify.request` | build | C30 ClarifyCard |
| `clarify.resolved` | build | C30 ClarifyCard |
| `spec.ready` | build | C07 SpecCard |
| `reuse.decided` | build | C08 ReuseCard |
| `slots.ready` | build | C06 DecisionTrace |
| `slot.updated` | build | C06 DecisionTrace |
| `candidates.ready` | build | C06 DecisionTrace |
| `decision.made` | build | C05 LatencyHUD, C06 DecisionTrace, C12 PartInspector |
| `decision.reverted` | build | C06 DecisionTrace |
| `layout.added` | build | C10 Viewport3D |
| `part.added` | build | C09 PartsList, C10 Viewport3D |
| `part.updated` | build | C09 PartsList, C10 Viewport3D, C12 PartInspector, C22 ColorPicker |
| `part.removed` | build | C09 PartsList, C10 Viewport3D, C12 PartInspector |
| `connection.added` | build | C14 ConnectionView, C23 ConnectDialog |
| `connection.removed` | build | C14 ConnectionView |
| `placement.updated` | build | C10 Viewport3D, C20 MoveGizmo |
| `enclosure.updated` | build | C10 Viewport3D, C21 ResizePanel, C22 ColorPicker |
| `board.updated` | build | C10 Viewport3D, C15 BoardView, C21 ResizePanel |
| `firmware.ready` | build | C16 FirmwareView |
| `firmware.progress` | build | C16 FirmwareView |
| `scene.ready` | build | C10 Viewport3D, C11 ViewportToolbar |
| `check.result` | build | C09 PartsList, C10 Viewport3D, C12 PartInspector, C14 ConnectionView, C17 ChecksPanel |
| `warning` | build | C09 PartsList, C18 WarningBanner |
| `build.done` | build | C01 TopBar, C02 PromptBar, C04 StageTimeline, C05 LatencyHUD, C24 ExportMenu |
| `build.failed` | build | C01 TopBar, C02 PromptBar, C04 StageTimeline, C25 FailureCard, C30 ClarifyCard |
| `edit.applied` | build | C13 SwapDrawer, C19 EditStatus, C28 AddPartPicker |
| `edit.rejected` | build | C13 SwapDrawer, C19 EditStatus, C23 ConnectDialog, C28 AddPartPicker |

| Client message | Sent by |
|---|---|
| `build.start` | C02 PromptBar, C03 ExampleChips, C19 EditStatus, C25 FailureCard |
| `build.resume` | C26 ConnectionBanner |
| `edit.apply` | C09 PartsList, C12 PartInspector, C13 SwapDrawer, C14 ConnectionView, C19 EditStatus, C20 MoveGizmo, C21 ResizePanel, C22 ColorPicker, C23 ConnectDialog, C28 AddPartPicker |
| `build.cancel` | C02 PromptBar, C30 ClarifyCard |
| `ping` | C26 ConnectionBanner |
| `clarify.answer` | C30 ClarifyCard |

| Edit op | Sent by |
|---|---|
| `swap_part` | C13 SwapDrawer |
| `connect` | C23 ConnectDialog |
| `disconnect` | C14 ConnectionView |
| `recolor` | C22 ColorPicker |
| `move` | C20 MoveGizmo |
| `resize` | C21 ResizePanel |
| `add_part` | C28 AddPartPicker |
| `remove_part` | C09 PartsList, C12 PartInspector |

### 11.4 Rendering rules shared by components

- Status colours: `pass` and `ok` green, `fail` with severity critical or error red, `warning` amber, `info` and `unknown` grey.
- Provenance (C27): show a check mark when `PartCard.verified` is true, a dashed outline when dims come from a third party, and a licence badge when `commercial_ok` is not `yes`.
- Missing asset: when a GLB fails to load or `asset` is missing, draw the part's `bbox_mm` as a translucent box with its label. Never block the scene on one asset.
- Numbers: show the unit from the field suffix (section 3.1); mm with one decimal, ms as integers.
- Text from the server (labels, reasons, messages, firmware code) is rendered as text, never as HTML.

## 12. Latency budgets and waiting states

Budgets are server side p95 on the Mac mini with a warm cache. They are sent as `budget_ms` in `stage.started` so the UI never hard codes them.

| Step | Budget | Notes | What the UI shows while waiting |
|---|---|---|---|
| socket open to `hello` | 300 ms | through the tunnel | C26 "connecting" |
| `build.start` to `ack` | 50 ms | | PromptBar spinner |
| classify | 50 ms | rules and cache; about 200 ms when a Cerebras call runs; 800 ms when the Anthropic backup (`claude-haiku-5-5`) answers instead (a `llm_fallback` warning is sent, `classifier.fallback` true) | C04 active row with elapsed time; C07 skeleton chips |
| clarify wait | user time, `timeout_ms` (60 s default) | not counted in any stage budget or in the whole build time | C30 ClarifyCard with countdown; C04 shows classify as "needs input"; Viewport stays empty |
| reuse | 30 ms | | C08 skeleton |
| compose | 1500 ms | Cerebras picks about 100 to 300 ms each; independent slots in parallel; the Anthropic backup roughly doubles a pick | C06 rows animate: pending, narrowing (filter chips counting down), decided |
| place | 50 ms | | parts at 50 percent opacity in provisional poses |
| enclose | 100 ms | | case outline as wireframe |
| board | 100 ms | design boards load at once; a new composition is autorouted live (about 1 s), then cached by `routing.cache_key` so a repeat is instant | C15 "pending", then "routing" |
| firmware | 50 ms | template fill only | C16 file tree appears |
| firmware compile | 0 s prebuilt; 4 to 45 s compiled | `mode prebuilt` serves the design binary at once; `mode compiled` runs in the background after `build.done`, off the critical path | C16 badge Prebuilt, or "compiling" with a progress bar from `firmware.progress`; Export firmware disabled until it ends |
| render | 50 ms | | camera eases to `scene.camera` |
| first part on screen | 1 s exact, 2 s compose | from `build.start` | |
| whole build | 1.5 s exact, 3 s compose | from `build.start` to `build.done`, excluding compile | |
| edit | 50 ms | from `edit.apply` to `edit.applied` | C19 "applying"; the dragged or picked change is shown optimistically, then confirmed or rolled back |

When a stage runs past its budget, C04 turns that row amber and the server may send a `slow_stage` warning. Nothing is cancelled automatically. Every model call reports `provider` (and `fallback`) next to its `latency_ms`, so C05 LatencyHUD can show which provider answered. Hard timeouts (5 s per model call, 10 s per stage) end the build with `E_LLM_TIMEOUT` or `E_SOLVER_TIMEOUT`.

## 13. Mock mode

Mock mode lets the frontend run with no backend, from the fixtures alone. The backend has the same switch, for demo safety.

- Turn on with the URL query `?mock=1` or the build variable `VITE_MOCK=1`.
- A fake socket class replaces the WebSocket. It sends the `hello` from the selected fixture, then replays server steps in order, waiting `delay_ms` (times a speed factor; `?mock_speed=0.5` plays twice as fast) before each one.
- At a client step, the replay pauses until the UI sends a message of the same `type`. The mock then rewrites `msg_id` in the following acks, `pong` and `cause` fields to the id the UI actually sent, and continues.
- Fixture choice: the `build.start` prompt is matched case-insensitively against each stream fixture's `match_prompts`; with no match, `compose_wireless_split_oled` is used. `?mock_fixture=<name>` forces one. The backend accepts the same choice through `BuildOptions.mock_fixture`.
- Chained fixtures: a fixture with `requires_fixture` first replays the fixture it names (edit and resume fixtures build on `exact_keyboard`).
- Edits in mock mode: when the UI sends `edit.apply`, the mock picks the edit fixture whose client `edit.apply` has the same op list for the same instance ids; otherwise it plays `edit_rejected_choc` with the rejection message replaced by "not available in mock mode".
- REST in mock mode: requests are answered from `spec/fixtures/rest/` by method and path; anything else returns `rest/error_unknown_build` style `E_NOT_FOUND`.
- Assets: mock mode uses the same `/assets/...` URLs; the frontend serves them from its `public/assets/` folder, which mirrors the backend asset folder.
- Mock mode must render exactly what the real backend renders for the same stream; the UI has no mock-only code paths beyond the fake socket and the REST stub.

## 14. Fixtures

### 14.1 Stream fixtures

`spec/fixtures/<name>.json`, schema `fixture.schema.json#/$defs/StreamFixture`. `steps` is a list of `{dir: "client", msg}` and `{dir: "server", delay_ms, msg}`.

| Fixture | Kind | Prompts that select it | Builds on | Steps | What it exercises |
|---|---|---|---|---|---|
| `clarify_vague_gadget` | stream | `something cool for my desk`, `make me a gadget` | none | 65 | Clarify flow: a vague prompt gets two clarify rounds (one answered, one skipped with a stated assumption), then a compose build with a generated gray case, an autorouted board and a live compile. |
| `compose_wireless_split_oled` | stream | `a wireless split keyboard with an OLED`, `wireless split keyboard with oled` | none | 101 | Compose tier: Corne skeleton, wireless parts chosen slot by slot, optional foam missing, late firmware compile. |
| `edit_rejected_choc` | stream | none (chained) | `exact_keyboard` | 5 | Edit rejected: swapping in Choc v1 switches fails mech.switch.family_match. Nothing changes; revision stays 1. Starts from exact_keyboard. |
| `edit_remove_part` | stream | none (chained) | `exact_keyboard` | 7 | Edit: remove the left OLED (optional slot). connection.removed comes before part.removed. Starts from exact_keyboard. |
| `edit_swap_switches` | stream | none (chained) | `exact_keyboard` | 8 | Edit: swap both switch arrays from Gateron Yellow to Cherry MX2A Brown (same MX family). Starts from exact_keyboard. |
| `exact_keyboard` | stream | `a keyboard`, `keyboard` | none | 65 | Exact tier: an underspecified prompt reuses the Corne by popularity; compose is skipped. |
| `failed_critical_missing` | stream | `a 60% keyboard with Choc switches` | none | 17 | Build failed: the PCB slot dead ends on {60% layout, Choc v1}; minimal conflict and two suggestions. |
| `resume_gap` | stream | none (chained) | `exact_keyboard` | 9 | Reconnect: ping/pong, build.resume with an old last_seq gets E_RESUME_GAP then build.snapshot; a resent resume is acked as duplicate. build.snapshot carries seq equal to build.last_seq and does not advance the sequence. |

Server event types not exercised by any fixture: `decision.reverted`. The UI must still handle them (section 9).

### 14.2 REST fixtures

`spec/fixtures/rest/<name>.json`, schema `fixture.schema.json#/$defs/RestFixture`. `body_def` names the `rest.schema.json` def the body validates against.

| Fixture | Request | Status | Body def | What it shows |
|---|---|---|---|---|
| `rest/alternatives` | GET `/v1/builds/b_exact001A/slots/switches/alternatives?instance_id=u_sw_l` | 200 | Alternatives | Swap drawer contents for the switches slot. |
| `rest/build_exact` | GET `/v1/builds/b_exact001A` | 200 | BuildResponse | GET of the finished exact build. Must equal the result of reducing exact_keyboard (contract test C6). |
| `rest/create_build` | POST `/v1/builds` | 201 | CreateBuildResponse | Create a build over REST (fallback when the WebSocket cannot send build.start). |
| `rest/design` | GET `/v1/designs/corne` | 200 | DesignResponse | Full design record for the Corne. |
| `rest/designs` | GET `/v1/designs?device_class=input_device` | 200 | DesignsPage | Design list. |
| `rest/error_unknown_build` | GET `/v1/builds/b_missing00` | 404 | ErrorResponse | Every non 2xx body is ErrorResponse. |
| `rest/events_failed` | GET `/v1/builds/b_fail0001A/events?after_seq=0` | 200 | EventsPage | Event log replay over REST. |
| `rest/facets` | GET `/v1/facets` | 200 | Facets | Facets the classifier may emit and the catalog can filter on (excerpt). |
| `rest/health` | GET `/v1/health` | 200 | Health | Server health. |
| `rest/part` | GET `/v1/parts/mod%3Anice_nano_v2` | 200 | PartResponse | Full Part record (Etch fields plus the v1 fields). |
| `rest/parts_search` | GET `/v1/parts?q=oled&function=display.oled&limit=20` | 200 | PartsPage | Catalog search for OLED displays. |
| `rest/vocab` | GET `/v1/vocab` | 200 | Vocab | Every enum with display labels. The UI uses these labels instead of hard coding text. |

## 15. Contract test plan

Strict mode: a copy of the schemas where every object with `properties` and no `additionalProperties`/`unevaluatedProperties` gets `unevaluatedProperties: false` (except directly under `if`, `then`, `else`, `allOf`). It catches undeclared fields in our own output. Loose mode is the published schemas.

| ID | Test | Owner | When |
|---|---|---|---|
| C1 | Every schema file is valid draft 2020-12, has the right `$id` and `x-spec-version` | both | each schema change |
| C2 | Every fixture validates in strict mode; every stream message validates against its own event or message def | both | each fixture or schema change |
| C3 | Stream invariants of section 8.5 hold for every fixture (seq, stage windows, references, single terminal event, acks, edit ordering, revision, filter count chains, layout quantity, summary counts) | Pranav | each change |
| C4 | Backend output: a test client runs each fixture prompt against the real server, records the stream, validates it in strict mode and runs C3 on it | Pranav | before each merge to main at the event |
| C5 | Every server-sent enum contains `unknown`; client-only enums do not | both | each schema change |
| C6 | Reducing a recorded stream with the section 9 rules equals `GET /v1/builds/{id}` (fixtures: `exact_keyboard` reduces to `rest/build_exact`; the reduced compose, edit and failed builds validate as Build with the expected revision and status) | both | each change |
| C7 | The UI plays every stream fixture in mock mode end to end with no console errors, and the final store equals the C6 reduction | Nithin | each UI change |
| C8 | Tolerance: replay `exact_keyboard` with an extra unknown field added to every object and one unknown event type inserted; the UI renders the same final state and logs the unknown event | Nithin | once per day at the event |
| C9 | Negative: strict mode rejects an undeclared field and a bad enum value; loose mode accepts the unknown field | both | each schema change |
| C10 | Text: no em or en dashes in `SPEC.md` or `spec/` | both | each change |

| C11 | Clarify: invariant 14 holds; a reduced stream cut right after `clarify.request` has `status awaiting_input` and validates as Build; `clarify.answer` with two answers or none is rejected | both | each change |
| C12 | Coverage: every server event type is consumed by at least one component other than C29, and every client message type is sent by one (checked when SPEC.md is generated) | both | each change |

The v1.1.0 files pass C1, C2, C3, C5, C6 (fixture part), C9, C10, C11 and C12. C4, C7 and C8 run at the event.

## 16. Open questions and decisions

Decided on 2026-10-18 (v1.1.0):

- Decided (name): Bara (Hebrew, "to create", Genesis 1:1), Pranav's pick. The earlier candidates (Fiat, Exploded, Graft, Splice) are dropped.
- Decided (clarify): the engine asks instead of guessing when a wrong guess changes the device (section 8.11). Facts with safe defaults become stated assumptions. "Just pick" builds the best guess with the assumptions shown.
- Decided (case): exact and substitute keep the design's own case (`kind design`). Compose gets a generated blank case in neutral gray, no colours unless the user asks (`color_source`).
- Decided (firmware): prebuilt binaries for known designs (`mode prebuilt`); live compile only when routing sends the build there (`mode compiled`, `firmware.progress`).
- Decided (boards): reused designs keep their own routed board (`routing.method design`); new compositions are autorouted live and cached by exact composition key (`routing.method autorouted`, `routing.cache_key`).
- Decided (`commercial_only`): stays default false. Any licence is allowed in the demo; licence warnings still show.
- Decided (providers): Cerebras primary; Anthropic backup with `claude-haiku-5-5` for fast steps and `claude-sonnet-5-5` only where a stronger step is needed.

Still open:

1. Multi-viewer room (QR code to watch a build on phones): v1 allows a second socket to send `build.resume` with `last_seq: 0` (snapshot reason `late_join`). Do we show it in the demo?

## Appendix A. Schema index

| File | $id | Title | Defs |
|---|---|---|---|
| `spec/schemas/asset.schema.json` | `https://app.invalid/spec/v1/asset.schema.json` | AssetRef | none |
| `spec/schemas/build.schema.json` | `https://app.invalid/spec/v1/build.schema.json` | Build | Build, Placement, PlacementIntent, Layout, BuildPart, Connection, Cutout, Enclosure, Net, Board, Firmware, Warning, Scene |
| `spec/schemas/check.schema.json` | `https://app.invalid/spec/v1/check.schema.json` | CheckResult | none |
| `spec/schemas/common.schema.json` | `https://app.invalid/spec/v1/common.schema.json` | Common definitions | SpecVersion, Id, Slug, BuildId, InstanceId, MsgId, Timestamp, DurationMs, Vec2, Vec3, BBox, HexColor, Material, Color, StageId, Tier, Severity, CheckStatus, TriState, Side, Criticality, Origin, PortRef, Subject, KeySpec |
| `spec/schemas/design.schema.json` | `https://app.invalid/spec/v1/design.schema.json` | Design | DesignCard |
| `spec/schemas/edit.schema.json` | `https://app.invalid/spec/v1/edit.schema.json` | EditOp | EditOp, OpName, SwapPart, Connect, Disconnect, Recolor, Move, Resize, AddPart, RemovePart |
| `spec/schemas/error.schema.json` | `https://app.invalid/spec/v1/error.schema.json` | ErrorObject | ErrorCode |
| `spec/schemas/fixture.schema.json` | `https://app.invalid/spec/v1/fixture.schema.json` | Fixture | StreamFixture, RestFixture |
| `spec/schemas/interface.schema.json` | `https://app.invalid/spec/v1/interface.schema.json` | Interface | none |
| `spec/schemas/part.schema.json` | `https://app.invalid/spec/v1/part.schema.json` | Part | Framework, PartCard |
| `spec/schemas/provenance.schema.json` | `https://app.invalid/spec/v1/provenance.schema.json` | Licence and provenance | Licence, Extractor, Verified, FieldSource, Provenance |
| `spec/schemas/rest.schema.json` | `https://app.invalid/spec/v1/rest.schema.json` | REST bodies | ErrorResponse, Health, PartsPage, PartResponse, Facets, Vocab, DesignsPage, DesignResponse, CreateBuildRequest, CreateBuildResponse, BuildResponse, EventsPage, Alternatives |
| `spec/schemas/slot.schema.json` | `https://app.invalid/spec/v1/slot.schema.json` | Slot, candidates and decisions | SlotState, Slot, Filter, Candidate, Decision |
| `spec/schemas/spec.schema.json` | `https://app.invalid/spec/v1/spec.schema.json` | Spec | RequirementSource, Requirement, ClarifyOption, ClarifyQuestion, ClarifyResolution, Assumption |
| `spec/schemas/vocab.schema.json` | `https://app.invalid/spec/v1/vocab.schema.json` | Closed vocabularies v1 | FunctionId, DeviceClass, Role, InterfaceType, Rail, SwitchFamily, Screw, Face, Params_power_in, Params_power_out, Params_gpio, Params_analog, Params_i2c, Params_spi, Params_uart, Params_i2s, Params_usb, Params_qwiic, Params_radio, Params_module_footprint, Params_switch_socket, Params_switch_stem, Params_plate_cutout, Params_layout, Params_stabilizer, Params_mounting_holes, Params_fastener, Params_battery, Params_addressable_led, Params_motor, Params_jack, Params_panel_access, Params_other, Params_unknown, ClarifyFacet |
| `spec/schemas/ws_client.schema.json` | `https://app.invalid/spec/v1/ws_client.schema.json` | WebSocket client messages | BuildOptions, C_build_start, C_build_resume, C_edit_apply, C_build_cancel, C_ping, C_clarify_answer |
| `spec/schemas/ws_envelope.schema.json` | `https://app.invalid/spec/v1/ws_envelope.schema.json` | WebSocket envelopes | ClientEnvelope, ServerEnvelope |
| `spec/schemas/ws_server.schema.json` | `https://app.invalid/spec/v1/ws_server.schema.json` | WebSocket server events | Suggestion, S_hello, S_ack, S_pong, S_error, S_build_snapshot, S_stage_started, S_stage_progress, S_stage_completed, S_clarify_request, S_clarify_resolved, S_spec_ready, S_reuse_decided, S_slots_ready, S_slot_updated, S_candidates_ready, S_decision_made, S_decision_reverted, S_layout_added, S_part_added, S_part_updated, S_part_removed, S_connection_added, S_connection_removed, S_placement_updated, S_enclosure_updated, S_board_updated, S_firmware_ready, S_firmware_progress, S_scene_ready, S_check_result, S_warning, S_build_done, S_build_failed, S_edit_applied, S_edit_rejected |
