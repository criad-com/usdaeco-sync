"""Author native receipts as drivers, derived attributes and ordinary USD meshes."""

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, Vt
from .derive import mark, derive_gprims
from .stack import facts


def prepare_native_prim(stage, item, host, version, document):
    """Materialize native-created elements/ports without introducing new types."""
    prim = stage.GetPrimAtPath(item["path"])
    if not prim:
        prim = UsdGeom.Xform.Define(stage, item["path"]).GetPrim()
    prim.ApplyAPI("AecoElementAPI")
    prim.GetAttribute("aeco:id").Set(item["id"])
    kind = item.get("kind")
    for api in {
        "pipe": ("AecoAxisAPI", "AecoPipeAPI"),
        "wall": ("AecoAxisAPI", "AecoWallAPI"),
        "fitting": ("AecoPipeFittingAPI",),
    }.get(kind, ()):
        prim.ApplyAPI(api)
    prim.ApplyAPI("AecoClassificationAPI", "ifc")
    code = {
        "pipe": "IfcPipeSegment",
        "wall": "IfcWall",
        "fitting": "IfcPipeFitting",
    }.get(kind)
    if code and not prim.GetAttribute("aeco:class:ifc:code").Get():
        prim.GetAttribute("aeco:class:ifc:code").Set(code)
    typ = item.get("type")
    if typ:
        catalog = stage.GetPrimAtPath(typ["path"]) or stage.CreateClassPrim(typ["path"])
        catalog.ApplyAPI("AecoTypeAPI")
        bind(
            catalog,
            host,
            typ["ref"],
            typ.get("localRef", ""),
            typ.get("version", version),
            document,
        )
        if "sizeTable" in item:
            catalog.ApplyAPI("AecoPipeTypeAPI")
            for column, prop in (
                ("nominal", "nominalDiameters"),
                ("outer", "outerDiameters"),
                ("inner", "innerDiameters"),
            ):
                catalog.GetAttribute("aeco:pipeType:" + prop).Set(
                    [r[column] for r in item["sizeTable"]]
                )
        if item.get("layers") is not None:
            catalog.ApplyAPI("AecoBuildUpAPI")
            catalog.GetAttribute("aeco:buildUp:thicknesses").Set(
                [r["width"] for r in item["layers"]]
            )
        prim.GetInherits().SetInherits(item.get("inherits", [typ["path"]]))
    for port in item.get("ports", []):
        pp = stage.GetPrimAtPath(port["path"]) or stage.DefinePrim(
            port["path"], "AecoPort"
        )
        pp.ApplyAPI("AecoPipePortAPI")
        pp.GetAttribute("aeco:id").Set(port["id"])
    return prim


def bind(prim, host, ref, local_ref, version, document):
    prim.AddAppliedSchema("AecoHostBindingAPI:" + host)
    for key, val in [
        ("ref", ref),
        ("localRef", local_ref),
        ("version", version),
        ("document", str(document)),
    ]:
        prim.CreateAttribute(f"aeco:host:{host}:{key}", Sdf.ValueTypeNames.String, custom=False).Set(str(val))


def write_mesh(stage, parent, entry, stamp):
    # Keep the converter's Geom name so its weaker body is replaced, not doubled.
    mesh = UsdGeom.Mesh.Define(stage, parent.GetPath().AppendChild("Geom"))
    vertices = entry["verts"]
    points = [Gf.Vec3f(*vertices[i : i + 3]) for i in range(0, len(vertices), 3)]
    if not points:
        raise ValueError(f"Empty mesh for {parent.GetPath()}")
    mesh.GetPointsAttr().Set(Vt.Vec3fArray(points))
    mesh.GetFaceVertexIndicesAttr().Set(entry["faces"])
    mesh.GetFaceVertexCountsAttr().Set([3] * (len(entry["faces"]) // 3))
    mesh.GetExtentAttr().Set(
        [
            Gf.Vec3f(*(min(p[i] for p in points) for i in range(3))),
            Gf.Vec3f(*(max(p[i] for p in points) for i in range(3))),
        ]
    )
    mesh.GetSubdivisionSchemeAttr().Set("none")
    mesh.GetPurposeAttr().Set("render")
    mesh.MakeMatrixXform().Set(Gf.Matrix4d(1))
    # Retire prior subsets, including weaker imported faces, before replacement.
    for child in mesh.GetPrim().GetChildren():
        if child.IsA(UsdGeom.Subset):
            child.SetActive(False)
    material_ids = entry.get("materialIds", [])
    if material_ids and len(material_ids) != len(entry["faces"]) // 3:
        raise ValueError("Per-face material id count differs from triangle count")
    for material_id in sorted(set(material_ids)):
        name = "Material_" + (str(material_id) if material_id >= 0 else "unassigned")
        path = mesh.GetPath().AppendChild(name)
        old = stage.GetPrimAtPath(path)
        if old:
            old.SetActive(True)
        subset = UsdGeom.Subset.CreateGeomSubset(
            mesh,
            name,
            UsdGeom.Tokens.face,
            [i for i, mid in enumerate(material_ids) if mid == material_id],
            "materialBind",
            UsdGeom.Tokens.partition,
        )
        subset.GetPrim().SetCustomDataByKey("ifc:materialId", material_id)
        if 0 <= material_id < len(entry.get("materials", [])):
            data = entry["materials"][material_id]
            material = UsdShade.Material.Define(
                stage, parent.GetPath().AppendChild("Materials").AppendChild(name)
            )
            material.GetPrim().SetDisplayName(data["name"])
            material.GetPrim().SetCustomDataByKey("ifc:styleId", data["instanceId"])
            UsdShade.MaterialBindingAPI.Apply(subset.GetPrim()).Bind(material)
    mark(
        mesh.GetPrim(),
        parent.GetAttribute("aeco:id").Get() or "",
        "body",
        "tessellated",
        stamp,
    )


def publish(session, receipt, result, host, version, document):
    stage = session.stage
    with Usd.EditContext(stage, result):
        for item in receipt["touched"]:
            prim = stage.GetPrimAtPath(item["path"])
            if item.get("active") is False:
                prim = prim or stage.OverridePrim(item["path"])
                prim.SetActive(False)
                continue
            if host == "revit" and item.get("id"):
                prim = prepare_native_prim(stage, item, host, version, document)
            if not prim:
                prim = UsdGeom.Xform.Define(stage, item["path"]).GetPrim()
            if item.get("kind") == "camera":
                publish_camera(stage, prim, item, host, version, document)
            if item.get("kind") in ("pipe", "wall", "fitting"):
                prim.ApplyAPI("AecoElementAPI")
                prim.ApplyAPI(
                    {
                        "pipe": "AecoPipeAPI",
                        "wall": "AecoWallAPI",
                        "fitting": "AecoPipeFittingAPI",
                    }[item["kind"]]
                )
                if item["kind"] != "fitting":
                    prim.ApplyAPI("AecoAxisAPI")
                if item.get("id"):
                    prim.GetAttribute("aeco:id").Set(item["id"])
                if item.get("name"):
                    prim.SetDisplayName(item["name"])
                if item.get("classification"):
                    prim.ApplyAPI("AecoClassificationAPI", "ifc")
                    prim.GetAttribute("aeco:class:ifc:code").Set(item["classification"])
            if "inherits" in item:
                prim.GetInherits().SetInherits(item["inherits"])
            for group in ("drivers", "derived"):
                for name, val in item.get(group, {}).items():
                    attr = prim.GetAttribute(name)
                    if attr:
                        attr.Set(val)
            if "matrix" in item:
                # Receipt matrices are world-space, USD element xforms are local.
                parent_world = UsdGeom.XformCache().GetLocalToWorldTransform(
                    prim.GetParent()
                )
                UsdGeom.Xformable(prim).MakeMatrixXform().Set(
                    Gf.Matrix4d(item["matrix"]) * parent_world.GetInverse()
                )
            bind(
                prim,
                host,
                item["ref"],
                item.get("localRef", ""),
                item.get("version", version),
                document,
            )
            for port in item.get("ports", []):
                pp = stage.GetPrimAtPath(port["path"])
                if not pp:
                    pp = stage.DefinePrim(port["path"], "AecoPort")
                pp.ApplyAPI("AecoPipePortAPI")
                if port.get("id"):
                    pp.GetAttribute("aeco:id").Set(port["id"])
                pp.GetAttribute("aeco:medium").Set("pipe")
                pp.GetAttribute("aeco:flowDirection").Set(port.get("flow", "undefined"))
                UsdGeom.Xformable(pp).MakeMatrixXform().Set(Gf.Matrix4d(port["matrix"]))
                pp.GetRelationship("aeco:connectedPorts").SetTargets(port["connected"])
                pp.GetAttribute("aeco:pipePort:nominalDiameter").Set(port["diameter"])
                bind(
                    pp,
                    host,
                    port["ref"],
                    port.get("localRef", ""),
                    port.get("version", version),
                    document,
                )
                if "exporterCandidates" in port:
                    pp.SetCustomDataByKey(
                        "aecoSync:exporterCandidates",
                        Vt.StringArray(port["exporterCandidates"]),
                    )
                    pp.SetCustomDataByKey(
                        "aecoSync:identityResolved", port["identityResolved"]
                    )
            returned_ports = {port["path"] for port in item.get("ports", [])}
            if host == "revit":
                for child in prim.GetChildren():
                    if (
                        child.GetTypeName() == "AecoPort"
                        and str(child.GetPath()) not in returned_ports
                    ):
                        child.SetActive(False)
            for name, targets in item.get("joins", {}).items():
                prim.GetRelationship(name).SetTargets(targets)
            mesh = receipt["meshes"].get(item["ref"])
            if mesh:
                write_mesh(stage, prim, mesh, receipt["stamp"])
        # File hashes are document-wide: refresh tokens on untouched bindings too.
        for prim in stage.TraverseAll():
            if prim.HasAPI("AecoHostBindingAPI", host):
                if host != "revit":
                    prim.GetAttribute(f"aeco:host:{host}:version").Set(version)
                prim.GetAttribute(f"aeco:host:{host}:document").Set(str(document))
    current = session.current()
    with Usd.EditContext(stage, session.layer("derived.usda")):
        for item in receipt["touched"]:
            prim = stage.GetPrimAtPath(item["path"])
            if prim and prim.IsActive() and item.get("kind") in ("pipe", "wall"):
                derive_gprims(stage, prim, item["kind"], derived_view=current)
    if any(item.get("kind") == "camera" or item.get("active") is False for item in receipt["touched"]):
        from .derive import derive_cameras
        derive_cameras(current, session.layer("derived.usda"))
    result.customLayerData = facts(host, document, version, session.policy)
    result.customLayerData = {
        **result.customLayerData,
        "aeco:sync:adapterVersion": receipt["stamp"],
        "aeco:sync:closure": Vt.StringArray(
            [
                item["ref"]
                for item in receipt["touched"]
                if item.get("active") is not False
            ]
        ),
    }


def publish_camera(stage, prim, item, host, version, document):
    """Catalog sensors are inherited; native occurrence overrides stay on sensors."""
    import json
    from .cctv import set_values, is_sensor

    prim.ApplyAPI("AecoElementAPI")
    prim.ApplyAPI("AecoCctvCameraAPI")
    prim.ApplyAPI("AecoClassificationAPI", "ifc")
    prim.GetAttribute("aeco:class:ifc:code").Set("IfcAudioVisualAppliance.CAMERA")
    level = item.get("levelBinding")
    if level:
        lp = stage.GetPrimAtPath(level["path"])
        if not lp or not lp.GetTypeName():
            lp = stage.DefinePrim(level["path"], "AecoLevel")
            lp.GetAttribute("aeco:id").Set(level["id"])
            lp.ApplyAPI("AecoClassificationAPI", "ifc")
            lp.GetAttribute("aeco:class:ifc:code").Set("IfcBuildingStorey")
            stage.GetEditTarget().GetLayer().pseudoRoot.SetInfo("fallbackPrimTypes", {
                **(stage.GetMetadata("fallbackPrimTypes") or {}),
                "AecoLevel": Vt.TokenArray(["Xform"]),
            })
        if lp and lp.GetTypeName() == "AecoLevel":
            if "matrix" in level:
                parent_world = UsdGeom.XformCache().GetLocalToWorldTransform(lp.GetParent())
                local = Gf.Matrix4d(level["matrix"]) * parent_world.GetInverse()
                UsdGeom.Xformable(lp).MakeMatrixXform().Set(local)
                lp.GetAttribute("aeco:elevation").Set(local.ExtractTranslation()[2])
            bind(lp, host, level["ref"], level.get("localRef", ""), level.get("version", version), document)
    if item.get("id"):
        prim.GetAttribute("aeco:id").Set(item["id"])
    typ = item.get("type")
    if typ:
        catalog = stage.GetPrimAtPath(typ["path"]) or stage.CreateClassPrim(typ["path"])
        catalog.ApplyAPI("AecoTypeAPI")
        catalog.ApplyAPI("AecoCctvCameraTypeAPI")
        bind(catalog, host, typ["ref"], typ.get("localRef", ""), typ.get("version", version), document)
        set_values(catalog, typ.get("drivers", {}))
        for sensor in typ.get("sensors", []):
            sp = UsdGeom.Camera.Define(stage, catalog.GetPath().AppendChild(sensor["name"])).GetPrim()
            sp.ApplyAPI("AecoCctvSensorAPI")
            set_values(sp, sensor["drivers"])
            bind(sp, host, typ["ref"], typ.get("localRef", ""), typ.get("version", version), document)
        prim.GetInherits().SetInherits([typ["path"]])
    for sensor in item.get("sensors", []):
        sp = stage.GetPrimAtPath(prim.GetPath().AppendChild(sensor["name"]))
        sp = sp or UsdGeom.Camera.Define(stage, prim.GetPath().AppendChild(sensor["name"])).GetPrim()
        sp.SetActive(True)
        sp.ApplyAPI("AecoCctvSensorAPI")
        set_values(sp, sensor.get("drivers", {}))
        if "tour" in sensor:
            sp.GetAttribute("aeco:cctvSensor:tour").Set(sensor["tour"])
        for api in sp.GetAppliedSchemas():
            if api.startswith("AecoCctvPresetAPI:") and api.split(":", 1)[1] not in sensor.get("presets", {}):
                sp.RemoveAPI("AecoCctvPresetAPI", api.split(":", 1)[1])
        for name, values in sensor.get("presets", {}).items():
            sp.ApplyAPI("AecoCctvPresetAPI", name)
            set_values(sp, {"aeco:cctvPreset:" + name + ":" + k: v for k, v in values.items()})
        bind(sp, host, sensor.get("ref", item["ref"]), sensor.get("localRef", ""), item.get("version", version), document)
        sp.SetCustomDataByKey("aecoSync:nativeIndex", sensor.get("nativeIndex", 1))
        sp.SetCustomDataByKey("aecoSync:bindingRefs", Vt.StringArray(sensor.get("refs", [])))
    if "sensors" in item:
        returned = {s["name"] for s in item["sensors"]}
        for child in prim.GetAllChildren():
            if is_sensor(child) and child.GetName() not in returned:
                child.SetActive(False)
    # DORI visibility and native placement facts have no C1 schema drivers.
    # Retain them losslessly as receipt evidence, without inventing schema fields.
    evidence = {k: item[k] for k in ("mark", "cameraParameters", "typeParameters", "subInstances", "location", "rotation", "mirrored", "level", "offsetFromHost", "typeName") if k in item}
    prim.SetCustomDataByKey("aecoSync:cameraEvidence", json.dumps(evidence, sort_keys=True))
