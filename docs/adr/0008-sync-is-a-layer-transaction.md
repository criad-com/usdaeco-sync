# ADR-0008 — Sync is a layer transaction

**Status:** Accepted

## Context

An editor can author desired pipe or wall parameters, but the native host owns
constraint solving, regenerated bodies and validation. Directly sharing mutable
geometry loses the distinction between a request and what the host accepted.
Native connected-end edits may leave gaps or silently undo joined-wall changes.
A reusable adapter protocol must work with both files and running authoring tools,
while its USD artifacts remain legible without plugins.

## Decision

Use a sparse intent layer above independent result and diagnostic layers per host.
The adapter computes the intent delta against an intent-muted current view,
classifies it, validates versions and bindings, takes the connection closure,
applies one native transaction, reads back and publishes the result. Only
accepted or redundant opinions are cleared automatically. Refused opinions remain
pending until the editor withdraws or reauthors them.

**Empty intent = in sync** at the recorded transaction boundary for the selected
host. Host changes arrive as a new read-back; overlapping intent is a conflict.
The host wins in the authoritative current view. The composed stage can continue
to show pending intent as a preview, but reconciliation and derived-property
inputs always use the current view.

Gap policy is a session fact: keepConnected, disconnect or refuse. A constrained
wall end is refused while its join remains. Version, document, time, authority
and policy are layer metadata. Binding instances cache native handles without
adding another element identity. Diagnostics are transient typed prims with a
Scope fallback. Geometry is ordinary USD gprims carrying AecoDerivedGeometryAPI,
and flows out of hosts only.

The Python boundary and JSON wire representation are specified in the
[protocol README](../../README.md). Core remains unchanged and unaware of hosts.

## Consequences

The request and receipt are inspectable USD data, usable offline and in vanilla
runtimes. Adapters share collection, preflight, closure and diagnostic conventions.
Emptiness requires two actions: the adapter clears applied opinions; the editor
withdraws refused ones. Host failures preserve pending intent. A process lock and
staged native output protect ordinary transactions; multi-file publication is
not a crash-atomic database and needs a durable commit protocol for that guarantee.

File version tokens are document-wide, while future live adapters may use native
per-element tokens. Native host behavior and operation coverage remain explicit
adapter responsibilities. The current IFC/Bonsai implementations preserve the
S4/S5 evidence; production catalogs, generated fittings, broader authoring and
large-model performance remain subsequent work packages.
