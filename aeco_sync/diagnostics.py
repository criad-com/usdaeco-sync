"""Normalized transient findings, one independent namespace per host."""

import json
from pxr import Sdf, Usd, Vt
from .stack import facts


class Diagnostics:
    def __init__(self):
        self.items = []

    def add(
        self,
        severity,
        code,
        message,
        about=(),
        blocking=False,
        phase="apply",
        host_refs=(),
    ):
        self.items.append(
            dict(
                severity=severity,
                code=code,
                message=message,
                about=[str(p) for p in about],
                blocking=blocking,
                phase=phase,
                hostRefs=list(host_refs),
            )
        )

    def write(self, session, layer, host, version, document):
        layer.Clear()
        layer.pseudoRoot.SetInfo(
            "fallbackPrimTypes", {"AecoSyncDiagnostic": Vt.TokenArray(["Scope"])}
        )
        with Usd.EditContext(session.stage, layer):
            session.stage.DefinePrim("/Sync", "Scope")
            session.stage.DefinePrim("/Sync/Diagnostics", "Scope")
            session.stage.DefinePrim(f"/Sync/Diagnostics/{host}", "Scope")
            for i, item in enumerate(self.items, 1):
                p = session.stage.DefinePrim(
                    f"/Sync/Diagnostics/{host}/d{i:04}", "AecoSyncDiagnostic"
                )
                for name in (
                    "severity",
                    "code",
                    "message",
                    "phase",
                    "blocking",
                    "hostRefs",
                ):
                    types = {"severity": Sdf.ValueTypeNames.Token, "code": Sdf.ValueTypeNames.String,
                             "message": Sdf.ValueTypeNames.String, "phase": Sdf.ValueTypeNames.Token,
                             "blocking": Sdf.ValueTypeNames.Bool, "hostRefs": Sdf.ValueTypeNames.StringArray}
                    # A caller may have initialized USD's registry before loading
                    # sync. Explicit property types keep that diagnostic legible.
                    p.CreateAttribute("aeco:diag:" + name, types[name], custom=False,
                                      variability=Sdf.VariabilityUniform if name in ("severity", "phase") else Sdf.VariabilityVarying).Set(item[name])
                p.CreateAttribute("aeco:diag:host", Sdf.ValueTypeNames.Token, custom=False,
                                  variability=Sdf.VariabilityUniform).Set(host)
                p.CreateRelationship("aeco:diag:about", custom=False).SetTargets(
                    [Sdf.Path(p) for p in item["about"]]
                )
                native = {
                    k: v
                    for k, v in item.items()
                    if k
                    not in {
                        "severity",
                        "code",
                        "message",
                        "phase",
                        "blocking",
                        "hostRefs",
                        "about",
                    }
                }
                if native:
                    p.SetCustomDataByKey(
                        "aecoSync:native", json.dumps(native, sort_keys=True)
                    )
        layer.customLayerData = facts(host, document, version, session.policy)
