"""Port/join closure and the keepConnected, disconnect and refuse policies."""

from dataclasses import dataclass, field
import numpy as np
from pxr import UsdGeom, Gf

JOIN_NAMES = ("aeco:wall:joinAtStart", "aeco:wall:joinAtEnd", "aeco:wall:joinAlongPath")


@dataclass
class Closure:
    paths: list[str] = field(default_factory=list)
    policy: str = "keepConnected"
    disconnect: list[str] = field(default_factory=list)

    def wire(self):
        return {"paths": self.paths, "disconnect": self.disconnect}


def adjacency(stage):
    """Build reverse edges once; a closure walk must not rescan per neighbour."""
    graph = {}
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        for name in (*JOIN_NAMES, "aeco:connectedPorts"):
            rel = prim.GetRelationship(name)
            if not rel:
                continue
            for target in rel.GetTargets():
                a, b = path, str(target)
                if name == "aeco:connectedPorts":
                    a, b = str(prim.GetPath().GetParentPath()), str(
                        target.GetParentPath()
                    )
                graph.setdefault(a, set()).add(b)
                graph.setdefault(b, set()).add(a)
    return graph


def neighbours(stage, path):
    return adjacency(stage).get(str(path), set())


def walk(stage, roots):
    graph = adjacency(stage)
    seen, todo = set(), list(roots)
    while todo:
        path = str(todo.pop())
        if path in seen:
            continue
        seen.add(path)
        todo.extend(graph.get(path, set()) - seen)
    return sorted(seen)


def plan(session, edits, diagnostics):
    stage = session.current()
    accepted, roots, disconnected = [], [], []
    removed = {
        (e.path, e.name) for e in edits if e.operation == "relationship" and not e.value
    }
    removed.update(
        (e.path, "aeco:wall:joinAt" + ("Start" if e.name.endswith("Start") else "End"))
        for e in edits
        if e.name.startswith("aeco:wall:allowJoin") and e.value is False
    )

    def link_removed(path, name, target):
        for edit in edits:
            if (
                edit.operation == "relationship"
                and edit.path == path
                and edit.name == name
            ):
                if str(target) not in map(str, edit.value):
                    return True
            if edit.operation == "relationship" and edit.path == str(target):
                if (
                    edit.name in JOIN_NAMES
                    and path in map(str, edit.current)
                    and path not in map(str, edit.value)
                ):
                    return True
        return False

    for edit in edits:
        prim = stage.GetPrimAtPath(edit.path)
        if not prim:
            accepted.append(edit)
            continue
        if prim.HasAPI("AecoWallAPI") and edit.kind == "axis":
            which = "End" if edit.name.endswith(":end") else "Start"
            name = "aeco:wall:joinAt" + which
            rel = prim.GetRelationship(name)
            if (
                rel
                and any(not link_removed(edit.path, name, t) for t in rel.GetTargets())
                and (edit.path, name) not in removed
            ):
                diagnostics.add(
                    "error",
                    "sync:joinedEnd",
                    f"{edit.property_path} moves a joined wall end; remove its join or move the neighbour",
                    [edit.property_path],
                    blocking=True,
                )
                continue
        connected = []
        if prim.HasAPI("AecoPipeAPI") and edit.kind in ("axis", "transform"):
            for port in prim.GetChildren():
                rel = port.GetRelationship("aeco:connectedPorts")
                if (
                    not rel
                    or not rel.GetTargets()
                    or (str(port.GetPath()), "aeco:connectedPorts") in removed
                ):
                    continue
                pos = (
                    UsdGeom.Xformable(port)
                    .GetLocalTransformation()
                    .ExtractTranslation()
                )
                endpoint = prim.GetAttribute(
                    "aeco:axis:end" if edit.name.endswith(":end") else "aeco:axis:start"
                ).Get()
                if edit.kind == "transform" or (
                    endpoint is not None and Gf.IsClose(pos, Gf.Vec3d(endpoint), 1e-6)
                ):
                    connected.append(str(port.GetPath()))
        if connected and session.policy == "refuse":
            diagnostics.add(
                "error",
                "sync:constrainedEnd",
                "Connected end edit refused by session gap policy",
                [edit.property_path] + connected,
                blocking=True,
            )
            continue
        if connected and session.policy == "disconnect":
            disconnected.extend(connected)
            diagnostics.add(
                "info",
                "sync:disconnected",
                "Port links will be removed before moving the end",
                connected,
            )
        accepted.append(edit)
        roots.append(edit.path)
    return accepted, Closure(
        walk(stage, roots), session.policy, sorted(set(disconnected))
    )


def segment_near_end(start, end, target, near_start):
    """Bonsai rule: trim/extend near end, preserve far end, never rotate.

    A perpendicular displacement translates the segment, preserving direction;
    an axial displacement changes its length.
    """
    start, end, target = map(lambda p: np.asarray(p, float), (start, end, target))
    direction = end - start
    length = np.linalg.norm(direction)
    if length <= 1e-12:
        raise ValueError("Degenerate connected segment")
    unit = direction / length
    near = start if near_start else end
    delta = target - near
    perpendicular = delta - unit * np.dot(delta, unit)
    start, end = start + perpendicular, end + perpendicular
    if near_start:
        start = target
    else:
        end = target
    if np.dot(end - start, unit) <= 1e-9:
        raise ValueError("Connected segment would have non-positive length")
    return start, end
