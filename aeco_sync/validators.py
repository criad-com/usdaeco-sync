"""Sync validation companion, registered under AecoSyncValidators."""

import json
from pathlib import Path
from .profiles import apply_profile, load_profile
from pxr import Sdf, Usd, UsdValidation
from . import register_plugins
from .edits import collect
from .stack import PREFIX, find_layer

KEYWORD = "UsdAecoSyncValidators"
_REGISTERED = False
SYNC_APIS = {
    "AecoCctvCameraAPI", "AecoCctvSensorAPI", "AecoCctvPresetAPI", "AecoCctvCameraTypeAPI",
    "AecoAxisAPI",
    "AecoPipeAPI",
    "AecoWallAPI",
    "AecoPipeFittingAPI",
    "AecoPipePortAPI",
    "AecoBuildUpAPI",
    "AecoPipeTypeAPI",
}


def finding(code, stage, path, message, warning=False):
    level = (
        UsdValidation.ValidationErrorType.Warn
        if warning
        else UsdValidation.ValidationErrorType.Error
    )
    return UsdValidation.ValidationError(
        code, level, [UsdValidation.ValidationErrorSite(stage, Sdf.Path(path))], message
    )


def bindings(stage, time_range):
    root = register_plugins()
    hosts = json.loads((root / "registries/host_names.json").read_text())["hosts"]
    result = []
    for prim in stage.TraverseAll():
        schemas = prim.GetAppliedSchemas()
        names = [
            s.split(":", 1)[1] for s in schemas if s.startswith("AecoHostBindingAPI:")
        ]
        for name in names:
            if name not in hosts:
                result.append(
                    finding(
                        "bindingInstanceUnregistered",
                        stage,
                        prim.GetPath(),
                        f"Unknown host binding instance: {name}",
                        True,
                    )
                )
        if SYNC_APIS.intersection(s.split(":", 1)[0] for s in schemas) and not any(
            prim.GetAttribute(f"aeco:host:{n}:ref").Get() for n in names
        ):
            result.append(
                finding(
                    "bindingMissing",
                    stage,
                    prim.GetPath(),
                    "Sync-relevant prim has no populated host binding",
                    True,
                )
            )
    return result


def intent_rules(stage, time_range):
    intent = find_layer(stage, "intent.usda")
    if intent is None:
        return []
    current = Usd.Stage.Open(stage.GetRootLayer())
    current.MuteLayer(intent.identifier)
    edits = collect(stage, intent, current)
    result = [
        finding(
            "derivedAuthoredInIntent",
            stage,
            e.property_path,
            "Derived opinion authored in intent.usda",
        )
        for e in edits
        if e.kind == "derived"
    ]
    versions = intent.customLayerData.get(PREFIX + "baseVersions", {})
    for host, version in versions.items():
        layer = find_layer(stage, f"result.{host}.usda")
        now = (
            layer.customLayerData.get(PREFIX + "version") if layer else None
        ) or stage.GetRootLayer().customLayerData.get(PREFIX + "version")
        if edits and now and now != version:
            result.append(
                finding(
                    "staleIntent",
                    stage,
                    edits[0].property_path,
                    f"{host} result version moved since intent was authored",
                )
            )
    return result


def register():
    from pxr import Plug
    root = register_plugins()
    Plug.Registry().RegisterPlugins(str(root / "usdAecoSyncValidators"))
    registry = UsdValidation.ValidationRegistry()
    for name in ("BindingsChecker", "IntentChecker"):
        if not registry.GetOrLoadValidatorByName("usdAecoSyncValidators:" + name):
            raise RuntimeError("Cannot load sync validator " + name)


def validate_stage(stage, profile=None):
    register()
    registry = UsdValidation.ValidationRegistry()
    names = [m.name for m in registry.GetValidatorMetadataForKeyword(KEYWORD)]
    if profile is not None and load_profile(profile).get("include_builtin", True):
        names += [m.name for m in registry.GetValidatorMetadataForKeyword("UsdCoreValidators")]
    errors = UsdValidation.ValidationContext(registry.GetOrLoadValidatorsByName(names)).Validate(stage)
    legacy = [UsdValidation.ValidationError(e.GetName()[0].lower() + e.GetName()[1:],
              e.GetType(), e.GetSites(), e.GetMessage()) if e.GetName() in
              {"BindingMissing", "BindingInstanceUnregistered", "DerivedAuthoredInIntent", "StaleIntent"}
              else e for e in errors]
    return apply_profile(legacy, profile)
