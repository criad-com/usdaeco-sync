# 11 · How the hosts model walls and pipes — research for a two-way sync

This document is the evidence base for [12](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/12-wall-pipe-libraries-and-sync.md).
It answers six questions about the three environments a wall or a pipe
must round-trip through — the IFC schema as read and written by
**ifcopenshell**, **Bonsai** as the live IFC host, and **Revit** as the
parametric host — and it records what was verified against source code
or a running library and what remains to be confirmed on a live host.

1. What *is* a wall or a pipe in each environment — which values are
   parameters, which are computed, where the section lives?
2. What happens when one is **extended or moved** — does the host fill the
   gap, move the neighbour, insert a piece, or refuse?
3. How are **joins and fittings** represented, and who creates them?
4. What **validation** does each environment produce, and in what form?
5. What differs between talking to a **live host** and to a **file**?
6. What **geometry kernel** produces the meshes, and in what form?

Verification levels used below: **[src]** read in the source code
(ifcopenshell 0.8.5 as installed; Bonsai and the open-source Revit IFC
exporter at their current `v0.8.0` / `master` branches), **[run]**
executed — headlessly with ifcopenshell, or through the API of a live
Revit 2027.2 session — in the spikes of §11.8, **[doc]** stated in the
vendor's API documentation.

## 11.1 Findings in ten lines

- All three environments share one anatomy for both kinds: a **driving
  axis** (IFC `Axis` representation, Revit `LocationCurve`, Bonsai's axis
  polyline), a **section owned by the type** (layer set for walls, profile
  or size table for pipes), a **derived body**, and **end relations**
  (path joins for walls, ports for pipes).
- **Length is never a parameter.** Revit's length parameter is read-only;
  IFC's extrusion depth follows the axis; Bonsai edits length by rewriting
  the axis and the depth together. The axis is the driver.
- **No environment solves from bare values.** A length change on a
  connected end produces a gap unless something moves the neighbour: Revit
  does it through its connector constraints only for a *move* of an
  element (`MoveElement`: fittings follow, collinear neighbours stretch,
  perpendicular ones translate) — a `LocationCurve` edit on a connected
  end leaves the pair *logically* connected with the connectors a metre
  apart and raises nothing, even at commit **[run]**; Bonsai does it on
  commit by translating neighbours and extending segments (never
  rotating) **[src]**; a plain IFC file does nothing **[run]**.
- **A recorded wall join is a constraint, not a decoration.** ifcopenshell's
  wall regeneration trims *and extends* a wall's axis to its joined
  neighbour; an axis edited past the join is trimmed back **[run]**. Revit
  behaves the same way from the other side: a `LocationCurve` edit that
  would move a joined end is silently ignored, while moving the
  neighbour stretches or shortens the wall to keep the join **[run]**.
- **A pipe gap is invisible to IFC validation.** Two ports 0.5 m apart and
  still "connected" pass schema and rule checks with zero findings
  **[run]**. Gap detection is the sync layer's job.
- **Fittings are elements, never implied — except at commit.** Revit
  creates elbows, tees and unions only when asked (`NewElbowFitting` and
  kin, with take-out applied to the pipes) and two free connectors that
  come to coincide do not connect by themselves; but a diameter change
  committed against fittings of another size makes Revit *insert
  transition fittings* at both ends of the pipe, and remove them again
  when the size is reverted **[run]**. Bonsai and ifcopenshell build
  fittings only on an explicit operation **[src]**.
- **Section changes propagate through the type — but Revit does not
  police the table.** Wall thickness is the layer set (Revit compound
  structure); pipe outer and inner diameter come from the size table
  keyed by nominal diameter. Through the API a pipe accepts *any*
  diameter — 33 mm between two table rows, 250 mm beyond the table's
  end — with no failure at commit **[run]**; the table is a UI and
  routing constraint, so the sync layer must validate sizes itself.
- **Diagnostics are structured in Revit, strings elsewhere.** Revit
  failures carry severity, a definition id, failing element ids and
  resolutions (a door left outside its shortened host is an *Error*,
  "Instance(s) of … not cutting anything", captured with both element
  ids and rolled back by a failure preprocessor **[run]**); persistent
  warnings are readable from the document at any time; ifcopenshell
  yields rule-check log lines and geometry log entries; Bonsai operators
  report free-text messages.
- **Revit never rebuilds native elements from IFC.** Its importer creates
  `DirectShape` geometry. Native creation from any exchange format is an
  adapter's job; the driver set is what the adapter needs.
- **Bonsai and the file are one adapter.** Everything Bonsai does to the
  IFC model goes through `ifcopenshell.api`; the live host only adds
  Blender views, lazy placement commits and a few regeneration algorithms
  that are short enough to port.

## 11.2 IFC — what the schema says a wall and a pipe are

**Wall.** `IfcWall` (with `PredefinedType` from `IfcWallTypeEnum`:
ELEMENTEDWALL, MOVABLE, PARAPET, PARTITIONING, PLUMBINGWALL, POLYGONAL,
RETAININGWALL, SHEAR, SOLIDWALL, STANDARD, WAVEWALL) typed by
`IfcWallType`. A standard wall carries two representations: an **Axis**
(`Plan/Axis/GRAPH_VIEW`, a 2D polyline from the start to the end of the
wall) and a **Body** (`Model/Body/MODEL_VIEW`, an `IfcExtrudedAreaSolid`
of a rectangle or composite profile extruded in +Z, wrapped in
`IfcBooleanClippingResult` half-space clips where joins cut it). The
section is the type's `IfcMaterialLayerSet` (layers with
`LayerThickness`, `Priority`, `Category`), applied to the occurrence
through `IfcMaterialLayerSetUsage` (`LayerSetDirection` AXIS2,
`DirectionSense` POSITIVE|NEGATIVE, `OffsetFromReferenceLine`) — the
usage is how the axis relates to the layers, i.e. IFC's location line.
Joins are `IfcRelConnectsPathElements` with `RelatingConnectionType` /
`RelatedConnectionType` in ATSTART, ATEND, ATPATH and per-layer priority
lists; openings are `IfcRelVoidsElement` → `IfcOpeningElement` →
`IfcRelFillsElement` (door, window). Properties: `Pset_WallCommon`
(Reference, Status, AcousticRating, FireRating, Combustible,
SurfaceSpreadOfFlame, ThermalTransmittance, IsExternal, LoadBearing,
ExtendToStructure, Compartmentation) and `Qto_WallBaseQuantities`
(Length, Width, Height, Gross/NetFootPrintArea, Gross/NetSideArea,
Gross/NetVolume, Gross/NetWeight) **[src: IFC4X3 templates via
ifcopenshell]**.

**Pipe.** `IfcPipeSegment` (`IfcPipeSegmentTypeEnum`: CULVERT,
FLEXIBLESEGMENT, GUTTER, RIGIDSEGMENT, SPOOL) typed by
`IfcPipeSegmentType`. Body: an `IfcExtrudedAreaSolid` of the section
profile — for a pipe an `IfcCircleHollowProfileDef` (radius, wall
thickness) — extruded along local +Z; the profile is owned by the type's
`IfcMaterialProfileSet` and applied through `IfcMaterialProfileSetUsage`
(cardinal point). Connectivity: `IfcDistributionPort` prims
(`PredefinedType` PIPE, `FlowDirection` SOURCE|SINK|SOURCEANDSINK|
NOTDEFINED) nested under the element with `IfcRelNests` (IFC2X3:
`IfcRelConnectsPortToElement`) and placed relative to it; a port has at
most one `IfcRelConnectsPorts`. Fittings are `IfcPipeFitting`
(`IfcPipeFittingTypeEnum`: BEND, CONNECTOR, ENTRY, EXIT, JUNCTION,
OBSTRUCTION, TRANSITION) with their own ports. Systems are
`IfcDistributionSystem` groups. Properties: `Pset_PipeSegmentTypeCommon`
(Reference, Status, WorkingPressure, PressureRange, TemperatureRange,
**NominalDiameter, InnerDiameter, OuterDiameter, Length**),
`Pset_PipeSegmentOccurrence` (InteriorRoughnessCoefficient, Colour,
Gradient, InvertElevation), `Qto_PipeSegmentBaseQuantities` (Length,
Gross/NetCrossSectionArea, OuterSurfaceArea, Gross/NetWeight,
FootPrintArea); on ports `Pset_DistributionPortTypePipe`
(ConnectionType, ConnectionSubtype, NominalDiameter, InnerDiameter,
OuterDiameter, Temperature, VolumetricFlowRate, MassFlowRate,
FlowCondition, Velocity, Pressure) **[src]**. Insulation is a separate
covering element in IFC and in Revit alike, not a property of the
segment.

**What IFC does not say.** IFC is a description, not a solver. Nothing
requires connected ports to coincide, a joined wall's body to reach its
neighbour, or a fitting to exist between two segments that meet at an
angle. Every such fact is *interpreted* by the tool that regenerates
geometry, which is why the regenerating tool's rules — not the schema —
decide what an edit means.

## 11.3 ifcopenshell — kernel, authoring API, regeneration, validation

**Kernel.** The geometry engine is Open CASCADE (OCCT). A CGAL kernel
exists as a build option; the PyPI wheel used here (0.8.5) rejects the
`kernel = cgal` setting ("Setting not available") **[run]**. Output is a
triangulation (vertices, faces, edges, per-face material ids) from
`ifcopenshell.geom.create_shape(settings, product)` for one product or
the multithreaded `iterator` for a file; with pythonocc installed,
`use-python-opencascade` returns OCCT `TopoDS_Shape` objects instead
**[src]**. Relevant settings: `precision`, `layerset-first`,
`enable-layerset-slicing` (per-layer wall solids), `disable-boolean-result`,
`unify-shapes`, `triangulation-type` **[run]**.

**Authoring API.** `ifcopenshell.api` is a flat set of use-case functions;
the ones a wall/pipe adapter needs, all present in 0.8.5 **[src]**:

| Area | Functions | Notes |
|---|---|---|
| Wall body | `geometry.add_wall_representation(length, height, thickness, direction_sense, offset, x_angle, clippings, booleans)`, `geometry.create_2pt_wall` | metres; clippings are half-space definitions |
| Axis | `geometry.add_axis_representation(context, axis)` | straight two-point axes only; start = min local X for walls |
| Joins | `geometry.connect_path(relating, related, relating_connection, related_connection)`, `geometry.connect_wall(wall1, wall2, is_atpath)` (derives ATSTART/ATEND/ATPATH from the axes), `geometry.disconnect_path` | `connect_path` removes any incompatible existing connection at the same end |
| Regeneration | `geometry.regenerate_wall_representation(wall)` | see below |
| Placement | `geometry.edit_object_placement(product, matrix, is_si, should_transform_children)` | world matrix; children (ports, openings, fillings) either follow (`True`) or keep world position |
| Profiles | `geometry.add_profile_representation(context, profile, depth, cardinal_point, clippings)` | the pipe/beam body |
| Materials | `material.add_material_set(set_type=IfcMaterialLayerSet|IfcMaterialProfileSet)`, `add_layer`, `edit_layer`, `add_profile`, `assign_material` | assigning a set to the **type** and then `type.assign_type` creates the **usage** on the occurrence automatically **[run]** |
| Ports | `system.add_port(element)` (creates and nests), `assign_port`, `connect_port(port1, port2, direction)`, `disconnect_port` | one connection per port |
| Fittings | `util.shape_builder.ShapeBuilder.mep_bend_shape(segment, start_length, end_length, angle, radius, bend_vector, flip_z_axis)`, `mep_transition_shape(...)`, `mep_transition_calculate` | parametric fitting bodies; nothing calls them automatically |
| Queries | `util.system.get_ports / get_connected_port / get_connected_to / get_connected_from`, `util.representation.get_reference_line`, `util.element.get_material / get_material_layers / get_material_profiles`, `util.shape.*` (bbox, volume, areas from a triangulation) | |
| Boolean edits | `geometry.clip_solid`, `clip_solid_bounded`, `add_boolean`, `remove_boolean` | clippings survive regeneration only if registered with the element (a `BBIM_Boolean` pset) |

**Wall regeneration semantics** **[src docstring + run]**. The function
reads the axis, the placement, the layer set usage and every
`IfcRelConnectsPathElements` on the wall; it rebuilds the body as a 2D
profile (composite if an ATPATH join cuts through) extruded in +Z, with
per-connection boolean differences for sloped walls; it **updates the
axis** (trimming it to connections) and **resets the placement** to the
axis start, transforming children with it. Mitre versus butt is decided
by layer **priorities** (equal priority → mitre). The spike confirms the
edit semantics that matter for a sync:

| Step | Action | Result |
|---|---|---|
| W1 | L-corner: `connect_wall(A, B)` → ATEND/ATSTART; regenerate both | both bodies lose half the corner block (mitre); 4 ms |
| W2 | edit A's axis from 4 m to 5 m past the join; regenerate | A's axis is **trimmed back to 4 m**: the join wins over the axis edit |
| W3 | move B by +1 m (children follow); regenerate **A only** | A's axis is **extended to 5 m** to meet B: the gap closes without touching B |

So on the file route a joined wall is a constraint system with one rule:
a wall's axis ends where its joined neighbour's face is. "Extend wall A"
is therefore only a valid intent for an unjoined end, or as "move B".

**Pipe edits** **[run]**. There is no segment regeneration function;
the file adapter does three things itself: set the extrusion `Depth`,
move the end port's placement, and — under a keep-connected policy —
translate the downstream element with its children by the port delta.
Two pipes with ports connected at 2.0 m; depth 2.0 → 2.5 m and the end
port moved: a 0.5 m gap, the ports still connected, **schema and WHERE
rule validation: zero findings**. Translating the neighbour with
`should_transform_children=True` closes the gap; the whole edit,
validation and re-tessellation took 1.5 s, of which validation dominates.

**Validation surfaces** **[src/run]**: `ifcopenshell.validate.validate(
file, logger, express_rules=True)` (attribute types, cardinalities, WHERE
rules; needs pytest for the rule executor) with a JSON logger option;
geometry failures appear in the library log during shape creation;
information-requirement checks run through `ifctester` (IDS). None of the
three sees a gap, an overlap or a missing fitting: those are the sync
layer's own checks.

## 11.4 Bonsai — the live IFC host

**Model of truth** **[src]**. The IFC model held in memory is the
document; Blender objects are views of products. A moved Blender object
is *not* written to IFC immediately: `tool.Geometry.commit_placement_if_moved`
runs when the next IFC operation needs the placement (regeneration,
save, export). Regeneration is explicit — an operator or gizmo — never a
depsgraph side effect.

**Walls** **[src: `bim/module/model/wall.py`, `tool/model.py`]**.
`DumbWallJoiner` implements `extend`, `set_length`, `split`, `merge`,
`unjoin` by editing the axis and the `IfcRelConnectsPathElements` set,
then `tool.Model.recreate_wall` → `regenerate_wall_representation`.
Operators: `bim.join_walls_intersection`, `bim.extend_walls_to_wall`,
`bim.extend_walls_to_underside`, `bim.extend_wall_to_cursor`,
`bim.split_wall`, `bim.merge_wall`, `bim.flip_wall`, `bim.align_wall`,
`bim.unjoin_walls`, `bim.recalculate_wall`, plus join and extend gizmos.
`tool.Model.recalculate_walls(walls)` builds a queue of each wall **and
every wall it is connected to or from**, commits pending placements,
re-syncs the placements of openings whose fillings moved, then
regenerates each wall in the queue. The neighbour update is therefore
one call away but not automatic on a plain move.

**MEP** **[src: `bim/module/model/mep.py`, `profile.py`]**. A segment is
the type's profile extruded along local +Z; `MEPGenerator.setup_ports`
places the start port at the origin and the end port at the extrusion
depth. Fittings are created only by operators — `bim.mep_add_bend`,
`bim.mep_add_transition`, `bim.mep_add_obstruction`, `FitFlowSegments`
(suggests a fitting type, needs confirmation) — which shorten the
segments (`DumbProfileJoiner.join_E`), build the body with the shape
builder and `connect_port` the ends. Length edits go through
`DumbProfileJoiner.set_depth` and, on commit of the parametric edit,
dispatch `bim.regenerate_distribution_element`: a breadth-first walk
over the port graph that **extends segments to meet their predecessor's
port and translates everything else by the port delta, never rotating**
— failure to re-align is reported but does not roll back the length
edit. Bends are rejected for non-round, non-rectangular profiles, when
the corner would fall inside a segment, or when a double bend is
detected; obstructions are rejected when the port is already connected
or the length exceeds the segment.

**Diagnostics** are operator reports (`ERROR`, `WARNING`) — strings —
plus the same IFC validation and IDS tooling as the library.

**Live versus headless.** Blender can run Bonsai in background mode, but
everything above except the two convenience algorithms
(`recalculate_walls`, `regenerate_distribution_element`) is
`ifcopenshell.api`; both algorithms are under two hundred lines over
`util.system` and `regenerate_wall_representation`, so a file adapter
can reproduce them without Blender. The difference between "against
Bonsai" and "against an .ifc" is who refreshes the view and who owns the
transaction, not what the edit does.

## 11.5 Revit — the parametric host

**Wall** **[doc]**. `Wall` is a system family driven by a
`LocationCurve` (line or arc; settable), a type with a
`CompoundStructure` (layers with width, function — Structure, Substrate,
Insulation, Finish 1/2, Membrane — material and wrapping), and
parameters: base constraint and offset, top constraint and offset,
unconnected height, **location line** (wall centreline, core centreline,
finish face exterior/interior, core face exterior/interior), `Flipped`,
room bounding, structural usage, function. Length, area and volume are
read-only. Joins are automatic: ends that meet within tolerance join,
with `JoinType` butt, mitre or square-off per end; `WallUtils.
DisallowWallJoinAtEnd` / `AllowWallJoinAtEnd` toggle them and re-allowing
re-joins immediately; `LocationCurve.ElementsAtJoin(end)` lists and
orders the partners. Doors and windows are hosted family instances that
move with the host; a wall shortened past a hosted instance raises an
*Error* ("Instance(s) of <type> not cutting anything", one resolution:
delete) — provided the instance actually cuts the host; an instance
placed with the level-taking overload in the spike was hosted but did
not cut, and raised nothing **[run]**. A `LocationCurve` edit that would
move a *joined* end is silently ignored **[run]**.

**Pipe** **[doc/src]**. `Pipe : MEPCurve` with a `LocationCurve` (lines
only), a `PipeType` whose `RoutingPreferenceManager` holds rules for
segments and fittings by size range, and a `PipeSegment` (material +
schedule) whose size table maps **nominal diameter → inner and outer
diameter**. `MEPCurve.Diameter`, `Width`, `Height` are **read-only
properties** (2025 API reference); the diameter is changed through the
`RBS_PIPE_DIAMETER_PARAM` parameter (or the connectors' read-write
`Radius`), and connected fittings resize through their lookup tables
(`.csv` sized by nominal diameter). Through the API the parameter takes
any value without failure; where a fitting cannot follow the size,
Revit inserts a transition fitting at commit (§11.5, "what happens on
an edit") **[run]**. Connectors (`ConnectorManager`)
carry origin, coordinate system, radius, domain, `Direction`
(In/Out/Bidirectional), `IsConnected`, `AllRefs`, and `ConnectTo` /
`DisconnectFrom`. Fittings are family instances created by
`Document.Create.NewElbowFitting`, `NewTeeFitting`, `NewCrossFitting`,
`NewTransitionFitting`, `NewUnionFitting`, `NewTakeoffFitting` — the
elbow call is documented as equivalent to the Trim tool, and Revit
"automatically adjusts the newly created element appropriately to
connect with the existing elements" (a pipe between two fittings need
not be given an exact direction). Precision matters: an unnormalised
direction vector on a `LocationCurve` was enough to break a tee
connection in a documented case.

**What happens on an edit** — the part that decides the sync design:

| Edit | Revit behaviour (2027.2, through the API) | Status |
|---|---|---|
| Extend a pipe's free end (`LocationCurve.Curve`) | plain curve change; nothing else | [run] |
| Move a pipe's **connected** end with `LocationCurve.Curve` | the curve changes, the connector stays *logically* connected to the fitting, the fitting does not move: a 1 m gap between "connected" connectors, no warning, no failure at commit | [run] |
| Extend a pipe past its elbow with `LocationCurve.Curve` | same: overlap, connection kept, nothing raised | [run] |
| `MoveElement` a pipe along its neighbour's axis | the elbow moves, the collinear neighbour stretches | [run] |
| `MoveElement` a pipe perpendicular to itself | its tee and elbow translate, the perpendicular pipes at both shorten, the branch translates | [run] |
| `MoveElement` a tee | one main pipe stretches, the other shortens, the branch translates | [run] |
| Two free connectors made coincident | no automatic connection | [run] |
| `NewElbowFitting` / `NewUnionFitting` on two connectors | the fitting from the routing preference appears; both pipes are shortened by its take-out (33 mm for the generic elbow, 40 mm for the tee, 13.5 mm for the union at DN50) | [run] |
| Set the diameter to a table size (65 mm) | connectors resize at once; the generic elbow and tee keep 50 mm; at commit Revit inserts `M_Transition - Generic` reducers at both ends of the pipe and shortens it further; reverting removes them | [run] |
| Set the diameter to 33 mm or 250 mm (not in the table) | accepted, no failure | [run] |
| `DisconnectFrom` then `MoveElement` | the API's Disjoin: the pipe moves alone, the fitting keeps a free connector; `ConnectTo` reconnects after moving back | [run] |
| Move a wall whose ends are joined (`MoveElement`) | the joined neighbour stretches or shortens to keep the join, in both directions; a hosted door moves with its wall | [run] |
| `LocationCurve` edit that moves a joined wall end (extend past, pull back, shorten) | silently ignored — the join wins; after `DisallowWallJoinAtEnd` the same edit works, and `AllowWallJoinAtEnd` re-joins at the next regeneration | [run] |
| `LocationCurve` edit on the unjoined end | works | [run] |
| Shorten a wall past a cutting door | *Error* "Instance(s) of <type> not cutting anything", failing ids = wall and door, one resolution; rolled back by the preprocessor | [run] |
| Change a wall's type | width changes, joins and the door stay | [run] |
| `Wall.Flip()` | flips; joins stay | [run] |

**Failures** **[doc]**. `Transaction.Commit` runs failure processing:
`FailuresAccessor.GetFailureMessages()` yields `FailureMessageAccessor`
with `GetSeverity()` (Warning, Error, DocumentCorruption),
`GetFailureDefinitionId()`, `GetDescriptionText()`,
`GetFailingElementIds()`, `GetAdditionalElementIds()` and the available
resolutions; an `IFailuresPreprocessor` decides to resolve, delete
warnings, or roll back. This is the richest diagnostics surface of the
three and maps directly onto a structured record.

**Change tracking** **[doc]**. `Element.VersionGuid` changes between
saves, synchronizations and reloads — not per transaction — so it is a
cross-session change token, not an in-session one; in-session changes
come from the `DocumentChanged` event (`GetAddedElementIds`,
`GetModifiedElementIds`, `GetDeletedElementIds`, mutually exclusive
sets, raised on commit, undo and redo).

**The IFC exporter** **[src: `Autodesk/revit-ifc`]**. Walls export as
`IfcWall` (`IfcWallStandardCase` only for IFC2x2 and older) with an Axis
representation and a body that is tried first as an extrusion with
clippings and falls back to tessellation or B-rep; layers export as a
layer set usage; **wall joins export as `IfcRelConnectsPathElements`**
(from `ExporterIFCUtils.GetConnectedWalls` at each end; suppressed for
the Reference View). Connectors export as `IfcDistributionPort` with flow
direction, nested with `IfcRelNests` (IFC4) and connected with
`IfcRelConnectsPorts`; the port GUID is generated from the host element
and the connector id. Extrusions with a circular loop become
`IfcCircleProfileDef` / `IfcCircleHollowProfileDef`; in the spike's IFC4
export the pipes came out as `IfcExtrudedAreaSolid` over a *solid*
`IfcCircleProfileDef` of the outer radius, with no material and a
`Pset_PipeSegmentTypeCommon` carrying only `Reference` — the nominal
diameter is not in the default export **[run]**. Fittings export as
`IfcMappedItem` bodies with `PredefinedType` NOTDEFINED. MEP curves go
through the generic body exporter (extrusion analysis, tessellation
fallback at the lowest level). Pipe insulation exports as a covering.
Element, port and relationship GUIDs were identical across two exports
of the same document, the element GUID is written back to the IFC GUID
parameter, and the **port GUID recipe is reproducible** outside Revit
(§11.8) **[run]**.
The **importer** builds `DirectShape` elements: there is no path from an
IFC file back to a native `Pipe` or `Wall` without an adapter.

## 11.6 The gap question, answered

"If I prolong or move a pipe or a wall, does the host add supporting
pieces so there is no gap?"

| Operation | IFC file (ifcopenshell) | Bonsai | Revit |
|---|---|---|---|
| Extend a **free** pipe end | adapter sets depth and moves the port; no side effects | `set_depth`; ports re-placed | curve change; nothing else |
| Extend a **connected** pipe end | gap; nothing notices; adapter translates the neighbour (spike) or shortens the next segment | on commit: neighbours translated, next segments extended, never rotated | by curve edit: silent gap, connection kept; by moving the fitting at that end: the pipe stretches and the rest follows; no new fitting |
| Move a whole pipe run | placements only; connections stay recorded; gap if partial | as above on regenerate | as above |
| Make two pipes meet at an angle | adapter builds a bend body and connects ports | `bim.mep_add_bend` | `NewElbowFitting` from routing preferences |
| Change nominal diameter | adapter swaps the profile (type) and rebuilds bodies; fittings rebuilt by the adapter | profile edit → `DumbProfileRecalculator` cascades to connected profiles | any value accepted; fittings that cannot follow get transition fittings inserted at commit |
| Extend a wall past a **joined** end | regeneration trims it back (spike W2) | same (same function) | the curve edit is silently ignored; works after disallowing the join |
| Move a joined wall's neighbour | regenerating the first wall extends it to the neighbour (spike W3) | `recalculate_walls` does exactly this for the connected set | the joined wall stretches or shortens to keep the join |
| Extend an **unjoined** wall end | axis + regenerate | `extend` / `set_length` | curve change; auto-join if it now meets another wall |
| Insert an opening | `IfcRelVoidsElement`; body unaffected until geometry time | opening tools | hosted instance / `NewOpening` |

Nothing inserts a piece to close a gap by itself. What every environment
offers is a **keep-connected regeneration**: move the neighbours so the
recorded connections hold, and extend path elements to their recorded
joins. Fittings appear only when an operation says "join these two".

## 11.7 What this means for the design

The findings reduce to eight razors that [12](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/12-wall-pipe-libraries-and-sync.md)
builds on:

- **R-a — The axis is the driver; length is derived.** All three agree.
- **R-b — One anatomy: axis + section-from-type → body, plus end
  relations.** Walls and pipes differ only in the section (layers versus
  profile) and the relation (path join versus port). Beams, columns,
  ducts and trays have the same anatomy.
- **R-c — Intent must be topological where ends are constrained.** A bare
  value on a joined or connected end is ambiguous; the sync layer must
  express "extend to meet X" or "move X with me", and carry a gap policy.
- **R-d — Fittings are elements; a host may generate them.** They need
  identity and a "generated" mark so an adapter can regenerate rather
  than reconcile them.
- **R-e — Sections belong to the type.** Nominal size is the occurrence's
  pick from the type's table; outer and inner diameter, thickness and
  layer widths are derived.
- **R-f — Diagnostics are host statements about elements, transient and
  structured.** Normalize to one record with severity, host-qualified
  code, message, elements; keep them out of the core and out of the
  record tier.
- **R-g — The file adapter and the Bonsai adapter are one code path.**
  Port the two regeneration algorithms; run the same code with or
  without Blender.
- **R-h — Revit is rebuilt from drivers, never from IFC geometry.** The
  driver set is the interface to every host; body geometry only ever
  flows *out* of a host.

## 11.8 Evidence

The headless spike (`ifcopenshell 0.8.5`, IFC4X3, metres) built two
walls with layer-set types, an L-join, and two port-connected DN50 pipes
with hollow-circle profiles, then edited them. Key lines of the
transcript (bounding boxes in metres, volumes in m³):

```
W1 connect_wall -> IfcRelConnectsPathElements ATEND / ATSTART   (regen 0.004 s)
W1 after join   A: axis [0,0]..[4,0]   vol 1.920 -> 1.872   (mitre)
W2 axis A edited to [0,0]..[5,0]; after regen: axis [0,0]..[4,0]   (trimmed back)
W3 B moved +1 m; regen A only: axis [0,0]..[5,0]  bbox ..[5.0,0.2,2.4]   (gap closed)
P0 P1 end [2,0,1] = P2 start [2,0,1]  gap 0.000  connected True
P1 depth 2.0 -> 2.5, end port moved: gap 0.500 m, still connected, validate: 0 findings
P2 neighbour translated by [0.5,0,0]: gap 0.000; P1 bbox ..[2.5], P2 bbox [2.5]..[4.0]   (1.5 s incl. validate)
```

The Revit spike ran through the API of a live Revit 2027.2 session on a
fresh multi-discipline metric project: a DN50 copper network (two runs,
an elbow, a split and a tee), two joined 200 mm walls with a door, each
edit in a transaction with a failure preprocessor and a before/after
diff of every element's curve, connectors and joins. Key lines:

```
baseline  P1 (0,0)->(2960) ->T1 | T1 at 3000 | P1b (3040)->(5967) ->E1 | E1 at 6000 | P2 (6000,33)->(6000,4000)
T2  LocationCurve P2 start -> (6000,-1000): P2 c0 at (6000,-1000) still ->E1#2; E1 unchanged; commit: failures none
T4  MoveElement P2 +1000 x: E1 at 7000, P1b stretched to 6967, P2 at x=7000
T5  MoveElement P1 +1000 y: T1, P1b, E1 translate; P2 and P3 shorten
T7c diameter P1b 65 mm, commit: P1b (3056)->(5950), NEW M_Transition - Generic x2; revert removes them
T8/T9 diameter 33 mm / 250 mm: accepted, failures none
T11 P3 extended to touch P5 (both free): no connection
W2  MoveElement WB +2000 x: WA stretched to 10000, still joined
W3/W4 LocationCurve WA end past / short of the join: no change, failures none
W3b DisallowWallJoinAtEnd then extend: WA 10000, joined=[]
W1d shorten WA past a cutting door: Error "Instance(s) of 1700 x 2000mm not cutting anything" els=wall,door -> rolled back
export IFC4: 4.6 s; 1 IfcRelConnectsPathElements ATEND/ATSTART; 13 ports, 6 IfcRelNests, 5 IfcRelConnectsPorts
port GUIDs: free connector = md5(elementGuid + "Sub-element:IfcDistributionPort Connector: " + id);
            connected pair = md5("InPort" + id + inGuid + outGuid) on the element processed first,
            md5("OutPort" + id + outGuid + inGuid) on the other; 13/13 reproduced in Python
```

The adapter spikes (S4, S5 of [12 §12.9](https://github.com/criad-com/usdaeco-core/blob/v0.8.4/docs/12-wall-pipe-libraries-and-sync.md#129-spikes-before-building))
ran the same scenario from an intent layer, once through the ifcopenshell
adapter and once through Bonsai's operators in headless Blender:

```
intent: Pipe 1 axis end 2.0 -> 2.5 (connected end) | Pipe 1 DN50 -> DN65 | Pipe 1 outerDiameter (derived) | Wall A axis end 4 -> 5 (joined) | Wall B +1 m
ifc adapter: Pipe 1 depth 2.5, end port moved; Pipe 2 start -> (2.5,0,1), depth 1.5 -> 1.0; profile OD 0.065; Wall B placed; Wall A regenerated to 5.0
             refused: sync:derivedAuthored, sync:joinedEnd | reported: sync:neighbourMoved x2, pipePortSizeMismatch | gaps: 0 | ifc rules: 0
bonsai:      set_depth 2.5 + regenerate_distribution_element; profile + DumbProfileRecalculator; move + recalculate_walls -> Wall A [[0,0],[5,0]]
compare:     68 properties equal within 1e-4, 0 differ
```

Sources consulted: the installed ifcopenshell package (API modules,
`util.shape_builder`, `geom` settings, `validate`); Bonsai
`src/bonsai/bonsai/bim/module/model/{wall,mep,profile}.py`,
`bim/module/geometry/operator.py`, `tool/model.py`; Autodesk
`revit-ifc` `Source/Revit.IFC.Export/Exporter/{WallExporter,
ConnectorExporter, ExtrusionExporter, GenericMEPExporter, Exporter}.cs`;
`Utility/GUIDUtil.cs`; the Revit API reference for `MEPCurve`,
`Element.VersionGuid`, `WallUtils`, `LocationCurve`,
`ElementTransformUtils`, routing preferences; a live Revit 2027.2 API
session; The Building Coder articles on pipe direction, connector
neighbours and the MEP API; buildingSMART IFC4.3 documentation for
`IfcRelConnectsPathElements` and `IfcExtrudedAreaSolid`.
