# Host contract

Edit in USD, let the host solve. Sync owns intent, result, derived and diagnostic
layers; each integration owns its document, native API and transactional solver.
Core identity survives every route. No operation accepts a mesh as input.

```python
from aeco_sync.hosts.base import Host, MutationReceipt
# An integration subclasses Host and declares its name.
# [project.entry-points."aeco_sync.hosts"]
# ifc = "usdaeco_ifc.host:IfcHost"
```

| Method | Input | Result / lifetime |
|---|---|---|
| `capabilities()` | none | immutable set of operation families |
| `open(session)` | an existing Session; constructor accepts document, validate_all, ids | self; resolve intent-muted current stage and document version |
| `apply(operations)` | list-compatible Operations with closure; Edit.wire() provides JSON values | MutationReceipt(touched, version); atomic native operation set |
| `readback(ids)` | touched native handles, or None for all | result-layer data `{touched, meshes, stamp}`; normalized drivers, derived values and geometry |
| `diagnostics()` | none | normalized records for this transaction, with severity/code/about/phase/blocking |
| `close()` | none | release resources, including on failures; no new mutation |
| `version()` | none | opaque native change token |
| `supports(edit)` | individual preflighted operation | per-element capability refinement |
| `validate()` | closure in validation_refs | native validation rows; defaults to empty |

The engine serializes result-layer data through `aeco_sync.readback.publish`.
A result receipt is data rather than an adapter-owned USD layer: it prevents the
adapter from accidentally writing the intent layer. Property values retain USD
value types; wire requests use JSON scalars, arrays and dictionaries.

File adapters declare `file_backed = True`, `file_suffix`, and `save(path)`.
The engine saves a sibling temporary file, publishes and saves the USD layers,
then atomically replaces the exported document. Failed publication restores the
USD snapshots and removes the temporary file. External transaction adapters
may retain a `journal` and implement `acknowledge()`; it is called after USD
publication so a committed native operation can be reconciled after a crash.
An adapter supplied as `native=` remains caller-owned; discovered adapters are
closed by the engine. `open()` failures also close the adapter.

Discovery uses `importlib.metadata.entry_points(group="aeco_sync.hosts")`.
Duplicate names fail closed. `--host-module package.module:Class` overrides
installed discovery and still checks the abstract contract and host name.
`aeco-sync init` delegates to `Host.initialize`; integrations can add a kind
importer there. The default initializer creates a session from an existing model
and opaque file document. Host integrations document live-document initialization.

## Identity across routes

| Route | Durable source handle | `aeco:id` | Cache only |
|---|---|---|---|
| IFC file / live IFC | GlobalId | lossless decoded UUID | STEP number; file path; document digest |
| Native authoring route with an IFC exporter | exporter-compatible GUID / durable native id | same published UUID; never re-minted on import | native object number; session handle |
| Distribution port | exported port GUID; deterministic owner/connector recipe if necessary | decoded GUID UUID; connected alternatives reconciled | connector index and candidate exporter GUIDs |
| Host-generated fitting | generated stable GlobalId/native id | minted once, retained in readback | local handle |
| Sensor optics | owning camera identity | no second element identity on a sensor child | owner handle plus sensor selector |

Bindings cache handles; they do not create another identity. Relative prim paths
may change on a fresh conversion, so round-trip comparisons join by `aeco:id`.
Convergence is `aeco_sync.convergence.compare_receipts`: compare drivers,
world-space axes, closed-body volume and bounds. Missing evidence fails the
comparison. `sync:bodyDivergence` is informational, and driver agreement is
reported separately from geometric agreement.

## Compatibility and schema lint

The preserved wire contract names `AecoHostBindingAPI`, `aeco:host:*` and
`aeco:diag:*` predate the family skeleton. They are deliberately retained for
existing intent/result layers and downstream host integrations. These are two
ownership declarations in `library.json`: `classPrefixes` lists
`AecoHostBinding` and `AecoSync`; `namespaces` lists `host` and `diag`.
Toolchain v0.3.2 checks these through raw S08/S09, without overriding failures.
`check.py` also checks the full legacy class/property sets so the wire
vocabulary cannot drift. Tier `record` is permitted
by S03 and describes exchange bindings and findings; it replaces the old
nonstandard `sync` tier.

Validator plugin error tokens use ProperCase. The older Python `validate_stage`
API preserves its lowercase error spellings while calling the same registry
validators. Existing transaction diagnostic codes such as `sync:conflict` remain
unchanged.

## 12.6 The adapters

Three adapters, two code paths: **Revit** (an add-in running the
transaction in-process) and **ifcopenshell**, which serves both the file
route and Bonsai — in Blender the same functions run inside an operator
so the IFC store, undo and the object views stay coherent; headless they
run on a file. The ifcopenshell adapter carries ports of Bonsai's two
regeneration algorithms (keep-connected re-alignment for MEP; recalculate
the connected wall set).

**Pipe operations** — the intent delta on the left, what the adapter
does on the right; every row ends with read-back and diagnostics:

| Intent delta | Revit | ifcopenshell (file / Bonsai) |
|---|---|---|
| `aeco:axis:end` moved, end port **free** | set `LocationCurve.Curve` | extrusion `Depth`; end port placement |
| `aeco:axis:end` moved, end port **connected**, policy `keepConnected` | **never set the curve** — Revit would keep the logical connection and leave a silent gap (S1); instead `MoveElement` the *fitting at that end* by the delta: the pipe stretches, collinear neighbours stretch, perpendicular ones translate, all stay connected; fallback for a run without a fitting: `DisconnectFrom`, curve edit, `NewUnionFitting` / `ConnectTo` | depth + port; translate the downstream subtree by the port delta (children follow); extend the next segment to its predecessor's port — Bonsai's `regenerate_distribution_element` rule: extend segments, translate the rest, never rotate |
| same, policy `refuse` | no host call; `sync:constrainedEnd` | same |
| element transform changed | `ElementTransformUtils.MoveElement` (same keep-connected behaviour) | `edit_object_placement(should_transform_children=True)` + the neighbour rule |
| `aeco:pipe:nominalDiameter` | validate against the type's size table first — Revit accepts any value without failure (S2); then `RBS_PIPE_DIAMETER_PARAM`; at commit Revit resizes what its lookup tables allow and inserts transition fittings where a fitting cannot follow — read those back as host-generated elements (`origin = generated`); they disappear when the size is reverted | swap the type's profile (`material.edit_profile` / new `IfcCircleHollowProfileDef` from the size table); rebuild every occurrence's body and each attached fitting's body (shape builder) |
| a free port gains `aeco:connectedPorts` to another free port | coincident free connectors never connect by themselves (S1); `NewElbowFitting(c1, c2)` (angle), `NewUnionFitting` (collinear), `NewTeeFitting` (a third connector), `NewTransitionFitting` (size step) — the new instance gets an id, a binding, `origin = generated`, and both pipes lose the fitting's take-out | `mep_bend_shape` / `mep_transition_shape` + `connect_port`; shorten the segments to the fitting's tangent points (Bonsai: `bim.mep_add_bend` / `bim.mep_add_transition`) |
| `aeco:connectedPorts` cleared | `Connector.DisconnectFrom` (with a following `MoveElement` this is the API's Disjoin; `ConnectTo` reconnects) | `disconnect_port` |
| type changed (a different catalog prim in `inherits`) | `Pipe.PipeType` | `type.assign_type` (the usage follows) |
| prim deactivated | `Document.Delete`; dangling fittings reported | `root.remove_product` |
| new pipe prim with axis + size + type | `Pipe.Create(doc, systemType, pipeType, level, start, end)` | `root.create_entity` + placement + profile representation + two ports |

**Wall operations:**

| Intent delta | Revit | ifcopenshell (file / Bonsai) |
|---|---|---|
| `aeco:axis:end` moved, end **unjoined** | set `LocationCurve.Curve` (verified); auto-join may fire and is read back as a new join | axis edit + `regenerate_wall_representation` |
| `aeco:axis:end` moved, end **joined** | refused as `sync:joinedEnd` unless the join is removed in the same intent — Revit silently ignores such a curve edit and ifcopenshell trims it back (S3, [11 §11.3 W2](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/11-host-research-walls-pipes.md#113-ifcopenshell--kernel-authoring-api-regeneration-validation)); with the join removed: `DisallowWallJoinAtEnd`, then the curve edit | same |
| element transform changed | `MoveElement`; the joined neighbours stretch or shorten to keep the joins; hosted openings follow (S3) | placement with children; regenerate this wall and its connected set (`recalculate_walls`): a joined neighbour extends or trims to meet it ([11 W3](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/11-host-research-walls-pipes.md#118-evidence)) |
| `aeco:wall:height`, offsets, `baseLevel`, `topLevel` | the wall parameters | `regenerate_wall_representation(height=…)`; placement elevation |
| `aeco:wall:locationLine` | `WALL_KEY_REF_PARAM` (the wall shifts, the axis stays) | usage `OffsetFromReferenceLine` from the build-up |
| `aeco:wall:flipped` | `Wall.Flip()` | usage `DirectionSense` |
| join relationships / allow flags / join types | `WallUtils.Allow/DisallowWallJoinAtEnd` (disallow removes the join at once; allow re-joins at the next regeneration); `LocationCurve.set_JoinType`; `set_ElementsAtJoin` for order | `connect_wall` / `connect_path` / `disconnect_path`; regenerate both walls |
| build-up edited on the type, or the type swapped | `WallType.SetCompoundStructure` / `Wall.WallType`; every occurrence regenerates, joins and hosted openings stay (S3) | `material.edit_layer` / `type.assign_type`; regenerate every occurrence |
| axis shortened past a hosted opening | Revit raises an *Error* at commit ("Instance(s) of <type> not cutting anything") — the preprocessor rolls back and the diagnostic names the wall and the door; the `wallOpeningOutsideHost` validator catches it before the host does | no host rule: the validator is the only check |
| `isExternal`, `loadBearing`, `roomBounding` | function, structural usage, room-bounding parameters | `Pset_WallCommon` |

**Read-back** (identical for both hosts): the axis as the host resolved
it (Revit `LocationCurve`; IFC `get_reference_line`), the derived
section values, port origins and connections (Revit `Connector.Origin`,
`AllRefs`; IFC port placements, `get_connected_port`), joins
(`ElementsAtJoin`; `ConnectedTo`/`ConnectedFrom`), generated elements,
and geometry.

**Geometry return** (ADR-0002: plain gprims plus an applied API):

- `Axis` — `BasisCurves`, `purpose = guide`, derived stage-side from the
  drivers; no host needed.
- `Proxy` — `Cylinder` or `Cube` from the drivers (`approx =
  defaultDims`), `purpose = proxy`, derived stage-side; the element's
  `proxyPrim` relationship targets it. Always available, never shows
  joins or openings.
- `Body` — `Mesh`, `purpose = render`, from the host: Revit
  `Element.get_Geometry` at fine detail, faces triangulated; ifcopenshell
  `create_shape` (with `unify-shapes`), vertices, faces and per-face
  material ids as `GeomSubset`s. Shows joins, clips and openings. Each
  host's result layer carries its own `Body`; the sublayer order shows
  the authoritative one; the sync library's convergence check compares
  volumes and bounding boxes across result layers and raises
  `sync:bodyDivergence` as information.

All three carry `AecoDerivedGeometryAPI` (§12.8): source id, role,
approximation, stamp.

**Diagnostics mapping.**

| Host surface | → `AecoSyncDiagnostic` |
|---|---|
| Revit `FailureMessageAccessor` (severity, definition id, description, failing and additional element ids, resolutions) | severity 1:1 (DocumentCorruption → error); `code = revit:<definition>`; `hostRefs` = element UniqueIds; `about` via bindings; `blocking` when the preprocessor rolled back |
| Revit API exceptions (`InvalidOperationException` from a fitting call, `ArgumentException` from a curve) | error, `code = revit:exception:<type>`, `phase = apply`, blocking |
| `ifcopenshell.validate` log lines (JSON logger: instance, attribute, rule, message) | `code = ifc:<rule or attribute>`; `about` via GlobalId |
| ifcopenshell geometry log during `create_shape` | `code = ifcopenshell:geometry`, `phase = regenerate` |
| IDS results (`ifctester`) | `code = ids:<specification>`, `phase = validate` |
| Bonsai operator reports | `code = bonsai:<operator>`, message verbatim |
| the sync library's own checks | `code = sync:<check>` |
