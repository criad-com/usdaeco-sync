#!/usr/bin/env python3
"""Run protocol contracts and print N checks, M failed."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(os.environ.get("TOOLCHAIN_DIR", ROOT.parent / "usdaeco-toolchain")) / "tools"))
from usdaeco_check import Report, registry_probe, can_apply, validate_examples
from usdaeco_check.structure import check_structure
from aeco_sync import register_plugins


def legacy_schema_contract():
    """Keep the shipped binding and diagnostic vocabulary unchanged."""
    from pxr import Sdf
    layer = Sdf.Layer.FindOrOpen(str(ROOT / "usdAecoSync/schema.usda"))
    binding = layer.GetPrimAtPath("/AecoHostBindingAPI")
    diagnostic = layer.GetPrimAtPath("/AecoSyncDiagnostic")
    return ({p.name for p in layer.rootPrims} == {"GLOBAL", "AecoHostBindingAPI", "AecoSyncDiagnostic"}
        and binding.customData["propertyNamespacePrefix"] == "aeco:host"
        and set(binding.properties.keys()) == {"ref", "localRef", "version", "document"}
        and set(diagnostic.properties.keys()) == {"aeco:diag:" + n for n in
            ("severity", "code", "message", "host", "phase", "blocking", "hostRefs", "about")})


def source_packaging_contract():
    """Verify declared package and data paths without importing a build backend."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]
    packages = {name: ROOT / config.get("package-dir", {}).get(name, name.replace(".", "/"))
                for name in config["packages"]}
    failures = [name for name, path in packages.items() if not (path / "__init__.py").is_file()]
    files = []
    for name, patterns in config.get("package-data", {}).items():
        for pattern in patterns:
            matches = list(packages[name].glob(pattern)) if name in packages else []
            if not matches:
                failures.append(f"{name}: {pattern}")
            files.extend(matches)
    for paths in config.get("data-files", {}).values():
        files.extend(ROOT / path for path in paths)
    failures.extend(str(path.relative_to(ROOT)) for path in files if not path.is_file())
    return not failures, ("; ".join(failures) if failures else
                          f"{len(packages)} packages, {len(files)} data files; source inspection only")


def main():
    report = Report()
    print("== stage: structure", flush=True)
    core = Path(os.environ.get("AECO_CORE", os.environ.get("AECO_CORE_ROOT", ROOT.parent / "usdaeco-core")))
    axis = Path(os.environ.get("AECO_AXIS_ROOT", ROOT.parent / "usdaeco-axis"))
    dependencies = [os.environ.get("CORE_PLUGIN_DIR", str(core / "out/plugins/usdAeco/resources")),
                    os.environ.get("AXIS_PLUGIN_DIR", str(axis / "out/plugins/usdAecoAxis/resources"))]
    raw = check_structure(ROOT, deps=dependencies)
    for result in raw:
        report.add(result)
    report.check("preserved protocol vocabulary", legacy_schema_contract())
    report.check("packaging source paths", *source_packaging_contract())
    register_plugins()
    from pxr import Gf, Plug, Sdf, Usd, UsdGeom, UsdValidation
    from aeco_sync.validators import register, validate_stage, KEYWORD
    from aeco_sync.hosts.base import Host
    print("== stage: registry and protocol", flush=True)
    Plug.Registry().RegisterPlugins(str(ROOT / "usdAecoSyncValidators"))
    report.add(registry_probe(["AecoHostBindingAPI"], ["AecoSyncDiagnostic", "AecoPort"]))
    report.add(can_apply([("Xform", "AecoHostBindingAPI", True, "ifc")]))
    stage = Usd.Stage.CreateInMemory()
    prim = UsdGeom.Xform.Define(stage, "/Wall").GetPrim()
    report.check("multiple host binding instances", prim.ApplyAPI("AecoHostBindingAPI", "ifc") and prim.ApplyAPI("AecoHostBindingAPI", "revit"))
    report.check("distinct handle namespaces", bool(prim.GetAttribute("aeco:host:ifc:ref")) and bool(prim.GetAttribute("aeco:host:revit:ref")))
    diag = stage.DefinePrim("/Finding", "AecoSyncDiagnostic")
    report.check("diagnostic severity fallback", diag.GetAttribute("aeco:diag:severity").Get() == "warning")
    report.check("diagnostic vanilla fallback", list(Usd.SchemaRegistry().GetFallbackPrimTypes()["AecoSyncDiagnostic"]) == ["Scope"])
    report.check("axis derived metadata registered through core", Usd.SchemaRegistry().FindAppliedAPIPrimDefinition("AecoAxisAPI").GetPropertyMetadata("aeco:axis:length", "aecoDerived") is True)
    register()
    registry = UsdValidation.ValidationRegistry()
    metadata = registry.GetValidatorMetadataForKeyword(KEYWORD)
    report.check("validator plugin listing", len(metadata) == 2 and all(registry.GetOrLoadValidatorByName(m.name) for m in metadata))
    print("== stage: core validation", flush=True)
    Plug.Registry().RegisterPlugins(str(core / "usdAecoValidators"))
    try:
        import usdAecoValidators
    except ImportError as exc:
        raise RuntimeError("Core validators are required; make the core checkout importable via PYTHONPATH") from exc
    core_metadata = registry.GetValidatorMetadataForKeyword("UsdAecoValidators")
    core_validators = registry.GetOrLoadValidatorsByName([m.name for m in core_metadata])
    loaded = len(core_metadata) == len(core_validators) == 8 and all(core_validators)
    report.check("core validator plugin listing", loaded, f"{len(core_validators)}/8 validators loaded")
    if not loaded:
        return report.finish()
    core_context = UsdValidation.ValidationContext(core_validators)
    report.add(validate_examples(ROOT / "usdAecoSync/examples", [],
                                 validators=[core_context.Validate, validate_stage]))
    defect = Usd.Stage.CreateInMemory()
    for path in ("/First", "/Second"):
        element = UsdGeom.Xform.Define(defect, path).GetPrim()
        element.ApplyAPI("AecoElementAPI")
        element.GetAttribute("aeco:id").Set("946ea480-cd43-4abc-9018-85e327fdab24")
    report.check("core validator detects duplicate identity", any(
        e.GetName() == "duplicateId" and e.GetType() == UsdValidation.ValidationErrorType.Error
        for e in core_context.Validate(defect)))
    prim.ApplyAPI("AecoHostBindingAPI", "futureHost")
    report.check("unknown binding warns", any(e.GetName() == "bindingInstanceUnregistered" and e.GetType() == UsdValidation.ValidationErrorType.Warn for e in validate_stage(stage)))
    from aeco_sync.identity import guid_to_uuid, uuid_to_guid
    sample = "946ea480-cd43-4abc-9018-85e327fdab24"
    report.check("identity is reversible", guid_to_uuid(uuid_to_guid(sample)) == sample)
    report.check("host lifecycle abstract", {"capabilities", "open", "apply", "readback", "diagnostics", "close"} <= Host.__abstractmethods__)
    imports = []
    for path in (ROOT / "aeco_sync").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import): imports += [a.name.split('.')[0] for a in node.names]
            if isinstance(node, ast.ImportFrom): imports += [(node.module or '').split('.')[0]]
    report.check("zero native imports", not {"ifcopenshell", "bpy"}.intersection(imports))
    report.check("no bundled hosts", {p.name for p in (ROOT / "aeco_sync/hosts").glob('*.py')} == {"__init__.py", "base.py"})
    from aeco_sync.convergence import metrics, compare_receipts
    mesh = {"verts": [0,0,0, 1,0,0, 0,1,0, 0,0,1], "faces": [0,2,1, 0,1,3, 0,3,2, 1,2,3]}
    report.check("convergence closed-body volume", abs(metrics(mesh, Gf.Matrix4d(1))["volume"] - 1/6) < 1e-12)
    row = dict(id=sample, ref=uuid_to_guid(sample), path="/Wall", kind="wall", drivers={"aeco:axis:start":[0,0,0],"aeco:axis:end":[1,0,0],"aeco:wall:height":1}, matrix=Gf.Matrix4d(1))
    receipt = dict(touched=[row],meshes={row['ref']:mesh})
    comparison = compare_receipts(receipt,receipt)
    report.check("convergence identical receipts", comparison['driversConverged'] and not comparison['diagnostics'])
    changed = dict(receipt, meshes={})
    report.check("missing body raises divergence", any(d['code'] == 'bodyDivergence' for d in compare_receipts(receipt,changed)['diagnostics']))
    print("== stage: fake host regressions", flush=True)
    env = {k:v for k,v in os.environ.items() if k != 'PYTHONPATH'}
    result = subprocess.run([sys.executable,'-m','pytest','-q','--tb=short'],cwd=ROOT,env=env,capture_output=True,text=True)
    print(result.stdout)
    if result.returncode: print(result.stderr)
    report.check("pytest", result.returncode == 0)
    import re
    count = re.search(r'(\d+) passed', result.stdout)
    report.check("at least 200 engine and protocol tests", bool(count) and int(count.group(1)) >= 200)
    evidence = {'checks':len(report.results),'failed':report.failed,'pytest':int(count.group(1)) if count else 0,
                'rawStructure': [dict(rule=r.name,passed=r.ok,detail=r.detail) for r in raw],
                'coreValidators':len(core_validators), 'deviations':[]}
    out = ROOT / '.work';out.mkdir(exist_ok=True)
    (out/'check.json').write_text(json.dumps(evidence,indent=2)+'\n')
    return report.finish()

if __name__ == '__main__': raise SystemExit(main())
