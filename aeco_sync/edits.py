"""Collect sparse intent, including relationship list operations and activation."""

from dataclasses import dataclass
import json
from pxr import Gf, Sdf, Usd, UsdGeom
from .stack import PREFIX, all_specs, value


@dataclass
class Edit:
    path: str
    name: str
    value: object
    current: object
    kind: str
    operation: str = "attribute"
    noop: bool = False
    ref: str = ""
    section: dict | None = None
    fitting: str | None = None
    third_port: str | None = None

    @property
    def property_path(self):
        return (
            Sdf.Path(self.path)
            if self.operation in ("activation", "create")
            else Sdf.Path(self.path).AppendProperty(self.name)
        )

    def wire(self):
        result = {
            "path": self.path,
            "name": self.name,
            "value": value(self.value),
            "current": value(self.current),
            "kind": self.kind,
            "operation": self.operation,
            "ref": self.ref,
            "section": self.section,
        }
        if self.fitting:
            result["fitting"] = self.fitting
        if self.third_port:
            result["thirdPort"] = self.third_port
        return result


def equal(a, b):
    return value(a) == value(b)


def classify(prim, name, operation="attribute"):
    from .cctv import is_sensor, NATIVE
    if is_sensor(prim) and (name in NATIVE or name.startswith("xformOp:") or name == "xformOpOrder"):
        return "derived"
    prop = prim.GetProperty(name) if prim else None
    if prim and (
        prim.HasAPI("AecoDerivedGeometryAPI")
        or (prop and prop.GetMetadata("aecoDerived"))
    ):
        return "derived"
    if operation == "relationship":
        return "relation"
    if name.startswith("aeco:axis:"):
        return "axis"
    if name.startswith("xformOp:") or name == "xformOpOrder":
        return "transform"
    if (
        name == "aeco:pipe:nominalDiameter"
        or name.startswith("aeco:pipeType:")
        or name.startswith("aeco:buildUp:")
        or name.startswith("aeco:cctvSensor:")
        or name.startswith("aeco:cctvPreset:")
    ):
        return "section"
    return "semantic"


def collect(stage, intent, current):
    from .cctv import is_sensor
    edits = []
    created = []
    for spec in all_specs(intent):
        if any(spec.path.HasPrefix(path) for path in created):
            continue
        prim = stage.GetPrimAtPath(spec.path)
        curprim = current.GetPrimAtPath(spec.path)
        if (
            not curprim
            and spec.specifier == Sdf.SpecifierDef
            and (prim.HasAPI("AecoPipeAPI") or prim.HasAPI("AecoCctvCameraAPI"))
        ):
            # One atomic create: a partial set must never mint a half-built pipe.
            attrs = {
                p.name: p.default
                for p in spec.attributes.values()
                if p.HasInfo("default")
            }
            derived = any(classify(prim, p.name) == "derived" for p in spec.properties)
            data = {
                "attributes": attrs,
                "inherits": list(prim.GetInherits().GetAllDirectInherits()),
                "metadata": list(spec.ListInfoKeys()),
                "apis": list(prim.GetAppliedSchemas()),
                "relationships": [p.name for p in spec.relationships.values()],
            }
            if prim.HasAPI("AecoCctvCameraAPI"):
                from .cctv import is_sensor
                data["kind"] = "camera"
                data["sensors"] = []
                for descendant in all_specs(intent):
                    if descendant.path != spec.path and descendant.path.HasPrefix(spec.path):
                        dp = stage.GetPrimAtPath(descendant.path)
                        derived |= bool(dp and dp.IsA(UsdGeom.Gprim))
                        derived |= any(classify(dp, p.name) == "derived" for p in descendant.properties)
                for child in prim.GetAllChildren():
                    if not is_sensor(child):
                        continue
                    child_spec = intent.GetPrimAtPath(child.GetPath())
                    properties = list(child_spec.properties) if child_spec else []
                    derived |= any(classify(child, p.name) == "derived" for p in properties)
                    drivers = {p.name: p.default for p in properties if isinstance(p, Sdf.AttributeSpec) and p.HasInfo("default")}
                    for api in child.GetAppliedSchemas():
                        if api.startswith("AecoCctvPresetAPI:"):
                            prefix = "aeco:cctvPreset:" + api.split(":", 1)[1] + ":"
                            drivers.update({prefix + field: child.GetAttribute(prefix + field).Get()
                                            for field in ("pan", "tilt", "focalLength", "dwell", "home")})
                    data["sensors"].append({"name": child.GetName(), "drivers": drivers})
                created.append(spec.path)
            edits.append(
                Edit(
                    str(spec.path),
                    "create",
                    data,
                    None,
                    "derived" if derived else "semantic",
                    "create",
                )
            )
            continue
        for prop in spec.properties:
            if isinstance(prop, Sdf.AttributeSpec):
                # No authored value means no driver edit (e.g. inert declaration).
                if not prop.HasInfo("default") and not intent.ListTimeSamplesForPath(
                    prop.path
                ):
                    continue
                val = prop.default
                cur = current.GetAttributeAtPath(prop.path)
                before = cur.Get() if cur else None
                operation = "attribute"
                if intent.ListTimeSamplesForPath(prop.path):
                    operation = "timeSamples"
            else:
                if not prop.HasInfo("targetPaths"):
                    continue
                rel = stage.GetRelationshipAtPath(prop.path)
                val = list(rel.GetTargets()) if rel else []
                cur = current.GetRelationshipAtPath(prop.path)
                before = list(cur.GetTargets()) if cur else []
                operation = "relationship"
            kind = classify(curprim or prim, prop.name, operation)
            edits.append(
                Edit(
                    str(spec.path),
                    prop.name,
                    val,
                    before,
                    kind,
                    operation,
                    equal(val, before),
                )
            )
        for key in spec.ListInfoKeys():
            if key in ("active", "specifier"):
                continue
            edits.append(
                Edit(
                    str(spec.path),
                    key,
                    (
                        list(prim.GetInherits().GetAllDirectInherits())
                        if key == "inheritPaths"
                        else list(prim.GetAppliedSchemas()) if key == "apiSchemas" and prim and is_sensor(prim)
                        else spec.GetInfo(key)
                    ),
                    (
                        list(curprim.GetInherits().GetAllDirectInherits())
                        if key == "inheritPaths" and curprim
                        else None
                    ),
                    classify(curprim or prim, key),
                    "primMetadata",
                )
            )
        if spec.specifier != Sdf.SpecifierOver:
            edits.append(
                Edit(
                    str(spec.path),
                    "specifier",
                    str(spec.specifier),
                    None,
                    "semantic",
                    "primMetadata",
                )
            )
        if spec.HasInfo("active"):
            before = curprim.IsActive() if curprim else True
            edits.append(
                Edit(
                    str(spec.path),
                    "active",
                    spec.active,
                    before,
                    "semantic",
                    "activation",
                    spec.active == before,
                )
            )
    return edits


def preflight(session, edits, host, version, diagnostics):
    accepted, noops = [], []
    base = session.intent.customLayerData.get(PREFIX + "baseVersions", {}).get(
        host, session.version(host)
    )
    current = session.current()
    original = json.loads(
        session.intent.customLayerData.get(PREFIX + "baseValues", "{}")
    )
    for edit in edits:
        prim = current.GetPrimAtPath(edit.path) or session.stage.GetPrimAtPath(
            edit.path
        )

        def refuse(code, message):
            diagnostics.add("error", code, message, [edit.property_path], blocking=True)

        # Derived authorship is invalid even when it happens to equal the host.
        if edit.kind == "derived":
            refuse(
                "sync:derivedAuthored",
                f"{edit.property_path} is derived; withdraw the opinion",
            )
            continue
        from .cctv import camera_of, envelope, is_sensor
        camera = camera_of(prim)
        if camera:
            desired = session.stage.GetPrimAtPath(camera.GetPath())
            problem = envelope(desired) if desired and desired.IsActive() else None
            if problem and edit.operation != "activation":
                refuse("cctvOutOfEnvelope", problem)
                continue
        key = str(edit.property_path)
        if key in original and not equal(original[key], edit.current):
            refuse(
                "sync:conflict", f"Host changed {key}; redo or withdraw this opinion"
            )
            continue
        if base != version:
            refuse(
                "sync:staleIntent",
                f"{host} changed since this intent was based on {base}",
            )
            continue
        if edit.noop:
            noops.append(edit)
            continue
        if edit.operation == "create":
            accepted.append(edit)
            continue
        if camera:
            # Sensors have native sub-instance bindings; operations address their
            # owning device. Preserve the sensor path and index in the wire.
            edit.section = {"cameraPath": str(camera.GetPath()),
                            "sensor": prim.GetName() if is_sensor(prim) else "",
                            "nativeIndex": prim.GetCustomDataByKey("aecoSync:nativeIndex") or 1}
            prim = camera
        binding = prim.GetAttribute(f"aeco:host:{host}:ref") if prim else None
        # Bonsai starts from the same IFC document and uses its GlobalIds.
        if host == "bonsai" and (not binding or not binding.Get()):
            binding = prim.GetAttribute("aeco:host:ifc:ref") if prim else None
        if not binding or not binding.Get():
            refuse("sync:unbound", f"No {host} binding on {edit.path}")
            continue
        edit.ref = binding.Get()
        if edit.operation == "timeSamples":
            refuse(
                "sync:unsupported",
                "Time samples are not sync driver edits; use default values",
            )
            continue
        if edit.name == "aeco:pipe:nominalDiameter":
            table = list(
                prim.GetAttribute("aeco:pipeType:nominalDiameters").Get() or []
            )
            outer = list(prim.GetAttribute("aeco:pipeType:outerDiameters").Get() or [])
            inner = list(prim.GetAttribute("aeco:pipeType:innerDiameters").Get() or [])
            matches = [
                i for i, n in enumerate(table) if abs(n - float(edit.value)) < 1e-9
            ]
            if not matches or len(table) != len(outer) or len(table) != len(inner):
                refuse(
                    "pipeSizeNotInTable",
                    f"{edit.value} m is not in a valid type size table {table}",
                )
                continue
            i = matches[0]
            edit.section = {
                "nominal": table[i],
                "outer": outer[i],
                "inner": inner[i],
                "label": f"DN{round(table[i]*1000)}",
            }
        accepted.append(edit)
    return accepted, noops


def clear(intent, edits):
    for edit in edits:
        if edit.operation == "create":
            spec = intent.GetPrimAtPath(edit.path)
            if spec:
                # Remove the complete authored definition, including APIs/inherits.
                parent = spec.nameParent
                if parent:
                    del parent.nameChildren[spec.name]
                else:
                    del intent.rootPrims[spec.name]
        elif edit.operation == "primMetadata":
            spec = intent.GetPrimAtPath(edit.path)
            if spec:
                if edit.name == "specifier":
                    spec.specifier = Sdf.SpecifierOver
                else:
                    spec.ClearInfo(edit.name)
        elif edit.operation == "activation":
            spec = intent.GetPrimAtPath(edit.path)
            if spec:
                spec.ClearInfo("active")
        else:
            spec = intent.GetPropertyAtPath(edit.property_path)
            if spec:
                spec.owner.RemoveProperty(spec)
    intent.RemoveInertSceneDescription()
    if not any(p.properties or p.HasInfo("active") for p in all_specs(intent)):
        intent.customLayerData = {}


def withdraw(session, paths=()):
    edits = collect(session.stage, session.intent, session.current())
    chosen = [
        e
        for e in edits
        if not paths
        or str(e.property_path) in paths
        or (e.operation == "activation" and e.path + ".active" in paths)
    ]
    clear(session.intent, chosen)
    session.intent.Save()
    return len(chosen)


def author(session, path, assignments):
    prim = session.stage.GetPrimAtPath(path)
    if not prim:
        raise ValueError(f"No prim at {path}")
    # Validate all controls before authoring any opinions.
    values = []
    for assignment in assignments:
        key, raw = assignment.split("=", 1)
        if key == "length":
            length = float(raw)
            start = Gf.Vec3d(prim.GetAttribute("aeco:axis:start").Get())
            end = Gf.Vec3d(prim.GetAttribute("aeco:axis:end").Get())
            if length <= 0 or (end - start).GetLength() <= 1e-12:
                raise ValueError(
                    "Length must be positive and the existing axis nondegenerate"
                )
            values.append(
                ("aeco:axis:end", start + (end - start).GetNormalized() * length)
            )
        elif key == "diameter":
            values.append(("aeco:pipe:nominalDiameter", float(raw)))
        elif key == "move":
            delta = Gf.Vec3d(*map(float, raw.split(",")))
            m = Gf.Matrix4d(UsdGeom.Xformable(prim).GetLocalTransformation())
            m.SetTranslateOnly(m.ExtractTranslation() + delta)
            values.append(("xformOp:transform", m))
        else:
            raise ValueError(f"Unknown edit control: {key}")
    session.capture_base([Sdf.Path(path).AppendProperty(name) for name, _ in values])
    with Usd.EditContext(session.stage, session.intent):
        for name, val in values:
            if name == "xformOp:transform":
                order = prim.GetAttribute("xformOpOrder").Get()
                if order is not None and list(order) == ["xformOp:transform"]:
                    prim.GetAttribute(name).Set(val)
                else:
                    UsdGeom.Xformable(prim).MakeMatrixXform().Set(val)
            else:
                prim.GetAttribute(name).Set(val)
    session.intent.Save()
