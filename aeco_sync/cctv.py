"""Camera wire mapping and preflight; usable without the optional CCTV companion.

Wire angles and optical lengths are degrees and millimetres. Placement,
range, offsets and native resolution-guide radii are metres; native half
angles alone remain radians. Raw family parameters are retained as evidence.
"""
import math
import re
from pxr import Gf, Sdf, UsdGeom

SENSOR = "aeco:cctvSensor:"
PRESET = "aeco:cctvPreset:"
CONTROLS = {"pan", "tilt", "roll", "focalLength", "range", "targetDensity"}
NATIVE = set(UsdGeom.Camera.GetSchemaAttributeNames(False))


def is_sensor(prim):
    return bool(prim and "AecoCctvSensorAPI" in prim.GetAppliedSchemas())


def camera_of(prim):
    if not prim:
        return None
    if prim.HasAPI("AecoCctvCameraAPI"):
        return prim
    parent = prim.GetParent()
    return parent if is_sensor(prim) and parent.HasAPI("AecoCctvCameraAPI") else None


def envelope(prim):
    """Validate composed poses and presets before any adapter call (zero zoom = wide)."""
    sensors = [prim] if is_sensor(prim) else [p for p in prim.GetAllChildren() if is_sensor(p)]
    if not sensors:
        return "Camera needs at least one sensor inherited from its catalog type"
    for sensor in sensors:
        prefixes = [SENSOR] + [PRESET + a.split(":", 1)[1] + ":"
                              for a in sensor.GetAppliedSchemas() if a.startswith("AecoCctvPresetAPI:")]
        for prefix in prefixes:
            for field, bounds in (("pan", "panRange"), ("tilt", "tiltRange"), ("focalLength", "focalRange")):
                attr = sensor.GetAttribute(prefix + field)
                val = attr.Get() if attr else None
                pair = sensor.GetAttribute(SENSOR + bounds).Get()
                if val is None or pair is None or not math.isfinite(val) or not all(math.isfinite(x) for x in pair):
                    return f"Missing or nonfinite {field} or {bounds} at {sensor.GetPath()}"
                lo, hi = pair
                if lo > hi or (field == "focalLength" and lo <= 0):
                    return f"Invalid {bounds} at {sensor.GetPath()}"
                if field == "focalLength" and val == 0:
                    continue
                if field != "focalLength" and (lo, hi) == (0, 0):
                    continue  # unspecified mechanical envelope
                if not lo - 1e-6 <= val <= hi + 1e-6:
                    return f"{prefix + field}={val} outside [{lo}, {hi}] at {sensor.GetPath()}"
        for field in ("range", "targetDensity"):
            val = sensor.GetAttribute(SENSOR + field).Get()
            if val is None or not math.isfinite(val) or val < 0:
                return f"{field} must be finite and nonnegative"
    return None


def rigid_z(matrix, mirrored=False):
    import numpy as np
    m = np.asarray(matrix, dtype=float)
    return (m.shape == (4, 4) and np.isfinite(m).all()
            and np.allclose(m[:, 3], [0, 0, 0, 1], atol=1e-9)
            and np.allclose(m[2, :3], [0, 0, 1], atol=1e-9)
            and np.allclose(m[:3, :3] @ m[:3, :3].T, np.eye(3), atol=1e-9)
            and abs(np.linalg.det(m[:3, :3]) - (-1 if mirrored else 1)) < 1e-9)


def controls(parameters, number=None):
    p = parameters
    prefix = f"FOV {number} " if number else "FOV "
    result = {}
    for field, names in {
        "pan": [prefix + "Pan", "FOV Pan", "FOV Camera Rotation"],
        "tilt": [prefix + "Tilt", "FOV Tilt", "FOV Camera Tilt"],
        "focalLength": [prefix + "Actual Focal Length", prefix + "Desired Focal Length", "FOV Actual Focal Length", "FOV Desired Focal Length"],
        "range": [prefix + "Distance to Object", "FOV Distance to Object"],
        "targetDensity": [prefix + "Target Pixel Density", "FOV Target Pixel Density"],
    }.items():
        if number is None:
            # The primary PTZ sensor uses base controls when present, otherwise
            # head 1. This is the same preference as CameraParameter in Revit.
            names += [n.replace("FOV ", "FOV 1 ", 1) for n in names]
        found = next((p[n] for n in names if n in p and p[n] is not None), None)
        if found is not None:
            result[SENSOR + field] = float(found)
    if "Corridor Format" in p:
        result[SENSOR + "roll"] = 90.0 if p["Corridor Format"] else 0.0
    return result


def optics_parameters(p):
    p = dict(p)
    for suffix in ("Min", "Max"):
        if "Tilt " + suffix in p:
            p.setdefault("FOV Tilt " + suffix, p["Tilt " + suffix])
    result = {}
    for field, names in {
        "focalRange": ("FOV Focal Length Minimum", "FOV Focal Length Maximum"),
        "hfovRange": ("FOV Horizontal Maximum", "FOV Horizontal Minimum"),
        "vfovRange": ("FOV Vertical Maximum", "FOV Vertical Minimum"),
        "pixels": ("FOV Horizontal Resolution", "FOV Vertical Resolution"),
        "tiltRange": ("FOV Tilt Min", "FOV Tilt Max"),
    }.items():
        if all(n in p for n in names):
            result[SENSOR + field] = [p[n] for n in names]
    if "Origin Horizontal" in p or "Origin Vertical" in p:
        result[SENSOR + "offset"] = [p.get("Origin Horizontal", 0), 0, p.get("Origin Vertical", 0)]
    return result


def normalize_revit_camera(item):
    """Promote the script's normalized family evidence to type sensors and overrides."""
    p, tp = item.get("cameraParameters", {}), item.get("typeParameters", {})
    presets = sorted(int(m[1]) for n in p if (m := re.fullmatch(r"Preset (\d+)", n)))
    heads = sorted({int(m[1]) for n in p if (m := re.match(r"FOV (\d+) ", n))})
    count = 1 if presets else max(heads, default=1)
    td = optics_parameters(tp)
    td[SENSOR + "motorised"] = bool(presets)
    if presets:
        td.setdefault(SENSOR + "panRange", [-180., 180.])
    subs = item.get("subInstances", [])
    fovs = [r for r in subs if r["role"] == "fov"]
    symbols = [r for r in subs if r["role"] == "symbol"]
    sensors, type_sensors = [], []
    for index in range(count):
        name = f"Sensor_{index}"
        drivers = controls(p, index + 1 if heads and not presets else None)
        preset_data = {}
        for n in presets:
            values = controls(p, n)
            preset_data[f"Preset_{n}"] = {f: values[SENSOR + f] for f in ("pan", "tilt", "focalLength") if SENSOR + f in values}
        refs = [item["ref"] + ":" + r["role"] + ":" + str(r["subId"])
                for r in (fovs if presets else fovs[index:index + 1]) + symbols]
        sensor = dict(name=name, path=item["path"] + "/" + name, drivers=drivers,
                      presets=preset_data, ref=refs[0] if refs else item["ref"], refs=refs,
                      nativeIndex=index + 1, fov=fovs if presets else fovs[index:index + 1])
        sensors.append(sensor)
        type_sensors.append(dict(name=name, drivers=dict(td)))
    item["sensors"] = sensors
    item["type"]["sensors"] = type_sensors
    item["type"]["parameters"] = tp
    item["drivers"].update({"aeco:cctv:scenario": str(p.get("Scenario", "")),
        "aeco:cctv:mount": {17160: "wall", 17161: "ceiling", 17162: "pole", 17165: "corner"}.get(int(tp.get("Placement ID", 0)), "undefined")})
    return item


def set_values(prim, values):
    for name, val in values.items():
        attr = prim.GetAttribute(name)
        if not attr:
            raise ValueError(f"Camera receipt needs a registered property: {name}")
        typ = attr.GetTypeName()
        convert = {Sdf.ValueTypeNames.Double2: Gf.Vec2d, Sdf.ValueTypeNames.Double3: Gf.Vec3d,
                   Sdf.ValueTypeNames.Int2: Gf.Vec2i}.get(typ)
        attr.Set(convert(*val) if convert else val)
