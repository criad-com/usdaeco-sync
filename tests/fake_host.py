"""Deterministic in-memory host for protocol tests; no native geometry kernel."""
import json
from pathlib import Path
from aeco_sync.stack import value, digest
from pxr import Gf
from aeco_sync.hosts.base import Host, MutationReceipt
from aeco_sync.identity import uuid_to_guid


def clone(value):
    if isinstance(value, dict): return {k:clone(v) for k,v in value.items()}
    if isinstance(value, list): return [clone(v) for v in value]
    return value


class FakeHost(Host):
    name = "ifc"

    def __init__(self, session=None, document=None, **options):
        self.document = document
        self.calls = []
        self.closed = False
        self.fail = False
        self.refuse = False
        self.rows = []
        if session:
            self.open(session)

    def capabilities(self):
        return frozenset({"attribute", "activation", "relationship", "primMetadata"})

    def open(self, session):
        self.session = session
        self.current = session.current()
        self.document = self.document or session.document(self.name)
        self.token = session.version(self.name)
        self.records = {}
        for prim in self.current.Traverse():
            identity = prim.GetAttribute("aeco:id")
            if not identity or not identity.Get():
                continue
            ref = uuid_to_guid(identity.Get())
            self.records[ref] = dict(path=str(prim.GetPath()), ref=ref,
                id=identity.Get(), drivers={a.GetName(): a.Get() for a in prim.GetAttributes()
                    if a.HasAuthoredValueOpinion() and not a.GetMetadata("aecoDerived")},
                derived={}, active=prim.IsActive())
        return self

    def supports(self, edit):
        return not self.refuse and super().supports(edit)

    def apply(self, operations):
        self.calls.append(operations)
        if self.fail:
            raise RuntimeError("Seeded host transaction failure")
        changed = set()
        for edit in operations:
            row = self.records[edit.ref]
            if edit.operation == "activation":
                row["active"] = edit.value
            elif edit.operation == "relationship":
                row.setdefault("joins", {})[edit.name] = edit.value
            elif edit.name == "xformOp:transform":
                row["matrix"] = Gf.Matrix4d(edit.value)
            else:
                row["drivers"][edit.name] = edit.value
            changed.add(edit.ref)
        self.token += ":applied"
        return MutationReceipt(tuple(sorted(changed)), self.token)

    def readback(self, ids):
        return dict(touched=[clone(self.records[r]) for r in (ids if ids is not None else self.records)],
                    meshes={}, stamp="fake host")

    def save(self, path):
        Path(path).write_text(json.dumps(value(self.records), sort_keys=True))
        self.document = Path(path)
        self.token = digest(path)

    def diagnostics(self):
        return list(self.rows)

    def version(self):
        return self.token

    def close(self):
        self.closed = True
