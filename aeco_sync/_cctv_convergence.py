"""Independent per-head optical parity against native family observations."""
import math
from .cctv import SENSOR


def compare_camera(row, other, angle_tolerance=1e-3, radius_tolerance=1e-3):
    report = dict(id=row.get("id"), halfAngleTolerance=angle_tolerance,
                  radiusTolerance=radius_tolerance, model="arc", comparisons=[], missing=[])
    try:
        from usdaeco_cctv.density import optics, range_at_density
    except ModuleNotFoundError as exc:
        if exc.name != "usdaeco_cctv":
            raise
        report.update(converged=False, missing=["optional usdaeco_cctv companion"])
        return report
    catalog = {s["name"]: s.get("drivers", {}) for s in other.get("type", {}).get("sensors", [])}
    sensors = {s["name"]: s for s in other.get("sensors", [])}
    for sensor in row.get("sensors", []):
        name = sensor["name"]
        if name not in sensors:
            report["missing"].append(name)
            continue
        d = {**catalog.get(name, {}), **sensors[name].get("drivers", {})}
        observations = sensor.get("fov", [])
        if not observations:
            report["missing"].append(name + ": native FOV observations")
        for observation in observations:
            p = observation.get("parameters", {})
            label = name + ":" + str(observation.get("subId", ""))
            try:
                # PTZ contains several FOVs. Match each by focal/tilt evidence,
                # never by the unstable native sub-element iteration order.
                presets = list(sensors[name].get("presets", {}).values())
                focal = d.get(SENSOR + "focalLength", 0)
                if presets:
                    matches = [v for v in presets if abs(v.get("focalLength", focal) - p.get("Focal Length", float("inf"))) <= 1e-6
                               and abs(v.get("tilt", d.get(SENSOR + "tilt", 0)) - p.get("Tilt", float("inf"))) <= 1e-6]
                    if not matches:
                        report["missing"].append(label + ": preset correspondence")
                        continue
                    focal = matches[0].get("focalLength", focal)
                o = optics(focal, d[SENSOR + "focalRange"], d[SENSOR + "hfovRange"],
                           d[SENSOR + "vfovRange"], d[SENSOR + "pixels"], d.get(SENSOR + "sensorSize", (0, 0)))
                expected = {"Horizontal Angle": math.radians(o["hfov"]) / 2,
                            "Vertical Angle": math.radians(o["vfov"])/2}
                distance = d.get(SENSOR + "range", 0) or range_at_density(d[SENSOR + "pixels"][0], o["hfov"], d.get(SENSOR + "targetDensity", 0) or 125, "arc")
                # The family uses 26 and 62 rather than the registry's 25 and
                # 62.5. Read the actual thresholds so this tests the same inputs.
                for suffix in ("Det", "Obs", "Rec", "Id", "UD"):
                    threshold = p.get("T_Res_" + suffix)
                    if threshold is None:
                        report["missing"].append(label + ": T_Res_" + suffix)
                        continue
                    if not math.isfinite(threshold) or threshold <= 0:
                        report["missing"].append(label + ": T_Res_" + suffix + " must be finite and positive")
                        continue
                    expected["RG_Length_" + suffix] = min(distance, range_at_density(d[SENSOR + "pixels"][0], o["hfov"], threshold, "arc"))
                for field, val in expected.items():
                    if field not in p or not math.isfinite(p[field]):
                        report["missing"].append(label + ": " + field)
                        continue
                    error = abs(val - p[field])
                    tolerance = angle_tolerance if field.endswith("Angle") else radius_tolerance
                    report["comparisons"].append(dict(sensor=label, field=field, expected=val, native=p[field], error=error, tolerance=tolerance, passed=error <= tolerance))
            except (KeyError, ValueError, TypeError) as exc:
                report["missing"].append(label + ": " + str(exc))
    report["converged"] = bool(report["comparisons"]) and not report["missing"] and all(v["passed"] for v in report["comparisons"])
    report["maxHalfAngleError"] = max((v["error"] for v in report["comparisons"] if v["field"].endswith("Angle")), default=0.)
    report["maxRadiusError"] = max((v["error"] for v in report["comparisons"] if v["field"].startswith("RG_Length")), default=0.)
    return report
