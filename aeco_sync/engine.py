"""Seven-step transaction orchestration; adapters never own the intent layer."""

import os
from pathlib import Path
import tempfile
from pxr import Gf, UsdGeom
from .diagnostics import Diagnostics
from .edits import collect, preflight, clear, equal
from .closure import plan
from .readback import publish
from .stack import PREFIX, lock
from .hosts.base import Operations


def adapter(session, host, document=None, *, validate_all=False, ids=None, host_module=None):
    from .hosts.base import open_host
    return open_host(session, host, document, host_module=host_module,
                     validate_all=validate_all, ids=ids)


def apply(session, host="ifc", *, validate_all=False, ids=None, native=None, host_module=None):
    """Apply intent through an installed integration; always load family plugins."""
    with lock(session):
        from . import register_plugins
        register_plugins()
        from .stack import find_layer
        previous = find_layer(session.stage, f"result.{host}.usda")
        if (previous is None or not previous.customLayerData) and any(
            Path(layer.realPath).name.startswith("result.") and layer.customLayerData
            for layer in session.stage.GetLayerStack()
        ):
            raise ValueError(f"Read back the {host} document before first switching this session to that host")
        owned = native is None
        native = native or adapter(session, host, validate_all=validate_all, ids=ids, host_module=host_module)
        try:
            return _apply(session, host, native=native)
        finally:
            if owned:
                native.close()


def _apply(session, host="ifc", *, validate_all=False, ids=None, native=None):
    """Apply intent, optionally reusing a caller-configured adapter for this session."""
    from . import register_plugins
    register_plugins()
    from .stack import find_layer

    previous = find_layer(session.stage, f"result.{host}.usda")
    if (previous is None or not previous.customLayerData) and any(
        Path(layer.realPath).name.startswith("result.") and layer.customLayerData
        for layer in session.stage.GetLayerStack()
    ):
        raise ValueError(
            f"Read back the {host} document before first switching this session to that host"
        )
    result, dlayer = session.ensure_host(host)
    native = native or adapter(session, host, validate_all=validate_all, ids=ids)
    diag = Diagnostics()
    edits = collect(session.stage, session.intent, session.current())
    accepted, noops = preflight(session, edits, host, native.version(), diag)
    # A refused relationship cannot authorize a constrained endpoint edit.
    # Keep host-independent endpoint refusals ahead of other capability checks.
    relations = []
    for edit in accepted:
        if edit.operation == "relationship" and not native.supports(edit):
            diag.add(
                "warning",
                "sync:unsupported",
                f"{host}: {native.unsupported_reason(edit)} at {edit.property_path}; intent retained",
                [edit.property_path],
                blocking=True,
            )
        else:
            relations.append(edit)
    accepted, closure = plan(session, relations, diag)
    supported = []
    for edit in accepted:
        if native.supports(edit):
            supported.append(edit)
        else:
            diag.add(
                "warning",
                "sync:unsupported",
                f"{host}: {native.unsupported_reason(edit)} at {edit.property_path}; intent retained",
                [edit.property_path],
                blocking=True,
            )
    accepted = supported
    if accepted:
        native.validation_refs = {e.ref for e in accepted if e.ref}
    touched = []
    snapshots = {
        layer: layer.ExportToString()
        for layer in (result, dlayer, session.layer("derived.usda"), session.intent)
    }
    output = session.path.parent / f"host.{host}{native.file_suffix}"
    candidate = None
    version, document = native.version(), str(native.document)
    try:
        if accepted:
            mutation = native.apply(Operations(accepted, closure))
            touched = list(mutation.touched)
            if getattr(native, "file_backed", True):
                fd, filename = tempfile.mkstemp(
                    prefix=".sync-", suffix=native.file_suffix, dir=session.path.parent
                )
                os.close(fd)
                candidate = Path(filename)
                native.save(candidate)
            version = native.version()
            receipt = native.readback(touched)
            diag.items.extend(native.diagnostics())
            diag.items.extend(native.validate())
            if any(d["code"] == "sync:gap" for d in diag.items):
                raise ValueError("Host returned a connected port gap")
            # Do not let accepted intent shadow the normalized native result.
            clear(session.intent, accepted + noops)
            document = str(output) if candidate else str(native.document)
            publish(session, receipt, result, host, version, document)
        else:
            clear(session.intent, noops)
            diag.items.extend(native.validate())
        # Refused edits retain their original base token. Accepted changes by
        # this transaction advance that token; unrelated external changes do not.
        if accepted and session.intent.customLayerData:
            data = dict(session.intent.customLayerData)
            versions = dict(data.get(PREFIX + "baseVersions", {}))
            versions[host] = version
            data[PREFIX + "baseVersions"] = versions
            session.intent.customLayerData = data
        diag.write(session, dlayer, host, version, document)
        for layer in snapshots:
            layer.Save()
        if candidate:
            os.replace(candidate, output)
            candidate = None
        if accepted and hasattr(native, "acknowledge"):
            native.acknowledge()
    except Exception as exc:
        for layer, text in snapshots.items():
            layer.ImportFromString(text)
        if candidate and candidate.exists():
            candidate.unlink()
        for item in native.diagnostics():
            if item not in diag.items:
                diag.items.append(item)
        diag.add(
            "error",
            f"{host}:exception:{type(exc).__name__}",
            str(exc),
            [e.property_path for e in accepted],
            blocking=True,
        )
        if (
            getattr(native, "journal", None)
            and native.journal.exists()
        ):
            diag.add(
                "error",
                f"{host}:receiptPending",
                "The native transaction committed but its USD receipt was not published; read back the host to reconcile the saved receipt before applying again",
                [e.property_path for e in accepted],
                blocking=True,
                phase="publish",
            )
        accepted, noops, touched = [], [], []
        version, document = session.version(host), session.document(host)
        diag.write(session, dlayer, host, version, document)
        for layer in snapshots:
            layer.Save()
    status = session.status()
    return {
        "nativeEvidence": getattr(native, "native_evidence", {}),
        "mutations": len(getattr(native, "camera_operations", [])) if accepted and getattr(native, "camera_operations", []) else len(accepted),
        "publishedTypes": [op["path"] for op in getattr(native, "camera_operations", []) if accepted and op["operation"] == "publishType"],
        "edits": len(edits),
        "accepted": len(accepted) + len(noops),
        "refused": len(edits) - len(accepted) - len(noops),
        "touched": touched,
        "diagnostics": diag.items,
        "pending": status["pending"],
        "inSync": status["inSync"],
    }


def readback(session, host, document=None, *, validate_all=False, ids=None, native=None, host_module=None):
    with lock(session):
        from . import register_plugins
        register_plugins()
        owned = native is None
        native = native or adapter(session, host, document, validate_all=validate_all, ids=ids, host_module=host_module)
        try:
            return _readback(session, host, native)
        finally:
            if owned:
                native.close()


def _readback(session, host, native):
    from . import register_plugins
    register_plugins()
    result, dlayer = session.ensure_host(host)
    edits = collect(session.stage, session.intent, session.current())
    receipt = native.readback(None)
    touched = [item["ref"] for item in receipt["touched"] if item.get("active", True)]
    # A native deletion must mask the weaker imported element as well.
    for prim in native.current.Traverse():
        binding = prim.GetAttribute(
            f"aeco:host:{host}:ref"
        )
        if (
            prim.HasAPI("AecoElementAPI")
            and binding
            and binding.Get()
            and binding.Get() not in touched
        ):
            receipt["touched"].append(
                {"path": str(prim.GetPath()), "ref": binding.Get(), "active": False}
            )
    diag = Diagnostics()
    resolved = {}
    for item in receipt["touched"]:
        fields = {
            **item.get("drivers", {}),
            **item.get("derived", {}),
            **item.get("joins", {}),
        }
        if "matrix" in item:
            prim = native.current.GetPrimAtPath(item["path"])
            parent = (
                UsdGeom.XformCache().GetLocalToWorldTransform(prim.GetParent())
                if prim
                else Gf.Matrix4d(1)
            )
            fields["xformOp:transform"] = (
                Gf.Matrix4d(item["matrix"]) * parent.GetInverse()
            )
        if "active" in item:
            fields["active"] = item["active"]
        resolved.update({(item["path"], name): val for name, val in fields.items()})
        for sensor in item.get("sensors", []):
            path = item["path"] + "/" + sensor["name"]
            resolved.update({(path, name): val for name, val in sensor.get("drivers", {}).items()})
            for preset, pose in sensor.get("presets", {}).items():
                resolved.update({(path, "aeco:cctvPreset:" + preset + ":" + field): val for field, val in pose.items()})
        for port in item.get("ports", []):
            resolved[(port["path"], "aeco:connectedPorts")] = port["connected"]
            resolved[(port["path"], "xformOp:transform")] = port["matrix"]
    for edit in edits:
        key = (edit.path, edit.name)
        if key in resolved and not equal(edit.current, resolved[key]):
            diag.add(
                "error",
                "sync:conflict",
                f"Host changed {edit.property_path}; native result wins in current view; redo or withdraw the pending opinion",
                [edit.property_path],
                blocking=True,
            )
    diag.items.extend(native.diagnostics())
    diag.items.extend(native.validate())
    snapshots = {
        layer: layer.ExportToString()
        for layer in (result, dlayer, session.layer("derived.usda"))
    }
    try:
        publish(
            session, receipt, result, host, native.version(), str(native.document)
        )
        diag.write(session, dlayer, host, native.version(), str(native.document))
        for layer in snapshots:
            layer.Save()
        if hasattr(native, "acknowledge"):
            native.acknowledge()
    except Exception:
        for layer, text in snapshots.items():
            layer.ImportFromString(text)
            layer.Save()
        raise
    return {
        "touched": touched,
        "diagnostics": diag.items,
        "pending": session.status()["pending"],
    }
