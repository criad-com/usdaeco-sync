import json
from pathlib import Path
import numpy as np
import pytest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdValidation
from aeco_sync import identity
from aeco_sync.edits import collect, author, preflight, withdraw, clear
from aeco_sync.diagnostics import Diagnostics
from aeco_sync.derive import derive_gprims, arc_points
from aeco_sync.closure import walk, segment_near_end, plan
from aeco_sync.stack import PREFIX, digest
from aeco_sync.readback import bind
from aeco_sync.validators import validate_stage


def edits(session):
    return collect(session.stage, session.intent, session.current())


def bound(session):
    with Usd.EditContext(session.stage, session.layer("kind.usda")):
        bind(
            session.stage.GetPrimAtPath("/Pipe"),
            "ifc",
            identity.uuid_to_guid("946ea480-cd43-4abc-9018-85e327fdab24"),
            "#1",
            session.version("ifc"),
            session.document("ifc"),
        )


def test_intent_muted_and_length_control(session):
    author(session, "/Pipe", ["length=3"])
    assert list(session.stage.GetAttributeAtPath("/Pipe.aeco:axis:end").Get()) == [
        0,
        0,
        3,
    ]
    current = session.current()
    assert list(current.GetAttributeAtPath("/Pipe.aeco:axis:end").Get()) == [0, 0, 2]
    assert list(session.stage.GetAttributeAtPath("/Pipe.aeco:axis:start").Get()) == [
        0,
        0,
        0,
    ]
    assert edits(session)[0].kind == "axis"
    assert PREFIX + "baseVersions" in session.intent.customLayerData


def test_relationship_list_operations_and_activation(session):
    with Usd.EditContext(session.stage, session.layer("kind.usda")):
        p = session.stage.GetPrimAtPath("/Pipe")
        p.CreateRelationship("aeco:connectedPorts").SetTargets(["/A", "/B"])
    with Usd.EditContext(session.stage, session.intent):
        p.GetRelationship("aeco:connectedPorts").RemoveTarget("/A")
        p.SetActive(False)
    actual = edits(session)
    assert {e.operation for e in actual} == {"relationship", "activation"}
    relation = next(e for e in actual if e.operation == "relationship")
    # Inactive prim has no composed relationship: collect the list operation against current.
    assert [str(t) for t in relation.value] == ["/B"]
    assert relation.kind == "relation"
    clear(session.intent, actual)
    assert session.status()["inSync"]


def test_noop_eliminated_but_derived_noop_refused(session):
    bound(session)
    session.capture_base()
    with Usd.EditContext(session.stage, session.intent):
        session.stage.GetAttributeAtPath("/Pipe.aeco:axis:end").Set(Gf.Vec3d(0, 0, 2))
        session.stage.GetAttributeAtPath("/Pipe.aeco:pipe:outerDiameter").Set(0.05)
    diag = Diagnostics()
    accepted, noops = preflight(
        session, edits(session), "ifc", session.version("ifc"), diag
    )
    assert not accepted and len(noops) == 1
    assert [d["code"] for d in diag.items] == ["sync:derivedAuthored"]
    clear(session.intent, noops)
    assert withdraw(session, ["/Pipe.aeco:pipe:outerDiameter"]) == 1
    assert session.status()["inSync"]


def test_unbound_and_stale_refused_before_host(session):
    author(session, "/Pipe", ["length=3"])
    diag = Diagnostics()
    assert (
        preflight(session, edits(session), "ifc", session.version("ifc"), diag)[0] == []
    )
    assert diag.items[0]["code"] == "sync:unbound"
    bound(session)
    diag = Diagnostics()
    assert preflight(session, edits(session), "ifc", "changed", diag)[0] == []
    assert diag.items[0]["code"] == "sync:staleIntent"


def test_size_table_key_differs_from_outer(session):
    bound(session)
    author(session, "/Pipe", ["diameter=.065"])
    accepted, _ = preflight(
        session, edits(session), "ifc", session.version("ifc"), Diagnostics()
    )
    assert accepted[0].section == {
        "nominal": 0.065,
        "outer": 0.0761,
        "inner": 0.0697,
        "label": "DN65",
    }


def test_derive_ignores_poisoned_derived_opinion_and_orients_axis(session):
    with Usd.EditContext(session.stage, session.intent):
        session.stage.GetAttributeAtPath("/Pipe.aeco:axis:end").Set(Gf.Vec3d(3, 0, 0))
        session.stage.GetAttributeAtPath("/Pipe.aeco:pipe:outerDiameter").Set(0.9)
    with Usd.EditContext(session.stage, session.layer("derived.usda")):
        derive_gprims(
            session.stage,
            session.stage.GetPrimAtPath("/Pipe"),
            "pipe",
            derived_view=session.current(),
        )
    proxy = UsdGeom.Cylinder(session.stage.GetPrimAtPath("/Pipe/Proxy"))
    assert proxy.GetRadiusAttr().Get() == pytest.approx(0.025)
    assert proxy.GetHeightAttr().Get() == 3
    matrix = proxy.GetLocalTransformation()
    assert Gf.IsClose(matrix.Transform(Gf.Vec3d(0, 0, -1.5)), Gf.Vec3d(0), 1e-8)
    assert Gf.IsClose(matrix.Transform(Gf.Vec3d(0, 0, 1.5)), Gf.Vec3d(3, 0, 0), 1e-8)


def test_arc_wall_curve_and_bbox_proxy(session):
    p = session.stage.GetPrimAtPath("/Pipe")
    with Usd.EditContext(session.stage, session.layer("kind.usda")):
        p.ApplyAPI("AecoWallAPI")
        p.GetAttribute("aeco:axis:start").Set(Gf.Vec3d(-1, 0, 0))
        p.GetAttribute("aeco:axis:end").Set(Gf.Vec3d(1, 0, 0))
        p.GetAttribute("aeco:axis:arcPoint").Set(Gf.Vec3d(0, 1, 0))
        p.GetAttribute("aeco:axis:curve").Set("arc")
    with Usd.EditContext(session.stage, session.layer("derived.usda")):
        derive_gprims(session.stage, p, "wall", derived_view=session.current())
    curve = UsdGeom.BasisCurves(session.stage.GetPrimAtPath("/Pipe/Axis"))
    points = curve.GetPointsAttr().Get()
    assert len(points) == 33
    assert points[16] == Gf.Vec3f(0, 1, 0) or Gf.IsClose(
        points[16], Gf.Vec3f(0, 1, 0), 1e-6
    )
    assert curve.GetPrim().GetAttribute("aeco:derived:approx").Get() == "arcSegmented"
    with pytest.raises(ValueError):
        arc_points((0, 0, 0), (1, 0, 0), (2, 0, 0))


def test_graph_walk_handles_cycles_and_reverse_joins(session):
    with Usd.EditContext(session.stage, session.layer("kind.usda")):
        for name, target in [("A", "B"), ("B", "C"), ("C", "A")]:
            p = session.stage.DefinePrim("/" + name, "Xform")
            p.CreateRelationship("aeco:wall:joinAtEnd").SetTargets(["/" + target])
    assert walk(session.stage, ["/A"]) == ["/A", "/B", "/C"]


@pytest.mark.parametrize(
    "target,near_start,expected",
    [
        ((2.5, 0, 0), True, ((2.5, 0, 0), (3.5, 0, 0))),
        ((4, 0, 0), False, ((2, 0, 0), (4, 0, 0))),
        ((2, 1, 0), True, ((2, 1, 0), (3.5, 1, 0))),
    ],
)
def test_segment_rule(target, near_start, expected):
    start, end = segment_near_end((2, 0, 0), (3.5, 0, 0), target, near_start)
    assert np.allclose(start, expected[0]) and np.allclose(end, expected[1])


def test_segment_cannot_invert():
    with pytest.raises(ValueError):
        segment_near_end((0, 0, 0), (1, 0, 0), (2, 0, 0), True)


def test_validator_scope_registry_derived_and_stale(session):
    bare = session.stage.DefinePrim("/Bare", "Xform")
    bare.ApplyAPI("AecoElementAPI")
    p = session.stage.GetPrimAtPath("/Pipe")
    p.ApplyAPI("AecoHostBindingAPI", "futureHost")
    author(session, "/Pipe", ["length=3"])
    with Usd.EditContext(session.stage, session.intent):
        p.GetAttribute("aeco:pipe:outerDiameter").Set(0.2)
    session.layer("result.ifc.usda").customLayerData = {PREFIX + "version": "new"}
    found = validate_stage(session.stage)
    names = [e.GetName() for e in found]
    assert set(names) == {
        "bindingInstanceUnregistered",
        "bindingMissing",
        "derivedAuthoredInIntent",
        "staleIntent",
    }
    assert not any(
        str(site.GetPrim().GetPath()) == "/Bare"
        for error in found
        for site in error.GetSites()
        if site.GetPrim()
    )


def test_identity_roundtrip_and_namespace():
    source = "946ea480-cd43-4abc-9018-85e327fdab24"
    assert identity.guid_to_uuid(identity.uuid_to_guid(source)) == source
    assert identity.mint_id(
        "revit", "stable-id", document="document-a"
    ) == identity.mint_id("revit", "stable-id", document="document-a")
    assert identity.mint_id(
        "revit", "stable-id", document="document-a"
    ) != identity.mint_id("generated", "stable-id", document="document-a")
    # Fixed known-answer hash verifies .NET Guid byte ordering independently.
    import uuid

    assert identity.to_ifc_guid(bytes(range(16))) == identity.uuid_to_guid(
        uuid.UUID(bytes_le=bytes(range(16)))
    )


def test_unsupported_prim_metadata_is_pending_and_withdrawable(session):
    with Usd.EditContext(session.stage, session.intent):
        session.stage.DefinePrim("/New", "Xform")
        session.stage.GetPrimAtPath("/Pipe").SetCustomDataByKey("test", "pending")
    assert session.status()["pending"] >= 3
    withdraw(session)
    assert session.status()["inSync"]
    assert not session.intent.rootPrims


@pytest.mark.parametrize(
    "vector",
    json.loads((Path(__file__).parent / "fixtures/port_guid_vectors.json").read_text()),
)
def test_revit_export_port_identity_vectors(vector):
    if "peerGuid" in vector:
        candidates = identity.connected_candidates(
            vector["elementGuid"],
            vector["connectorId"],
            vector["peerGuid"],
            vector["peerConnectorId"],
        )
    else:
        candidates = [identity.free_port(vector["elementGuid"], vector["connectorId"])]
    assert vector["expected"] in candidates
