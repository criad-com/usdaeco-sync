"""Plain USD Axis and Proxy geometry; derived inputs never come from intent."""

import math
import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom, Vt


def derive_cameras(stage, target):
    """Delegate into an isolated scratch layer, preserving pipe/wall derivations.

    The companion clears its output. Copy only its owned sensor subtrees and
    properties into the transaction's existing derived layer, so the engine's
    snapshot/rollback also covers all CCTV results.
    """
    try:
        from usdaeco_cctv.derive import derive
        from usdaeco_cctv import iter_cameras, sensors_of, camera_type_of
    except ModuleNotFoundError as exc:
        if exc.name == "usdaeco_cctv":
            return None
        raise
    if Usd.SchemaRegistry().FindAppliedAPIPrimDefinition("AecoCctvSensorAPI") is None:
        return None
    # Rebuild against drivers, with the previous output absent. Otherwise the
    # companion can author only overs for existing guide meshes, which would
    # lose their definitions when we replace the owned subtree below.
    view = Usd.Stage.Open(stage.GetRootLayer())
    view.MuteAndUnmuteLayers(list(set(stage.GetMutedLayers()) | {target.identifier}), [])
    stage = view
    scratch = Sdf.Layer.CreateAnonymous("cctv.derived.usda")
    stats = derive(stage, scratch)
    paths = []
    for camera in iter_cameras(stage):
        paths.append(camera.GetPath().AppendProperty("aeco:cctv:mountHeight"))
        paths.extend(s.GetPath() for s in sensors_of(camera))
        typ = camera_type_of(camera)
        if typ:
            paths.append(typ.GetPath().AppendProperty("aeco:cctvType:sensorCount"))
    paths.append(Sdf.Path("/AecoCctvLooks"))
    old = target.customLayerData.get("aeco:sync:cctvDerivedPaths", [])
    for path in old:
        if target.GetObjectAtPath(path):
            edit = Sdf.BatchNamespaceEdit()
            edit.Add(Sdf.Path(path), Sdf.Path.emptyPath)
            target.Apply(edit)
    owned = []
    for path in sorted(set(paths)):
        if scratch.GetObjectAtPath(path):
            Sdf.CreatePrimInLayer(target, path.GetPrimPath() if path.IsPropertyPath() else path.GetParentPath())
            Sdf.CopySpec(scratch, path, target, path)
            owned.append(str(path))
    target.customLayerData = {**target.customLayerData,
        "aeco:sync:cctvDerivedPaths": Vt.StringArray(owned), "aeco:cctv:layer": "derived"}
    stage.GetSessionLayer().subLayerPaths.remove(scratch.identifier)
    return stats


def arc_points(start, middle, end, segments=32):
    a, b, c = map(lambda p: np.array(p, float), (start, middle, end))
    u = b - a
    normal = np.cross(u, c - a)
    if np.linalg.norm(normal) < 1e-12:
        raise ValueError("Arc points must be distinct and non-collinear")
    normal /= np.linalg.norm(normal)
    x = u / np.linalg.norm(u)
    y = np.cross(normal, x)
    bx, cx, cy = np.linalg.norm(u), np.dot(c - a, x), np.dot(c - a, y)
    center = a + x * (bx / 2) + y * ((cx * cx + cy * cy - bx * cx) / (2 * cy))
    radius = np.linalg.norm(a - center)
    e1 = (a - center) / radius
    e2 = np.cross(normal, e1)
    angle = lambda p: math.atan2(np.dot(p - center, e2), np.dot(p - center, e1)) % (
        2 * math.pi
    )
    mid, last = angle(b), angle(c)
    if mid > last:
        last -= 2 * math.pi
    return [
        center + radius * (math.cos(t) * e1 + math.sin(t) * e2)
        for t in np.linspace(0, last, segments + 1)
    ]


def mark(prim, source, role, approx, stamp):
    prim.ApplyAPI("AecoDerivedGeometryAPI")
    for name, val in [
        ("source", source),
        ("role", role),
        ("approx", approx),
        ("stamp", stamp),
    ]:
        prim.GetAttribute("aeco:derived:" + name).Set(val)


def derive_gprims(stage, prim, kind, stamp="aeco-sync 0.3.0", derived_view=None):
    if derived_view is None:
        from .stack import find_layer

        derived_view = Usd.Stage.Open(stage.GetRootLayer())
        intent = find_layer(stage, "intent.usda")
        if intent:
            derived_view.MuteLayer(intent.identifier)
    dv = derived_view.GetPrimAtPath(prim.GetPath())
    start = np.array(prim.GetAttribute("aeco:axis:start").Get(), float)
    end = np.array(prim.GetAttribute("aeco:axis:end").Get(), float)
    length = float(np.linalg.norm(end - start))
    if length <= 1e-12:
        raise ValueError("Cannot derive a degenerate axis")
    arc = prim.GetAttribute("aeco:axis:curve").Get() == "arc"
    points = (
        arc_points(start, prim.GetAttribute("aeco:axis:arcPoint").Get(), end)
        if arc
        else [start, end]
    )
    src = prim.GetAttribute("aeco:id").Get() or ""
    axis = UsdGeom.BasisCurves.Define(stage, prim.GetPath().AppendChild("Axis"))
    axis.GetTypeAttr().Set("linear")
    axis.GetWrapAttr().Set("nonperiodic")
    axis.GetCurveVertexCountsAttr().Set([len(points)])
    axis.GetPointsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*p) for p in points]))
    axis.GetExtentAttr().Set(
        Vt.Vec3fArray(
            [Gf.Vec3f(*np.min(points, axis=0)), Gf.Vec3f(*np.max(points, axis=0))]
        )
    )
    axis.GetPurposeAttr().Set("guide")
    mark(axis.GetPrim(), src, "axis", "arcSegmented" if arc else "exact", stamp)
    if kind == "pipe":
        od = (
            dv.GetAttribute("aeco:pipe:outerDiameter").Get()
            or prim.GetAttribute("aeco:pipe:nominalDiameter").Get()
        )
        proxy = UsdGeom.Cylinder.Define(stage, prim.GetPath().AppendChild("Proxy"))
        proxy.GetAxisAttr().Set("Z")
        proxy.GetRadiusAttr().Set(od / 2)
        proxy.GetHeightAttr().Set(length)
        matrix = Gf.Matrix4d(1)
        matrix.SetRotate(
            Gf.Rotation(Gf.Vec3d(0, 0, 1), Gf.Vec3d(*(end - start) / length))
        )
        matrix.SetTranslateOnly(Gf.Vec3d(*((start + end) / 2)))
        proxy.MakeMatrixXform().Set(matrix)
        proxy.GetExtentAttr().Set(
            [
                Gf.Vec3f(-od / 2, -od / 2, -length / 2),
                Gf.Vec3f(od / 2, od / 2, length / 2),
            ]
        )
    else:
        thickness = dv.GetAttribute("aeco:wall:thickness").Get() or 0.2
        height = prim.GetAttribute("aeco:wall:height").Get() or 3.0
        proxy = UsdGeom.Cube.Define(stage, prim.GetPath().AppendChild("Proxy"))
        proxy.GetSizeAttr().Set(1)
        rotation = Gf.Rotation(Gf.Vec3d(1, 0, 0), Gf.Vec3d(*(end - start) / length))
        if arc:
            lo, hi = np.min(points, axis=0), np.max(points, axis=0)
            dims = hi - lo + np.array([thickness, thickness, height])
            mid = (lo + hi) / 2 + np.array([0, 0, height / 2])
            matrix = Gf.Matrix4d().SetScale(Gf.Vec3d(*dims))
        else:
            dims = (length, thickness, height)
            mid = (start + end) / 2 + np.array(
                rotation.TransformDir(Gf.Vec3d(0, thickness / 2, height / 2))
            )
            matrix = Gf.Matrix4d().SetScale(Gf.Vec3d(*dims)) * Gf.Matrix4d().SetRotate(
                rotation
            )
        matrix.SetTranslateOnly(Gf.Vec3d(*mid))
        proxy.MakeMatrixXform().Set(matrix)
        proxy.GetExtentAttr().Set([Gf.Vec3f(-0.5), Gf.Vec3f(0.5)])
    proxy.GetPurposeAttr().Set("proxy")
    mark(proxy.GetPrim(), src, "proxy", "bbox" if arc else "defaultDims", stamp)
    UsdGeom.Imageable(prim).GetProxyPrimRel().SetTargets([proxy.GetPath()])
