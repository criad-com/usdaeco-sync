"""Session layers, version facts and the intent-muted current view."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from pxr import Sdf, Usd, Vt

PREFIX = "aeco:sync:"
POLICIES = ("keepConnected", "disconnect", "refuse")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def facts(host, document, version, policy="keepConnected", authoritative=None):
    return {
        PREFIX + "host": host,
        PREFIX + "document": str(document),
        PREFIX + "version": version,
        PREFIX + "time": datetime.now(timezone.utc).isoformat(),
        PREFIX + "gapPolicy": policy,
        PREFIX + "authoritativeHost": authoritative or host,
        PREFIX + "protocol": "1",
    }


def find_layer(stage, basename):
    return next(
        (l for l in stage.GetLayerStack() if Path(l.realPath).name == basename), None
    )


def all_specs(layer):
    def walk(spec):
        yield spec
        for child in spec.nameChildren:
            yield from walk(child)

    for spec in layer.rootPrims:
        yield from walk(spec)


def create(model, document, directory=None, policy="keepConnected", *, host="ifc", version=None):
    from . import register_plugins
    register_plugins()
    model, document = Path(model).resolve(), Path(document).resolve()
    directory = Path(directory or model.parent).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "stage.usda"
    if path.exists():
        raise FileExistsError(f"Session already exists: {path}")
    if policy not in POLICIES:
        raise ValueError(f"Unknown gap policy: {policy}")
    if not model.is_file() or not document.is_file():
        raise FileNotFoundError("Model and document input must exist")
    names = [
        "intent.usda",
        f"diagnostics.{host}.usda",
        f"result.{host}.usda",
        "derived.usda",
        "kind.usda",
    ]
    if any((directory / n).exists() for n in names):
        raise FileExistsError(
            "Session layer names already exist in the target directory"
        )
    root = Sdf.Layer.CreateNew(str(path))
    for name in names:
        Sdf.Layer.CreateNew(str(directory / name)).Save()
    root.subLayerPaths = names + [os.path.relpath(model, directory)]
    source = Usd.Stage.Open(str(model))
    for key in ("defaultPrim", "metersPerUnit", "upAxis", "fallbackPrimTypes"):
        if source.HasAuthoredMetadata(key):
            root.pseudoRoot.SetInfo(key, source.GetMetadata(key))
    fallback = dict(source.GetMetadata("fallbackPrimTypes") or {})
    fallback["AecoSyncDiagnostic"] = Vt.TokenArray(["Scope"])
    root.pseudoRoot.SetInfo("fallbackPrimTypes", fallback)
    root.customLayerData = facts(host, document, version or digest(document), policy)
    root.Save()
    return Session(path)


class Session:
    def __init__(self, path="stage.usda"):
        from . import register_plugins
        register_plugins()
        self.path = Path(path).resolve()
        self.stage = Usd.Stage.Open(str(self.path))
        if not self.stage:
            raise ValueError(f"Cannot open {path}")
        self.root = self.stage.GetRootLayer()
        self.intent = find_layer(self.stage, "intent.usda")
        if self.intent is None:
            raise ValueError("A sync session must contain intent.usda")

    @property
    def policy(self):
        return self.root.customLayerData.get(PREFIX + "gapPolicy", "keepConnected")

    def current(self):
        current = Usd.Stage.Open(self.root)
        current.MuteLayer(self.intent.identifier)
        return current

    def layer(self, name):
        layer = find_layer(self.stage, name)
        if layer is None:
            raise ValueError(f"Missing session layer: {name}")
        return layer

    def ensure_host(self, host):
        if not host.isidentifier():
            raise ValueError("Host instance must be an identifier")
        names = [f"diagnostics.{host}.usda", f"result.{host}.usda"]
        for name in names:
            if not (self.path.parent / name).exists():
                Sdf.Layer.CreateNew(str(self.path.parent / name)).Save()
        old = list(self.root.subLayerPaths)
        self.root.subLayerPaths = (
            ["intent.usda"]
            + names
            + [n for n in old if n not in names + ["intent.usda"]]
        )
        self.root.customLayerData = {
            **self.root.customLayerData,
            PREFIX + "authoritativeHost": host,
        }
        self.root.Save()
        return self.layer(names[1]), self.layer(names[0])

    def document(self, host):
        result = find_layer(self.stage, f"result.{host}.usda")
        data = result.customLayerData if result else {}
        return (
            data.get(PREFIX + "document")
            or self.root.customLayerData[PREFIX + "document"]
        )

    def version(self, host):
        result = find_layer(self.stage, f"result.{host}.usda")
        return (
            result.customLayerData.get(PREFIX + "version") if result else None
        ) or self.root.customLayerData[PREFIX + "version"]

    def capture_base(self, properties=None):
        data = dict(self.intent.customLayerData)
        if PREFIX + "baseVersions" not in data:
            hosts = {self.root.customLayerData[PREFIX + "authoritativeHost"]}
            hosts.update(Path(layer.realPath).name[7:-5] for layer in self.stage.GetLayerStack()
                         if Path(layer.realPath).name.startswith("result."))
            versions = {host: self.version(host) for host in hosts}
            data[PREFIX + "baseVersions"] = versions
        current = self.current()
        original = json.loads(data.get(PREFIX + "baseValues", "{}"))
        if properties is None:
            properties = (p.GetPath() for prim in current.TraverseAll()
                          for p in prim.GetAttributes() if p.HasAuthoredValueOpinion())
        for path in properties:
            key = str(path)
            if key not in original:
                prop = current.GetPropertyAtPath(path)
                original[key] = value(prop.GetTargets() if isinstance(prop, Usd.Relationship) else prop.Get() if prop else None)
        data[PREFIX + "baseValues"] = json.dumps(original, sort_keys=True)
        self.intent.customLayerData = data

    def status(self):
        from .edits import collect

        pending = collect(self.stage, self.intent, self.current())
        hosts = {
            Path(l.realPath).name[7:-5]: dict(l.customLayerData)
            for l in self.stage.GetLayerStack()
            if Path(l.realPath).name.startswith("result.")
        }
        return {
            "pending": len(pending),
            "inSync": not pending,
            "policy": self.policy,
            "edits": [e.wire() for e in pending],
            "hosts": hosts,
        }


@contextmanager
def lock(session):
    path = session.path.parent / ".sync.lock"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        path.unlink()


def value(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): value(v) for k, v in obj.items()}
    if isinstance(obj, Sdf.ValueBlock):
        return {"blocked": True}
    try:
        return [value(v) for v in obj]
    except TypeError:
        return str(obj)
