"""Version contracts for plugin registration, independent of USD imports."""
from packaging.specifiers import SpecifierSet
from packaging.version import Version

# The reference reader is optional; earlier supported schemas use the fallback.
OPTIONAL_REQUIREMENTS = {"usdAecoCctv": ">=0.4.8,<0.6"}
LEGACY_CAMERA_REQUIREMENT = ">=0.4.4,<0.4.8"


def shared_camera_reader_available(version):
    return version is not None and Version(version) in SpecifierSet(OPTIONAL_REQUIREMENTS["usdAecoCctv"])


def check_requirements(sync, available):
    """Enforce Sync's built manifest and bounds on installed companions."""
    requirements = dict(sync["requires"])
    for name, bound in OPTIONAL_REQUIREMENTS.items():
        if name in available:
            version = available[name].get("version")
            legacy = version is not None and Version(version) in SpecifierSet(LEGACY_CAMERA_REQUIREMENT)
            requirements[name] = LEGACY_CAMERA_REQUIREMENT if legacy else bound
    for name, bound in requirements.items():
        version = available.get(name, {}).get("version")
        if version is None or Version(version) not in SpecifierSet(bound):
            raise RuntimeError(f"usdAecoSync requires {name} {bound}: found {version or 'MISSING'}")
