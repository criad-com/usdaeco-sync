# 12 · `usdAecoWall`, `usdAecoPipe`, and the two-way sync

The first two element-kind libraries, designed around the ask that
motivates them: expose a pipe's diameter and a wall's thickness and
extent as parameters in OpenUSD, let them be edited there, round-trip
the edit to Revit and to IFC (live Bonsai or a file), and get back the
detailed and proxy geometry plus whatever validation either host raises.
[11](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/11-host-research-walls-pipes.md) is the evidence; this document is
the design. The core changes in §12.8 shipped in v0.7.0; §12.9–12.10
record the subsequent library and adapter deliveries and their limits.

**The answer in one paragraph.** OpenUSD is the *ledger and the editor of
intent*; the hosts are the *solvers*. A kind library carries the small
set of **driver** properties every host can rebuild a native element
from (the axis, the section choice, the constraints), marks everything
else **derived**, and never carries geometry. A sync session is three
layers per host — *intent* (stage-side edits, drivers only), *result*
(the host's resolved drivers, derived values, ports, joins and meshes)
and *diagnostics* (the host's findings as structured prims) — with one
invariant: **an empty intent layer means the stage and the host agree**.
An adapter turns the intent delta into host operations, using the
connection graph to decide what a change on a constrained end means,
and writes back what the host actually did. The core's contribution is
one applied schema for the axis and one for derived geometry; the rest
is libraries.

## 12.1 Drivers in, derived out — the three-layer transaction

**Vocabulary.**

- A **driver** is a property a host can consume to build or rebuild its
  native element: the axis, the nominal size, the height, the location
  line, the join and connection relationships, the type choice.
- A **derived** value is one the host computes: length, outer/inner
  diameter, thickness, areas, volumes, resolved port positions, meshes.
  Derived properties are marked in the schema with the `aecoDerived`
  property metadatum so a validator, an editor and a diff can treat them
  mechanically ([E13, §12.8](#128-optional-core-modifications)).
- A **host-generated element** is one the host created to satisfy an
  intent (a bend, a union, a transition). It is a real element with an
  id and a binding, marked `generated`, so the adapter may regenerate it
  rather than reconcile it.
- A **binding** is the host's own handle for a prim (`UniqueId`,
  `GlobalId`, a connector index) plus the host's change token.

**Layer stack** (strongest first):

```
stage.usda
  subLayers = [
    @sync/intent.usda@            # stage-side edits: drivers only, sparse overs
    @sync/diagnostics.revit.usda@ # /Sync/Diagnostics/* prims; customLayerData = session
    @sync/result.revit.usda@      # host-owned: resolved drivers, derived, ports, joins, Body/Proxy
    @sync/result.ifc.usda@        # a second host, if any — one result layer per host
    @model.usda@                  # the base import (the core stage from a converter)
  ]
```

**The cycle.**

1. An editor authors driver opinions in `intent.usda` — a new
   `aeco:axis:end`, a new `aeco:pipe:nominalDiameter`, a connection
   relationship, a new prim, a deactivated prim.
2. The adapter computes the **edit set**: every intent opinion, compared
   with the strongest opinion below intent. Derived opinions are
   rejected outright with a diagnostic.
3. It **classifies** each element's edits — geometry (axis, transform,
   height, offsets), section (size, type), relation (joins, ports),
   semantic (flags, properties) — and takes the **dependency closure**
   through ports and joins: an edit on a connected or joined end marks
   the neighbours, and the session's **gap policy** decides what happens
   to them (`keepConnected` moves them, `disconnect` breaks the link,
   `refuse` rejects the edit).
4. It applies the edits in **one host transaction** (Revit
   `Transaction`, ifcopenshell in-memory file, Bonsai `IfcStore`
   operator) using the operation tables of §12.6, then lets the host
   regenerate.
5. It **reads back** every touched element plus its closure: drivers as
   the host resolved them (snapped sizes, trimmed axes), derived values,
   port positions and connections, joins, generated elements, and the
   meshes.
6. It writes `result.<host>.usda`, writes `diagnostics.<host>.usda`,
   updates the bindings' change tokens, and **clears the accepted
   opinions from intent**. Rejected opinions stay in intent with a
   diagnostic pointing at them.
7. A host-side change (someone edits in Revit) flows into the result
   layer directly at the next sync; if intent holds an opinion on the
   same property, the host value wins and a `sync:conflict` diagnostic
   marks the intent opinion for the user to redo or drop.

**Why a transaction, not a live link.** It is deterministic and
reviewable (the intent layer *is* the change request; the result layer
*is* the receipt); it works identically for a live host and for a file
(the file route has no one to be live with); it matches how both hosts
already work — Revit commits transactions with failure processing,
Bonsai commits placements lazily and regenerates on demand; and it keeps
the stage an ordinary USD stage with no host process attached (B7).

**Why lengths are not authored.** Every host derives length from the
axis ([11 §11.1](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/11-host-research-walls-pipes.md#111-findings-in-ten-lines)).
An editor that wants a "length" control computes it from the axis and
writes the axis end back — the same way a transform manipulator writes
`xformOp:translate`. The documented rule for such an editor: a length
edit keeps the start fixed and moves the end; to move the start, edit
the start.

## 12.2 The shared anatomy: the axis

Walls, pipes, ducts, trays, beams and columns share one anatomy —
axis + section-from-type → body, plus end relations ([11 §11.7,
R-b](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/11-host-research-walls-pipes.md#117-what-this-means-for-the-design)).
The axis is the part every host agrees is *the* parameter, so it is
defined once, applied to any element that has one:

```
class "AecoAxisAPI" (
    inherits = </APISchemaBase>
    doc = """The driving axis of a path-based element (wall, pipe, duct,
    cable carrier, beam, column): the one representation every host
    treats as the parameter — IFC's 'Axis' representation, an
    authoring tool's location curve. Authored in the prim's local space;
    the prim's transform places it. Convention: the axis START is the
    local origin (hosts re-express placement at the axis start), so a
    length edit is an edit of aeco:axis:end. Length is DERIVED."""
    customData = {
        string className = "AxisAPI"
        token apiSchemaType = "singleApply"
        token[] apiSchemaCanOnlyApplyTo = ["Imageable"]
    }
) {
    double3 aeco:axis:start = (0, 0, 0) (doc = "DRIVER (m). Local-space start.")
    double3 aeco:axis:end = (1, 0, 0) (doc = "DRIVER (m). Local-space end.")
    uniform token aeco:axis:curve = "line" (
        allowedTokens = ["line", "arc"]
        doc = "DRIVER. 'arc' = circular arc through aeco:axis:arcPoint (walls); pipes are lines."
    )
    double3 aeco:axis:arcPoint = (0, 0, 0) (doc = "DRIVER, arc only: a point on the arc.")
    double aeco:axis:length = 0 (
        aecoDerived = true
        doc = "DERIVED (m). Host-reported length along the axis."
    )
}
```

This lives in core v0.7.0 (§12.8, ADR-0007); a separate `usdAecoAxis`
library is unnecessary. A derived `Axis` child gprim
(`BasisCurves`, `purpose = guide`) makes the axis visible and snappable
in any USD viewer with nothing installed.

## 12.3 `usdAecoPipe`

Applies to elements (with `AecoElementAPI` and `AecoAxisAPI`), to ports,
to catalog types and to systems. Kind stays classification
(`IfcPipeSegment.RIGIDSEGMENT`, `IfcPipeFitting.BEND`); the APIs carry
data, not kind.

| Property | D/D | Meaning | Revit | IFC |
|---|---|---|---|---|
| `aeco:pipe:nominalDiameter` | **driver** | the size-table key (m) | `RBS_PIPE_DIAMETER_PARAM` (set); `MEPCurve.Diameter` (read) | `Pset_PipeSegmentTypeCommon.NominalDiameter` |
| `aeco:pipe:outerDiameter` | derived | from the type's table | `RBS_PIPE_OUTER_DIAMETER` | `IfcCircleHollowProfileDef.Radius × 2` |
| `aeco:pipe:innerDiameter` | derived | | `RBS_PIPE_INNER_DIAM_PARAM` | radius − wall thickness |
| `aeco:pipe:sizeLabel` | derived | the host's display size | `RBS_PIPE_SIZE_PARAM` ("50 mmø") | profile name ("DN50") |
| `aeco:pipe:slope` | derived | rise over run of the axis | `RBS_PIPE_SLOPE` | `Pset_PipeSegmentOccurrence.Gradient` |
| `aeco:pipeType:material` | driver (type) | | `PipeSegment` material | `IfcMaterial.Name` on the profile |
| `aeco:pipeType:schedule` | driver (type) | | `PipeSegment` schedule/type | `Pset_PipeSegmentTypeCommon.Reference` |
| `aeco:pipeType:nominalDiameters` / `outerDiameters` / `innerDiameters` | derived (type) | the size table, aligned arrays | `PipeSegment.GetSizes()` | one entry per profile |
| `aeco:pipeType:workingPressure` | driver (type) | Pa | type parameter | `Pset_PipeSegmentTypeCommon.WorkingPressure` |
| `aeco:pipePort:nominalDiameter` | derived (segment) / driver (equipment) | | `Connector.Radius × 2` | `Pset_DistributionPortTypePipe.NominalDiameter` |
| `aeco:pipePort:connectionType` | driver | threaded, flanged, welded, pushFit, compression, solvent, grooved, other, undefined | family connector description | `Pset_DistributionPortTypePipe.ConnectionType` |
| `aeco:pipeFitting:origin` | driver | `authored` \| `generated` (host-created to satisfy an intent) | — (adapter bookkeeping) | — |
| `aeco:pipeFitting:angle`, `aeco:pipeFitting:bendRadius` | derived | | family parameters | fitting geometry |
| `aeco:pipeSystem:fluid`, `aeco:pipeSystem:fluidTemperature` | driver (system) | | `PipingSystemType` fluid | no standard property |

Notes on the cut. The system *kind* is classification
(`IfcDistributionSystem.DOMESTICCOLDWATER`), so the `systemType` token
proposed in [10 §10.3](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/10-fan-out-proposal.md#103-kind-libraries--replacing-the-discipline-libraries)
is dropped — it duplicated a classification code (E4). A fitting's role
(bend, tee, transition) is likewise the classification's `PredefinedType`,
not a token. Insulation is a covering element in both hosts and gets no
property here. Length is the axis's.

```
#usda 1.0
(  subLayers = [@usdGeom/schema.usda@, @usdAeco/schema.usda@]  )
over "GLOBAL" ( customData = { string libraryName = "usdAecoPipe"  bool skipCodeGeneration = true  bool useLiteralIdentifier = true } ) {}

class "AecoPipeAPI" ( inherits = </APISchemaBase>
    customData = { string className = "PipeAPI"  token apiSchemaType = "singleApply"  token[] apiSchemaCanOnlyApplyTo = ["Imageable"] }
) {
    double aeco:pipe:nominalDiameter = 0.05 (doc = "DRIVER (m). Must be one of the type's aeco:pipeType:nominalDiameters (validator: pipeSizeNotInTable).")
    double aeco:pipe:outerDiameter = 0 (aecoDerived = true)
    double aeco:pipe:innerDiameter = 0 (aecoDerived = true)
    string aeco:pipe:sizeLabel = "" (aecoDerived = true)
    double aeco:pipe:slope = 0 (aecoDerived = true)
}
class "AecoPipeTypeAPI" ( inherits = </APISchemaBase>
    doc = "Apply on the catalog class prim beside AecoTypeAPI; occurrences inherit it."
    customData = { string className = "PipeTypeAPI"  token apiSchemaType = "singleApply" }
) {
    string aeco:pipeType:material = ""
    string aeco:pipeType:schedule = ""
    double aeco:pipeType:workingPressure = 0
    double[] aeco:pipeType:nominalDiameters = [] (aecoDerived = true)
    double[] aeco:pipeType:outerDiameters = [] (aecoDerived = true)
    double[] aeco:pipeType:innerDiameters = [] (aecoDerived = true)
}
class "AecoPipeFittingAPI" ( inherits = </APISchemaBase>
    customData = { string className = "PipeFittingAPI"  token apiSchemaType = "singleApply"  token[] apiSchemaCanOnlyApplyTo = ["Imageable"] }
) {
    uniform token aeco:pipeFitting:origin = "authored" (allowedTokens = ["authored", "generated"])
    double aeco:pipeFitting:angle = 0 (aecoDerived = true)
    double aeco:pipeFitting:bendRadius = 0 (aecoDerived = true)
}
class "AecoPipePortAPI" ( inherits = </APISchemaBase>
    customData = { string className = "PipePortAPI"  token apiSchemaType = "singleApply"  token[] apiSchemaCanOnlyApplyTo = ["AecoPort"] }
) {
    double aeco:pipePort:nominalDiameter = 0
    uniform token aeco:pipePort:connectionType = "undefined" (
        allowedTokens = ["undefined", "threaded", "flanged", "welded", "pushFit", "compression", "solvent", "grooved", "other"])
}
class "AecoPipeSystemAPI" ( inherits = </APISchemaBase>
    customData = { string className = "PipeSystemAPI"  token apiSchemaType = "singleApply"  token[] apiSchemaCanOnlyApplyTo = ["AecoSystem"] }
) {
    string aeco:pipeSystem:fluid = ""
    double aeco:pipeSystem:fluidTemperature = 0 (doc = "K")
}
```

**Validators** (library-owned, warn unless stated): `pipeKindMismatch`
(the prim's IFC code is not `IfcPipeSegment`/`IfcPipeFitting`),
`pipeSizeNotInTable`, `pipePortSizeMismatch` (connected ports differ in
nominal diameter with no transition between), `pipeGap` (connected
ports further apart than tolerance — the check no host performs),
`pipeMissingAxis` (error: a pipe without `AecoAxisAPI`),
`derivedAuthoredInIntent` (error; from the sync library).

**Importer pass** (the promotion mechanism of [10 §10.3](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/10-fan-out-proposal.md#103-kind-libraries--replacing-the-discipline-libraries)):
on a core stage, for every element classified `IfcPipeSegment`, read the
IFC axis or the extrusion (start, direction, depth) into `AecoAxisAPI`,
the hollow-circle profile and `Pset_PipeSegmentTypeCommon` into the type's
and the occurrence's pipe APIs, and drop the quarantined
`aeco:props:Pset_PipeSegmentTypeCommon:*` copies that now have a typed
home.

## 12.4 `usdAecoBuildUp` and `usdAecoWall`

The section of a wall is a layered build-up owned by the type, the same
data shape floors, roofs and ceilings use, so it is a shared section
library that `usdAecoWall` sublayers (core ← BuildUp ← Wall). Section
is the explicit lower sub-tier allowed by E3/E12; this is not an edge
between kind libraries.

| Property | D/D | Revit | IFC |
|---|---|---|---|
| `aeco:buildUp:thicknesses` (double[]) | driver (type) | `CompoundStructureLayer.Width` | `IfcMaterialLayer.LayerThickness` |
| `aeco:buildUp:functions` (token[]: structure, substrate, insulation, finish, membrane, other) | driver (type) | `MaterialFunctionAssignment` | `IfcMaterialLayer.Category` |
| `aeco:buildUp:materials` (string[]) | driver (type) | layer material name | `IfcMaterial.Name` |
| `aeco:buildUp:priorities` (int[]) | driver (type) | function priority / wrapping | `IfcMaterialLayer.Priority` (decides mitre vs butt in regeneration) |
| `aeco:buildUp:totalThickness` | derived | `WallType.Width` | sum |

Render materials bind through UsdShade as usual (E10); the strings here
are the hosts' names, for the join across routes.

The wall occurrence — with `AecoAxisAPI` as its baseline:

| Property | D/D | Meaning | Revit | IFC |
|---|---|---|---|---|
| `aeco:wall:locationLine` | **driver** | centerline, coreCenterline, finishFaceExterior, finishFaceInterior, coreFaceExterior, coreFaceInterior | `WALL_KEY_REF_PARAM` | `IfcMaterialLayerSetUsage.OffsetFromReferenceLine` (computed from the build-up) |
| `aeco:wall:flipped` | driver | which side the layers extrude to | `Wall.Flipped` / `Flip()` | `DirectionSense` |
| `aeco:wall:height` | driver when `topLevel` is unset, else derived | m | unconnected height | extrusion depth |
| `aeco:wall:baseOffset`, `aeco:wall:topOffset` | driver | m | `WALL_BASE_OFFSET`, `WALL_TOP_OFFSET` | placement / depth |
| `rel aeco:wall:baseLevel`, `rel aeco:wall:topLevel` | driver | `AecoLevel` prims | base / top constraint | containing storey; `ExtendToStructure` hint |
| `aeco:wall:isExternal`, `aeco:wall:loadBearing`, `aeco:wall:roomBounding` | driver | | function, structural usage, room bounding | `Pset_WallCommon.IsExternal`, `LoadBearing`; space boundaries |
| `rel aeco:wall:joinAtStart`, `rel aeco:wall:joinAtEnd`, `rel aeco:wall:joinAlongPath` | driver | the joined walls per end; T-joins into this wall | `LocationCurve.ElementsAtJoin` | `IfcRelConnectsPathElements` ATSTART / ATEND / ATPATH |
| `aeco:wall:allowJoinAtStart`, `aeco:wall:allowJoinAtEnd` | driver | | `WallUtils.Allow/DisallowWallJoinAtEnd` | (absence of a connection) |
| `aeco:wall:joinTypeStart`, `aeco:wall:joinTypeEnd` | driver | auto, butt, miter, squareOff | `JoinType` | derived from layer priorities |
| `aeco:wall:thickness` | derived | | `WALL_ATTR_WIDTH_PARAM` | layer set sum |
| `aeco:wall:grossSideArea`, `netSideArea`, `grossVolume`, `netVolume` | derived | | computed area / volume | `Qto_WallBaseQuantities` |

Joins are relationships in the wall library, not ports: a path join is
a geometric relation between axis ends, not network connectivity, so E6
is untouched. If beams and columns need the same relation the trio is
complete and the join set moves into `AecoAxisAPI` (§12.8, variant).
The full opening contract is intended for `usdAecoOpening`
([10 §10.3](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/10-fan-out-proposal.md#103-kind-libraries--replacing-the-discipline-libraries));
The wall library ships its minimal `AecoOpeningAPI` inside `usdAecoWall` 0.1.0 until extraction;
the wall validator only checks that a hosted opening's `host` is a wall
whose axis spans it — the check whose failure Revit resolves by deleting
the door.

**Validators**: `wallKindMismatch`, `wallMissingAxis` (error),
`wallJoinAsymmetric` (A joins B at its end, B does not list A),
`wallJoinedEndExtended` (intent moves an axis end that is joined without
also editing the join — the edit every host would undo or refuse),
`wallOpeningOutsideHost`, `wallSizeMismatch` (the build-up's sum differs
from the reported thickness).

## 12.5 `usdAecoSync` — binding, diagnostics, protocol

A small library below the kind libraries (core ← Sync; Pipe and Wall
do not depend on it — a stage can carry pipes without ever syncing).

```
class "AecoHostBindingAPI" ( inherits = </APISchemaBase>
    doc = "One instance per host, named from the sync registry (revit, ifc, bonsai, …)."
    customData = { string className = "HostBindingAPI"  token apiSchemaType = "multipleApply"  token propertyNamespacePrefix = "aeco:host" }
) {
    string ref = ""       (doc = "The host's durable handle: Revit UniqueId; IFC GlobalId; port = owner handle + connector index.")
    string localRef = ""  (doc = "Session-volatile handle: Revit ElementId; STEP instance id; Blender object name.")
    string version = ""   (doc = "The host's change token: Revit VersionGuid; file hash; Bonsai transaction key.")
    string document = ""  (doc = "The host document: Revit project/central id; IFC file path + hash.")
}
class AecoSyncDiagnostic "AecoSyncDiagnostic" ( inherits = </Typed>
    doc = "A host's finding about one sync, under /Sync/Diagnostics. Transient and machine-made: not a record-tier statement; a persisting one is minted into an issue by a person."
    customData = { string className = "SyncDiagnostic"  token[] fallbackTypes = ["Scope"] }
) {
    uniform token aeco:diag:severity = "warning" (allowedTokens = ["info", "warning", "error"])
    string aeco:diag:code = ""      (doc = "Host-qualified: revit:<FailureDefinitionId or BuiltInFailures name>, ifc:<rule>, ifcopenshell:geometry, ids:<specification>, bonsai:<operator>, sync:<check>.")
    string aeco:diag:message = ""
    uniform token aeco:diag:host = ""
    uniform token aeco:diag:phase = "apply" (allowedTokens = ["apply", "regenerate", "validate", "export"])
    bool aeco:diag:blocking = false (doc = "The host rolled the transaction back; the intent stays pending.")
    string[] aeco:diag:hostRefs = []
    rel aeco:diag:about  (doc = "The element, port or type prims concerned; the intent property path may be named in the message.")
}
```

Session facts — host, document, change token, time of the sync, gap
policy, which host is authoritative — are `customLayerData` on the
result and diagnostics layers, not prim properties: information time is
layer metadata (E12), and a policy is a property of a session, not of an
element. The sync codes the library itself raises: `sync:derivedAuthored`,
`sync:constrainedEnd`, `sync:joinedEnd`, `sync:gap`, `sync:conflict`,
`sync:staleIntent` (the binding's change token moved on since the intent
was authored), `sync:bodyDivergence` (two hosts' bodies for one element
differ beyond tolerance — the cross-route convergence check).

**Identity across routes.**

| Thing | `aeco:id` | Revit binding | IFC / Bonsai binding |
|---|---|---|---|
| element | the IFC GlobalId in canonical UUID form; Revit stores the same GUID in its IFC GUID parameter and its exporter derives it deterministically from `UniqueId` | `ref` UniqueId, `localRef` ElementId, `version` VersionGuid | `ref` GlobalId, `localRef` STEP id, `version` file hash |
| port | the exporter's recipe, reproduced outside Revit (13/13 in the spike): free connector = MD5 of `<elementGuid>Sub-element:IfcDistributionPort Connector: <id>`; connected pair = MD5 of `InPort<id><inGuid><outGuid>` on the element processed first and `OutPort<id><outGuid><inGuid>` on the other, `<id>` being the first element's connector — both candidates are computed and matched against an export (the processing order is the exporter's, not the adapter's) | `ref` = UniqueId + ":" + `Connector.Id` | port GlobalId |
| catalog type | type GlobalId | `ElementType` UniqueId | `IfcTypeProduct` GlobalId |
| generated fitting | minted by the adapter at creation, written to the host (IFC GUID parameter / GlobalId) | as element | as element |

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

## 12.7 A round trip, concretely

The pipe from the examples, edited from DN50 to DN65 and extended 0.5 m
into a connected end, against the file route.

```
# sync/intent.usda — what the editor wrote
over "Pipe_1" {
    double aeco:pipe:nominalDiameter = 0.065
    double3 aeco:axis:end = (2.5, 0, 0)
}
```

The adapter classifies: a section edit (type table lookup: 0.065 is in
the table) and a geometry edit on a connected end (policy
`keepConnected` → the elbow and `Pipe_2` are in the closure). It applies
depth, end-port placement, the subtree translation, the profile swap on
the type and the body rebuilds, regenerates, validates, and writes:

```
# sync/result.ifc.usda — what the host did   (customLayerData: host, document, hash, time, policy)
over "Pipe_1" {
    double3 aeco:axis:end = (2.5, 0, 0)
    double aeco:axis:length = 2.5
    double aeco:pipe:nominalDiameter = 0.065
    double aeco:pipe:outerDiameter = 0.0761
    double aeco:pipe:innerDiameter = 0.0697
    string aeco:pipe:sizeLabel = "DN65"
    def Mesh "Body" ( apiSchemas = ["AecoDerivedGeometryAPI"] ) { ... token purpose = "render"  string aeco:derived:stamp = "ifcopenshell 0.8.5" }
    over "Port_End" { double3 xformOp:translate = (2.5, 0, 0) }
}
over "Pipe_2" { double3 xformOp:translate = (2.5, 0, 1) ... }          # translated, body rebuilt at DN65
over "Elbow_7" { ... }                                                # if present: translated, body rebuilt
```

```
# sync/diagnostics.ifc.usda
def Scope "Sync" { def Scope "Diagnostics" {
    def AecoSyncDiagnostic "d001" {
        uniform token aeco:diag:severity = "info"
        string aeco:diag:code = "sync:neighbourMoved"
        string aeco:diag:message = "Pipe_2 translated (0.5, 0, 0) to keep Port_End connected"
        rel aeco:diag:about = [</Pipe_2>, </Pipe_1/Port_End>]
    }
}}
```

Intent is then empty: the stage and the file agree. Against Revit the
same intent produces a result layer whose `Body` came from Revit's
tessellation, a `sizeLabel` of "65 mmø", and — because the generic
elbow keeps its 50 mm — two host-generated transition fittings between
the pipe and its neighbours, each a new prim with an id, a binding and
`origin = generated`, plus an `info` diagnostic naming them. Had the
intent asked for a size outside the type's table, the adapter's own
`pipeSizeNotInTable` check would have refused it before any host call:
Revit itself accepts any value.

## 12.8 Optional core modifications

Everything above works with the core as it is, at the cost of one more
library (`usdAecoAxis`) and one convention nobody enforces. The core
change that removes that cost is small and additive (a v0.7), and it is
the kind of change the core exists to make once: a mechanism every
path-based library and every adapter would otherwise re-mint.

**C1 — `AecoAxisAPI` in the core** (§12.2). Arguments: it is the second
mechanism after ports on which connectivity hangs (path joins are
defined on axis ends); it is IFC's standard `Axis` representation across
walls, beams, columns, members and flow segments — structural in the
incumbent, not kind-specific; and it yields a new core promise, **B9:
the plan is a traversal** — a core-only consumer can draw every
axis-based element as a line with nothing else installed. Variant: also
carry the path-join relationships (`aeco:axis:joinAtStart/End/AlongPath`)
once beams or columns need them (rule of three); until then they stay in
`usdAecoWall`.

**C3 — `AecoDerivedGeometryAPI` in the core.** ADR-0002 committed to
"plain gprims plus an applied API" and specified `AecoProxyAPI`; the
v0.6 core ships no such API. This design needs the mark on proxies,
bodies and axes alike, so it generalizes the ADR's schema by one token:

```
class "AecoDerivedGeometryAPI" ( inherits = </APISchemaBase>
    customData = { string className = "DerivedGeometryAPI"  token apiSchemaType = "singleApply"  token[] apiSchemaCanOnlyApplyTo = ["Gprim"] }
) {
    string aeco:derived:source = ""   (doc = "aeco:id of the element this gprim stands for.")
    uniform token aeco:derived:role = "body" (allowedTokens = ["body", "proxy", "axis", "footprint", "symbol"])
    uniform token aeco:derived:approx = "exact" (allowedTokens = ["exact", "tessellated", "arcSegmented", "defaultDims", "bbox"])
    string aeco:derived:stamp = ""    (doc = "Deriving host or tool and its version.")
}
```

**Two contract rules**, whichever home the schemas get:

- **E13 · Drivers and derived.** In every library namespace a property is
  a driver unless its schema definition carries `aecoDerived = true` — a
  boolean property metadatum the core plugin registers through
  `SdfMetadata` in its `plugInfo.json`. Only drivers may be authored by
  an editing party; derived values are written by hosts and derivations;
  a validator flags a derived opinion in an intent layer. The field
  lives in schema files only, never in stage data, so vanilla runtimes
  never meet it. (Verified: `usdGenSchema` drops property `customData`
  but preserves a registered field and `displayGroup` into the
  registry, where `GetPropertyMetadata` and `Property.GetMetadata`
  return it.)
- **E14 · Geometry flows out of hosts only.** A library never presents a
  mesh to a host as input; every host-facing representation is a driver
  set. Derived gprims carry `AecoDerivedGeometryAPI`.

**Explicitly not core — C2, the host binding.** The core's identity rule
(E8) is one identity; a binding is a cache of host handles for a sync
session, so it lives in `usdAecoSync`. The same goes for diagnostics:
statements about elements are downstream (ADR-0006).

Cost of C1 + C3: two applied schemas, nine properties, no typed prims,
no registry; B8's count becomes "6 applied schemas". **Status: shipped in
core v0.7** — [ADR-0007](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/adr/0007-drivers-in-derived-out.md) is Accepted;
the schemas, the registered `aecoDerived` field, the validators, the
converter pass and the examples are in the core package.

## 12.9 Spikes before building

**Implementation followed the spikes.** The S1–S6 results below remain
historical evidence. Library deliveries now include `usdAecoSync`,
`usdAecoPipe`, `usdAecoBuildUp` and `usdAecoWall`, with the shared
`usdaeco-toolchain` builder and checks; versions and merged acceptance
results are recorded in §12.10. Core v0.7.1 and Pipe/BuildUp/Wall v0.1.1
are shipped; the integration gate replaces the retired S4/S5/prototype copies with
production libraries and retains the Revit and edit-semantics evidence. A spike pass is not a claim of complete
adapter coverage.

| # | Question | Pass criterion |
|---|---|---|
| S1 | **Done.** Revit API: curve edits versus `MoveElement` on a pipe connected through an elbow and a tee | a curve edit on a connected end keeps the logical connection and leaves a silent gap; `MoveElement` keeps the network connected (fittings follow, collinear pipes stretch, perpendicular ones translate); coincident free connectors do not connect; `DisconnectFrom` + move is Disjoin, `ConnectTo` reconnects. Adapter rule adopted: move the fitting, never set the curve on a connected end |
| S2 | **Done.** Revit: `RBS_PIPE_DIAMETER_PARAM` with fittings, including sizes absent from the table | any value is accepted without failure; at commit Revit inserts transition fittings where a fitting cannot follow and removes them on revert. Adapter rule adopted: validate against the size table; read transitions back as generated elements |
| S3 | **Done.** Revit walls and export | a curve edit that moves a joined end is ignored; moving the neighbour stretches the wall; a door left outside its host is an Error captured with both ids; IFC4 export carries the join as `IfcRelConnectsPathElements` and 13 ports with stable GUIDs; the port GUID recipe reproduced 13/13 outside Revit. Caveat: a door placed with the level-taking overload was hosted but did not cut, and raised nothing |
| S4 | **Done.** ifcopenshell file adapter: the two Bonsai algorithms ported (segment extends or trims to the moved port, everything else translates; the joined wall set regenerates); the [11 §11.8](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/11-host-research-walls-pipes.md#118-evidence) scenario run from an intent layer of five edits | result layer written; zero gaps; two edits refused with `sync:derivedAuthored` and `sync:joinedEnd` and left in intent; three applied — the connected neighbour trimmed to meet the extended pipe, the profile swapped from the type's table, the joined wall regenerated to meet its moved neighbour — with `sync:neighbourMoved` and `pipePortSizeMismatch` reported; after withdrawing the refused edits a second pass finds nothing to do and the intent layer is empty |
| S5 | **Done.** Bonsai headless (Blender 5.1.2, Bonsai 0.8.5): the same three edits through `DumbProfileJoiner.set_depth`, `regenerate_distribution_element`, `DumbProfileRecalculator` and `recalculate_walls`, saved and read back through the same adapter | result layer equal to S4: 68 properties within 1e-4, the same single warning |
| S6 | **Done for the drafts.** Codeless build of Axis, DerivedGeometry, Sync, Pipe, PipeType, PipeFitting, BuildUp, Wall; `CanApplyAPI` refusals; the derived-in-intent validator | green; the `aecoDerived` field visible through the registry and used by S4's refusal |

S6 was run while writing this document: all eleven sketches built codeless
against the core plugin; `CanApplyAPI` refused the derived-geometry API on
an `Xform`, the pipe-port API on a `Mesh` and the pipe-system API on a
`Scope`; the multi-apply binding produced `aeco:host:revit:*`; the
diagnostic type fell back to `Scope`; and the derived-in-intent check found
the derived opinion in an intent layer and ignored the driver beside it.

S4 and S5 were then run end to end on the scenario of [11 §11.8](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/11-host-research-walls-pipes.md#118-evidence):
a core stage from the reference converter, the importer kind pass authoring
drivers, bindings, the Axis and Proxy gprims, and the layer stack; an intent
layer of five edits; the file adapter; the same edits through Bonsai's own
operators in headless Blender; the Bonsai IFC read back through the same
adapter. Two details the runs settled: a refused derived opinion left in
intent shadows the host's value in the composed stage, so the stage-side
derivation reads derived properties from the intent-muted view (drivers
still come from intent, which is what the proxy is for); and "intent
empty" is reached in two steps — the adapter clears what it applied, the
editor withdraws what was refused.

## 12.10 Sequencing

**Shipped status (2026-09-08).** Counts below are the merged PR acceptance
results, not new runs of adapters in the core repository. PR numbers are
repository-local so this document needs no deployment address.

| Package / work | Version | Shipped surface and acceptance evidence |
|---|---|---|
| `usdAeco` | v0.7.1 | Axis, derived geometry and metadata; core PR #1: **25/25 checks** |
| `usdAecoSync` | 0.1.0 | Binding, diagnostics, Python transaction engine, CLI and Accepted ADR-0008; sync PR #1: **14/14 checks**, 35 tests, 10 IFC scenarios and 3 Bonsai scenarios |
| `usdAecoPipe` | v0.1.1 | Five APIs, five validators, size catalogs and IFC promotion; pipe PR #1: **35/35 checks**, both synthetic and reference baseline |
| IFC host, in `usdAecoSync` | 0.1.0 | Native creation, generated fittings, wall operations and closure read-back; sync PR #2: **53 tests**, including a run with production kind plugins; full acceptance **16/16 checks** |
| Bonsai mode, in `usdAecoSync` | 0.1.0 | Reference native runner shipped with the sync engine; sync PR #2 reports 3 shared scenarios and **152/152** parity values within 1e-4; this does not certify every planned operation |
| Revit | Merged Sync revision, pinned by the scenarios gate | Python adapter, C# script pack, rollback scenarios and export comparison shipped; offline acceptance is recorded in Sync. Live native execution remains unverified; no live pass is inferred from the merge |
| `usdAecoBuildUp` | v0.1.1 | Shared layered section, catalog query and two validators; build-up PR #1: **18/18 checks** |
| `usdAecoWall` | v0.1.1 | Wall and minimal Opening APIs, six validators and IFC promotion; wall PR #1: **46/46 checks** with the reference baseline (44 synthetic); IFC/Bonsai neighbour parity **108/108** wall values |
| `usdaeco-toolchain` | 0.1.0 | Shared codeless builder, check primitives, dependency plugin sets and Nix/template support; toolchain PR #1: **35 tests**, 4/4 package checks |

**Integration gate.** `usdaeco-scenarios` pins the complete family,
builds one dependency plugin path and executes the library checks, all **21**
IFC cases, the **3** shared Bonsai cases and S4/S5. Its unattended demo uses
the production pipe and wall importers and compares **152/152** IFC/Bonsai
result values within 1e-4. Library profiles supply default severity overlays;
the roundtrip profile hardens bindings, path axes, kind APIs and derived
opinions above result layers. [08](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/08-worked-examples.md) walks the shipped route.

The version column identifies repository release tags where present; existing
schema manifests still advertise 0.7 for core and 0.1.0 downstream. Exact
revisions, including untagged Sync changes, are in the gate's manifest. Counts
in the older delivery rows are historical PR evidence; the gate emits fresh
per-library counts including profile checks.

**Delivery limits.** Pipe's reference baseline has no fittings or mapped
property sets; augmented fixtures cover both. Wall's baseline has no
openings or mapped wall properties; synthetic metre and millimetre fixtures
cover them. Opening remains in the Wall plugin to avoid duplicate schema
definitions before extraction. Native Nix wall acceptance used an explicit
USD-only gate because its Python environment lacked IfcOpenShell; the full
importer checks used USD 26.8 / IfcOpenShell 0.8.5 wheels. IFC adapter limits
include straight axes, metre inputs, translations and fixed layer counts;
complete Bonsai/Revit operation parity is not established by these counts.

The sequence replaces steps 3 and 6 of
[10 §10.6](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/10-fan-out-proposal.md#106-sequencing):

1. **Shipped:** core v0.7.1 (C1 + C3, E13/E14).
2. **Shipped:** `usdAecoSync`: binding, diagnostics, the layer protocol, validators;
   the protocol document is the adapter authors' contract.
3. **Shipped:** `usdAecoPipe` + the ifcopenshell adapter (S4): pipes first because
   ports are already core and the file route needs no host.
4. **Adapter shipped; live acceptance pending:** Revit (S1–S3), with a responding endpoint and a matching native fixture required.
5. **Reference mode shipped:** the Bonsai mode of the ifcopenshell adapter (S5).
6. **Libraries shipped:** `usdAecoBuildUp` + `usdAecoWall`; available IFC
   and Bonsai wall paths exercised, full adapter parity remains open (S3).
7. **Next:** ducts, cable carriers, beams and columns reuse axis + section + the
   same adapter skeleton; `usdAecoFlowSegment` shrinks to what round and
   rectangular runs share beyond the axis (shape, and insulation as a
   covering element).

## 12.11 Corrections to 10 §10.3

Three cells of the kind-library table change: `usdAecoFlowSegment` no
longer carries the centreline (the axis is shared or core); the pipe
system API carries no `systemType` token (classification is the kind);
and `usdAecoWall` depends on `usdAecoBuildUp` explicitly. BuildUp (layered
elements) and FlowSegment (profile runs) are **shared section libraries**,
an explicit lower sub-tier: core ← section ← kind. Kind libraries may
sublayer sections and core; E3 forbids edges between kind libraries,
and E12 requires the whole graph to remain acyclic. The 0.1.0 BuildUp
manifest retains the broad `kind` tier label; the section sub-tier is
the documented schema-review distinction, not a new metadata contract.
The "two things to settle" stand as stated, with the second — system kinds
travel with the element kind they serve — now applied as: the *system
API* travels with the element kind, the system *kind* is classification.
