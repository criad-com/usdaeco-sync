"""Real manifest bounds reject incompatible plugins before USD registration."""
import json
from pathlib import Path

import pytest

from aeco_sync.requirements import OPTIONAL_REQUIREMENTS, check_requirements

ROOT = Path(__file__).resolve().parents[1]


def metadata(source):
    if source == "manifest":
        return json.loads((ROOT / "library.json").read_text())
    return json.loads("\n".join(line for line in (ROOT / "usdAecoSync/plugInfo.json").read_text().splitlines() if not line.lstrip().startswith("#")))["Plugins"][0]["Info"]["aeco"]


@pytest.mark.parametrize("source", ["manifest", "plugin"])
@pytest.mark.parametrize("version,accepted", [
    ("0.9.0", False), ("0.9.1", False), ("0.9.2", True), ("0.9.3", True),
    ("0.8.4", False), ("1.0.0", False),
])
def test_core_requirement_bounds(source, version, accepted):
    available = {"usdAecoAxis": {"version": "0.1.0"}, "usdAeco": {"version": version}}
    if accepted:
        check_requirements(metadata(source), available)
    else:
        with pytest.raises(RuntimeError, match="requires usdAeco .*found " + version):
            check_requirements(metadata(source), available)


@pytest.mark.parametrize("version,accepted", [
    ("0.4.4", True), ("0.4.5", True), ("0.4.3", False), ("0.6.0", False),
])
def test_optional_camera_requirement_bounds(version, accepted):
    available = {"usdAecoAxis": {"version": "0.1.0"}, "usdAeco": {"version": "0.9.2"}, "usdAecoCctv": {"version": version}}
    if accepted:
        check_requirements(metadata("plugin"), available)
        check_requirements(metadata("plugin"), {**available, "usdAecoCctv": {"version": "0.5.0"}})
    else:
        with pytest.raises(RuntimeError, match="requires usdAecoCctv .*found " + version):
            check_requirements(metadata("plugin"), available)


def test_core_and_axis_are_required_and_cctv_is_optional():
    check_requirements(metadata("plugin"), {"usdAecoAxis": {"version": "0.1.0"}, "usdAeco": {"version": "0.9.2"}})
    with pytest.raises(RuntimeError, match="requires usdAeco .*MISSING"):
        check_requirements(metadata("plugin"), {})
    with pytest.raises(RuntimeError, match="requires usdAecoAxis .*MISSING"):
        check_requirements(metadata("plugin"), {"usdAeco": {"version": "0.9.2"}})
    with pytest.raises(RuntimeError, match="requires usdAecoAxis .*found 0.2.0"):
        check_requirements(metadata("plugin"), {"usdAeco": {"version": "0.9.2"},
                                                 "usdAecoAxis": {"version": "0.2.0"}})


def test_packaging_requirement_and_source_pin_agree():
    from packaging.specifiers import SpecifierSet
    pins = json.loads((ROOT / "dependencies.json").read_text())["repos"]
    for name, library in (("core", "usdAeco"), ("axis", "usdAecoAxis")):
        assert pins[name]["ref"].removeprefix("v") in SpecifierSet(metadata("manifest")["requires"][library])
        assert "ref=" + pins[name]["ref"] in (ROOT / "flake.nix").read_text()
