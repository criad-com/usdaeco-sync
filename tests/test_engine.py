"""Transaction outcomes across drivers, gap policies and host failure phases."""
from pathlib import Path
import importlib.metadata
import json
import os
import subprocess
import sys
import pytest
from pxr import Gf, Sdf, Usd
from aeco_sync import engine
from aeco_sync.edits import author
from aeco_sync.hosts.base import discover, host_class, open_host
from aeco_sync.identity import uuid_to_guid
from aeco_sync.readback import bind
from aeco_sync.stack import PREFIX, POLICIES
from tests.fake_host import FakeHost


@pytest.fixture
def native(session):
    with Usd.EditContext(session.stage, session.layer("kind.usda")):
        prim = session.stage.GetPrimAtPath("/Pipe")
        prim.GetAttribute("aeco:pipe:nominalDiameter").Set(.05)
        bind(prim, "ifc", uuid_to_guid(prim.GetAttribute("aeco:id").Get()),
             "1", session.version("ifc"), session.document("ifc"))
        wall = session.stage.DefinePrim("/Wall", "Xform")
        for api in ("AecoElementAPI", "AecoAxisAPI", "AecoWallAPI"):
            wall.ApplyAPI(api)
        wall.GetAttribute("aeco:id").Set("b6401a5e-139e-4216-91d1-e7dc0d6c107e")
        wall.GetAttribute("aeco:axis:end").Set(Gf.Vec3d(4, 0, 0))
        wall.GetAttribute("aeco:wall:height").Set(3)
        bind(wall, "ifc", uuid_to_guid(wall.GetAttribute("aeco:id").Get()),
             "2", session.version("ifc"), session.document("ifc"))
    session.layer("kind.usda").Save()
    return FakeHost(session)


def edit(session, driver):
    if driver == "length":
        author(session, "/Pipe", ["length=3"])
    elif driver == "diameter":
        author(session, "/Pipe", ["diameter=.065"])
    else:
        path = "/Wall" if driver == "height" else "/Pipe"
        prop = "aeco:wall:height" if driver == "height" else "xformOp:transform" if driver == "placement" else "active"
        session.capture_base([] if prop == "active" else [Sdf.Path(path).AppendProperty(prop)])
        with Usd.EditContext(session.stage, session.intent):
            prim = session.stage.GetPrimAtPath(path)
            if driver == "delete":
                prim.SetActive(False)
            else:
                prim.GetAttribute(prop).Set(4 if driver == "height" else Gf.Matrix4d(1).SetTranslate(Gf.Vec3d(1, 0, 0)))
        session.intent.Save()


@pytest.mark.parametrize("file_backed", [False, True])
@pytest.mark.parametrize("policy", POLICIES)
@pytest.mark.parametrize("driver", ["length", "diameter", "height", "placement", "delete"])
@pytest.mark.parametrize("outcome", ["accept", "unsupported", "stale", "nativeFailure", "publishFailure", "unbound", "diagnostic"])
def test_transaction_matrix(session, native, monkeypatch, policy, driver, outcome, file_backed):
    native.file_backed = file_backed
    native.file_suffix = ".json" if file_backed else ""
    session.root.customLayerData = {**session.root.customLayerData, PREFIX + "gapPolicy": policy}
    edit(session, driver)
    before = {name: session.layer(name).ExportToString() for name in ("result.ifc.usda", "derived.usda")}
    intent = session.intent.ExportToString()
    if outcome == "unsupported": native.refuse = True
    if outcome == "stale": native.token = "external-change"
    if outcome == "nativeFailure": native.fail = True
    if outcome == "publishFailure":
        def fail(*args): raise RuntimeError("Seeded USD publication failure")
        monkeypatch.setattr(engine, "publish", fail)
    if outcome == "unbound":
        with Usd.EditContext(session.stage, session.layer("kind.usda")):
            session.stage.GetPrimAtPath("/Wall" if driver == "height" else "/Pipe").GetAttribute("aeco:host:ifc:ref").Set("")
    if outcome == "diagnostic":
        native.rows = [dict(severity="warning", code="fake:advisory", message="Retained native warning", about=["/Pipe"], blocking=False, phase="validate", hostRefs=[])]
    result = engine.apply(session, native=native)
    successful = outcome in ("accept", "diagnostic")
    assert result["accepted"] == (1 if successful else 0), result["diagnostics"]
    assert result["inSync"] == successful
    assert len(native.calls) == (0 if outcome in ("unsupported", "stale", "unbound") else 1)
    if successful:
        assert not session.status()["pending"]
        assert engine.apply(session, native=FakeHost(session))["mutations"] == 0
        if outcome == "diagnostic": assert any(d["code"] == "fake:advisory" for d in result["diagnostics"])
    else:
        assert session.intent.ExportToString() == intent
        assert {name: session.layer(name).ExportToString() for name in before} == before
        assert result["diagnostics"]


def test_discovery_uses_distribution_entry_point(monkeypatch):
    point = importlib.metadata.EntryPoint(name="ifc", value="tests.fake_host:FakeHost", group="aeco_sync.hosts")
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda **kwargs: [point])
    assert discover()["ifc"] == point
    assert host_class("ifc") is FakeHost
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda **kwargs: [point, point])
    with pytest.raises(ValueError, match="Multiple"): discover()


@pytest.mark.parametrize("module", ["tests.fake_host", "tests.fake_host:", ":FakeHost", "builtins:object"])
def test_invalid_override(module):
    with pytest.raises((ValueError, TypeError)):
        host_class("ifc", module)


def test_explicit_override_and_close(session, native, monkeypatch):
    assert host_class("ifc", "tests.fake_host:FakeHost") is FakeHost
    monkeypatch.setattr(engine, "adapter", lambda *args, **kwargs: native)
    edit(session, "length")
    assert engine.apply(session)["accepted"] == 1
    assert native.closed


def test_readback_conflict_retains_intent(session, native):
    edit(session, "length")
    row = next(r for r in native.records.values() if r["path"] == "/Pipe")
    row["drivers"]["aeco:axis:end"] = Gf.Vec3d(0, 0, 4)
    native.token = "external"
    result = engine.readback(session, "ifc", native=native)
    assert any(d["code"] == "sync:conflict" for d in result["diagnostics"])
    current = session.current()
    assert current.GetAttributeAtPath("/Pipe.aeco:axis:end").Get()[2] == 4
    assert session.stage.GetAttributeAtPath("/Pipe.aeco:axis:end").Get()[2] == 3


@pytest.mark.parametrize("operation", ["apply", "readback"])
def test_library_entrypoints_without_native_imports(session, native, operation):
    code = '''import importlib.abc,sys
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in ('ifcopenshell', 'bpy'):
            raise AssertionError('Native import reached sync')
sys.meta_path.insert(0, NoNative())
from aeco_sync.stack import Session
from aeco_sync import engine
from tests.fake_host import FakeHost
from pxr import Usd
s = Session(sys.argv[1])
getattr(engine, sys.argv[2])(s, 'ifc', native=FakeHost(s))
assert not Usd.SchemaRegistry.GetTypeFromSchemaTypeName('AecoSyncDiagnostic').isUnknown
'''
    env = {k:v for k,v in os.environ.items() if k not in ("PYTHONPATH", "PXR_PLUGINPATH_NAME")}
    result = subprocess.run([sys.executable, "-c", code, str(session.path), operation], cwd=Path(__file__).parents[1], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
