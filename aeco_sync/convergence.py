"""S5 parity: resolved drivers, derived data, topology and body bounds."""

import argparse
import json
from pxr import Sdf
from aeco_sync.stack import all_specs, value

TOL = 1e-4


def values(layer):
    result = {}
    for prim in all_specs(layer):
        for prop in prim.properties:
            if prop.name.startswith("aeco:host:") or prop.name == "aeco:derived:stamp":
                continue
            if isinstance(prop, Sdf.RelationshipSpec):
                result[str(prop.path)] = [
                    str(p) for p in prop.targetPathList.GetAppliedItems()
                ]
            elif prop.HasInfo("default"):
                if prop.name in ("faceVertexIndices", "faceVertexCounts"):
                    continue
                result[str(prop.path)] = (
                    len(prop.default) if prop.name == "points" else value(prop.default)
                )
    return result


def close(a, b, tolerance=TOL):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tolerance
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(close(a[k], b[k], tolerance) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y, tolerance) for x, y in zip(a, b))
    return a == b


def numeric_error(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b)
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return max((numeric_error(x, y) for x, y in zip(a, b)), default=0)
    return 0


def compare(a_path, b_path, tolerance=TOL):
    a, b = [values(Sdf.Layer.FindOrOpen(str(p))) for p in (a_path, b_path)]
    keys = sorted(set(a) | set(b))
    differences = [
        k for k in keys if k not in a or k not in b or not close(a[k], b[k], tolerance)
    ]
    return {
        "compared": len(keys),
        "equal": len(keys) - len(differences),
        "differences": differences,
        "tolerance": tolerance,
        "maxNumericError": max(
            (numeric_error(a[k], b[k]) for k in keys if k in a and k in b), default=0
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ifc_result")
    parser.add_argument("bonsai_result")
    args = parser.parse_args()
    result = compare(args.ifc_result, args.bonsai_result)
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result["differences"]))


import numpy as np
from .identity import guid_to_uuid

def metrics(mesh, matrix):
    """World-space bounds and signed closed-mesh volume; insensitive to triangulation."""
    points = np.asarray(mesh["verts"], dtype=float).reshape((-1, 3))
    faces = np.asarray(mesh["faces"], dtype=int).reshape((-1, 3))
    if (
        not len(points)
        or not len(faces)
        or not np.isfinite(points).all()
        or faces.min() < 0
        or faces.max() >= len(points)
    ):
        raise ValueError("Invalid convergence mesh")
    transform = np.asarray(matrix, dtype=float)
    world = np.c_[points, np.ones(len(points))] @ transform
    world = world[:, :3]
    # Shift the reference near the body to avoid cancellation far from origin.
    a, b, c = np.transpose((world - world.mean(axis=0))[faces], (1, 0, 2))
    volume = abs(float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6))
    return {
        "min": world.min(axis=0).tolist(),
        "max": world.max(axis=0).tolist(),
        "volume": volume,
    }


def world_axis(row):
    drivers = row["drivers"]
    matrix = np.asarray(row["matrix"], dtype=float)
    return np.array(
        [
            np.r_[list(drivers["aeco:axis:" + end]), 1.0] @ matrix
            for end in ("start", "end")
        ]
    )[:, :3]


def compare_receipts(
    native,
    exported,
    *,
    driver_tolerance=1e-4,
    extent_tolerance=1e-4,
    volume_relative_tolerance=0.01,
    volume_absolute_tolerance=1e-6,
):
    """Compare the measurable S4 drivers; missing evidence is a failed comparison."""
    idx = {
        r.get("id") or guid_to_uuid(r["ref"]): r
        for r in exported["touched"]
        if r.get("active") is not False
    }
    report = {
        "elements": 0,
        "driversCompared": 0,
        "maxDriverError": 0.0,
        "driverDifferences": [],
        "missingDrivers": [],
        "missingElements": [],
        "bodies": [],
        "diagnostics": [],
        "cameras": [],
        "driverTolerance": driver_tolerance,
        "extentTolerance": extent_tolerance,
        "volumeRelativeTolerance": volume_relative_tolerance,
        "volumeAbsoluteTolerance": volume_absolute_tolerance,
    }
    native_by_ref = {}
    for r in native["touched"]:
        for key in (r.get("ref"), r.get("id"), r.get("ifcGuid"), r.get("uniqueId")):
            if key:
                native_by_ref[key] = r
    for row in native["touched"]:
        if row.get("active") is False:
            continue
        identity = row.get("id") or guid_to_uuid(row["ifcGuid"])
        other = idx.get(identity)
        if not other:
            report["missingElements"].append(identity)
            continue
        report["elements"] += 1
        if row.get("kind") == "camera":
            from ._cctv_convergence import compare_camera
            comparison = compare_camera(row, other)
            report["cameras"].append(comparison)
            report["driversCompared"] += len(comparison["comparisons"])
            if not comparison["converged"]:
                report["driverDifferences"].append({"id": identity, "driver": "cameraOptics"})
                report["diagnostics"].append({"severity": "info", "code": "cctvDivergence",
                    "message": "Camera half-angles or clipped arc radii differ, or native evidence is missing",
                    "phase": "compare", "blocking": False, "about": [row["path"]], "hostRefs": [row["ref"], other["ref"]]})
        if row.get("kind") in ("pipe", "wall"):
            if not all(
                k in other["drivers"] for k in ("aeco:axis:start", "aeco:axis:end")
            ):
                report["missingDrivers"].append({"id": identity, "driver": "axis"})
            else:
                # The IFC exporter extends or trims a JOINED wall end to the neighbour's
                # face (half its thickness), while the native location curve ends at the
                # corner (docs/11 §11.3 W2/W3 and §11.5). Allow exactly that at joined ends.
                per_end = np.max(np.abs(world_axis(row) - world_axis(other)), axis=-1)
                per_end = np.atleast_1d(per_end).reshape(-1)[:2]
                allowance = [0.0, 0.0]
                if row.get("kind") == "wall":
                    for i, name in enumerate(("aeco:wall:joinAtStart", "aeco:wall:joinAtEnd")):
                        targets = (row.get("joins") or {}).get(name) or []
                        if targets:
                            widths = [
                                (native_by_ref.get(t) or {}).get("derived", {}).get("aeco:wall:thickness")
                                for t in targets
                            ]
                            widths = [w for w in widths if w] or [
                                row.get("derived", {}).get("aeco:wall:thickness") or 0.0
                            ]
                            allowance[i] = 0.5 * max(widths)
                errors = [float(e) for e in per_end]
                error = max(errors)
                report["driversCompared"] += 6
                report["maxDriverError"] = max(error, report["maxDriverError"])
                excess = max(e - a for e, a in zip(errors, allowance + [0.0] * (len(errors) - 2)))
                if excess > driver_tolerance:
                    report["driverDifferences"].append(
                        {"id": identity, "driver": "axis", "error": error, "joinAllowance": allowance}
                    )
                elif error > driver_tolerance:
                    report.setdefault("joinAdjusted", []).append(
                        {"id": identity, "driver": "axis", "error": error, "joinAllowance": allowance}
                    )
            field = (
                "aeco:pipe:nominalDiameter"
                if row["kind"] == "pipe"
                else "aeco:wall:height"
            )
            if field not in row["drivers"] or field not in other["drivers"]:
                report["missingDrivers"].append({"id": identity, "driver": field})
            else:
                error = abs(row["drivers"][field] - other["drivers"][field])
                report["driversCompared"] += 1
                report["maxDriverError"] = max(error, report["maxDriverError"])
                if error > driver_tolerance:
                    report["driverDifferences"].append(
                        {"id": identity, "driver": field, "error": error}
                    )
        mesh_a, mesh_b = native["meshes"].get(row["ref"]), exported["meshes"].get(
            other["ref"]
        )
        if mesh_a and mesh_b:
            a, b = metrics(mesh_a, row["matrix"]), metrics(mesh_b, other["matrix"])
            extent_error = float(
                np.max(
                    np.abs(
                        np.array([a["min"], a["max"]]) - np.array([b["min"], b["max"]])
                    )
                )
            )
            volume_error = abs(a["volume"] - b["volume"])
            relative_error = volume_error / max(
                a["volume"], b["volume"], volume_absolute_tolerance
            )
            divergent = extent_error > extent_tolerance or volume_error > max(
                volume_absolute_tolerance,
                volume_relative_tolerance * max(a["volume"], b["volume"]),
            )
            report["bodies"].append(
                {
                    "id": identity,
                    "native": a,
                    "ifc": b,
                    "extentError": extent_error,
                    "volumeError": volume_error,
                    "volumeRelativeError": relative_error,
                    "divergent": divergent,
                }
            )
        else:
            divergent = True
            report["bodies"].append(
                {"id": identity, "missingMesh": True, "divergent": True}
            )
        if divergent:
            report["diagnostics"].append(
                {
                    "severity": "info",
                    "code": "bodyDivergence",
                    "message": "Native and exported body bounds/volume differ beyond the recorded tolerances",
                    "phase": "compare",
                    "blocking": False,
                    "about": [row["path"]],
                    "hostRefs": [row["ref"], other["ref"]],
                }
            )
    report["driversConverged"] = report["driversCompared"] > 0 and not any(
        report[k] for k in ("driverDifferences", "missingDrivers", "missingElements")
    )
    report["cctvConverged"] = bool(report["cameras"]) and all(c["converged"] for c in report["cameras"])
    report["maxExtentError"] = max(
        (b.get("extentError", 0.0) for b in report["bodies"]), default=0.0
    )
    report["maxVolumeRelativeError"] = max(
        (b.get("volumeRelativeError", 0.0) for b in report["bodies"]), default=0.0
    )
    return report


