"""usdAeco sync: intent in, host results and diagnostics out."""

__version__ = "0.5.5"


def register_plugins(core=None, kind=None):
    """Register core first and enforce the declared dependency before USD use.

    AECO_CORE and AECO_AXIS_ROOT select built core and axis checkouts.
    CORE_PLUGIN_DIR and AXIS_PLUGIN_DIR select installed resources directly.
    AECO_KIND_PLUGIN optionally
    selects the isolated prototype fixture or a real kind plugin aggregate.
    """
    import json
    import os
    import sys
    sys.dont_write_bytecode = True
    from pathlib import Path
    from pxr import Plug

    repo = Path(__file__).resolve().parent.parent
    core = Path(core or os.environ.get("AECO_CORE", os.environ.get("AECO_CORE_ROOT", repo.parent / "usdaeco-core")))
    plugin = Path(os.environ.get("CORE_PLUGIN_DIR", core / "out/plugins/usdAeco/resources"))
    if not (plugin / "plugInfo.json").exists():
        raise RuntimeError("Build core >=0.9.2,<1.0 and set AECO_CORE to its checkout")
    axis = Path(os.environ.get("AECO_AXIS_ROOT", repo.parent / "usdaeco-axis"))
    axis_plugin = Path(os.environ.get("AXIS_PLUGIN_DIR", axis / "out/plugins/usdAecoAxis/resources"))
    if not (axis_plugin / "plugInfo.json").exists():
        raise RuntimeError("Build axis >=0.1,<0.2 and set AECO_AXIS_ROOT to its checkout")
    from .requirements import check_requirements

    def metadata(directory):
        text = (directory / "plugInfo.json").read_text()
        data = json.loads("\n".join(line for line in text.splitlines()
                                    if not line.lstrip().startswith("#")))
        return data["Plugins"][0]["Info"]["aeco"]

    registry = Plug.Registry()
    root = (
        repo
        if (repo / "usdAecoSync/plugInfo.json").exists()
        else Path(sys.prefix) / "share/usdaeco-sync"
    )
    sync = root / "usdAecoSync"
    if not sync.is_dir():
        sync = root / "plugins/usdAecoSync/resources"
    if not (sync / "plugInfo.json").exists():
        raise RuntimeError("Run build.sh before loading usdAecoSync")
    sync_metadata = metadata(sync)
    available = {"usdAeco": metadata(plugin), "usdAecoAxis": metadata(axis_plugin)}
    check_requirements(sync_metadata, available)
    registry.RegisterPlugins(str(plugin))
    registry.RegisterPlugins(str(axis_plugin))
    kind = kind or os.environ.get("AECO_KIND_PLUGIN")
    if kind:
        registry.RegisterPlugins(str(kind))
    # Explicit opt-in: ordinary sync installations have no CCTV dependency.
    cctv = os.environ.get("AECO_CCTV_ROOT")
    cctv_root = Path(cctv or repo.parent / "usdaeco-cctv").resolve()
    cctv_plugins = [cctv_root / path for path in
                    ("out/plugins/usdAecoCctv/resources", "usdAecoCctv", "plugins/usdAecoCctv/resources")]
    cctv_plugin = next((path for path in cctv_plugins if (path / "plugInfo.json").is_file()), None)
    if not cctv and cctv_plugin:
        cctv = str(cctv_root)
    if cctv:
        if cctv_plugin is None:
            raise RuntimeError("Build usdAecoCctv and set AECO_CCTV_ROOT to its checkout")
        cctv = cctv_root
        available["usdAecoCctv"] = metadata(cctv_plugin)
        check_requirements(sync_metadata, available)
        if str(cctv / "tools") not in sys.path:
            sys.path.insert(0, str(cctv / "tools"))
        registry.RegisterPlugins(str(cctv_plugin))
    registry.RegisterPlugins(str(sync))
    # USD keeps the first plugin registered for a name, including plugins
    # loaded through PXR_PLUGINPATH_NAME. Validate the actual active versions.
    loaded = {name: registry.GetPluginWithName(name).metadata["aeco"]
              for name in ("usdAeco", "usdAecoAxis", "usdAecoCctv") if registry.GetPluginWithName(name)}
    check_requirements(sync_metadata, loaded)
    return root
