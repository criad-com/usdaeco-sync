# usdAecoSync — edit in USD, let the host solve

## Use case

Author drivers in an intent layer. Let an installed host integration solve them.
Publish resolved results and diagnostics separately; see [use case](docs/usecase.md)
and [host contract](docs/host-contract.md).

## The schema on an index card

| Schema / layer | Purpose |
|---|---|
| AecoHostBindingAPI (multiple apply) | cached native handles, version and document; identity stays aeco:id |
| AecoSyncDiagnostic (Scope fallback) | transient severity, code, message and affected paths |
| intent / result / diagnostics / derived | editor requests / host receipts / findings / generated guides |

## The example

[Minimal wall and pipe](usdAecoSync/examples/minimal.usda) compose without plugins.
The [IFC integration](https://github.com/criad-com/usdaeco-ifc) owns the executable
facility round trip. Sync's regression host is [tests/fake_host.py](tests/fake_host.py).

![Protocol example](usdAecoSync/userDoc/usdAecoSyncExample.png)

## Build and check

With core v0.9.5, axis v0.1.5 and toolchain v0.3.10 sibling source checkouts and
Python 3.11+ with usd-core 26.8, numpy, packaging, jinja2, Pillow and pytest:

```sh
export PYTHON=python
export AECO_CORE_ROOT=../usdaeco-core
export AECO_AXIS_ROOT=../usdaeco-axis
export TOOLCHAIN_DIR=../usdaeco-toolchain
export CORE_PLUGIN_DIR=$AECO_CORE_ROOT/usdAeco
export AXIS_PLUGIN_DIR=$AECO_AXIS_ROOT/usdAecoAxis
export PXR_PLUGINPATH_NAME=$CORE_PLUGIN_DIR:$AXIS_PLUGIN_DIR
bash build.sh --generate-only
env -u PYTHONPATH PYTHONPATH=$AECO_CORE_ROOT:$PWD python check.py
env -u PYTHONPATH python -m pytest -q
nix flake check
```

`check.py` prints `N checks, M failed`, including all 29 structure rules. It must
import the core validators and load all eight through UsdValidation; a seeded
duplicate identity proves that they execute. Tests run directly from source,
without setuptools or an editable install. `AECO_CORE_ROOT`, `AECO_AXIS_ROOT` and `TOOLCHAIN_DIR`
select alternate checkouts. Optional camera integration uses CCTV v0.5.2;
`AECO_CCTV_ROOT` selects its checkout. No IFC or Blender package is required. Install a
host integration to use `aeco-sync init model.usda model.ifc --kind-import` and
`aeco-sync --stage stage.usda apply --host ifc`. Source users may pass
`--host-module package.module:Class`; installed integrations use entry points.

Flake inputs name public source tags. For a local source mirror use
`nix flake check --offline --no-write-lock-file --override-input toolchain path:../usdaeco-toolchain
--override-input core path:../usdaeco-core
--override-input axis path:../usdaeco-axis` (one shell command). The toolchain's
repository conventions describe registry files and nested overrides.

## Family

Requires `usdAeco >=0.9.2,<1.0` and `usdAecoAxis >=0.1,<0.2`; tested against
core v0.9.5 and axis v0.1.5. This release uses tier
`record`. Exact source pins are in [dependencies.json](dependencies.json).
The [family board](https://github.com/criad-com/usdaeco-board) consumes those pins.

## Layout

`usdAecoSync/` is the codeless schema; `usdAecoSyncValidators/` registers Python
UsdValidation rules. `aeco_sync/` owns protocol, engine, identity and convergence;
`tools/usdaeco_sync/` exposes the companion CLI. `testenv/` mirrors USD module
tests; `tests/` holds transaction and fake-host regressions.

## Status

Version 0.5.5: 52 checks, 0 failed; 275 tests pass. Host integrations are separate
packages. The existing wire names
are [declared explicitly](docs/host-contract.md#compatibility-and-schema-lint)
for S08/S09. The library has no executable round-trip example; S21/S22/S27/S28/S29
are explicitly not applicable. S23/S24 still check the existing documentation
image and minimal stages; S25/S26 check sanitization and the gate contract.
The single offline Nix attempt evaluated five Darwin derivations; builds remain
not proven (see [acceptance](docs/acceptance.md)). Native solver and wheel
packaging claims belong to their measured integration gates; an exact readback
route remains future work.

## Licence

[MIT](LICENSE). Copyright (c) 2026 Criad

Runtime dependencies retain their own licences:

| Dependency | Licence |
|---|---|
| OpenUSD (`usd-core`) | Apache-2.0-style TOST (`LicenseRef-TOST-1.0`) |
| numpy | BSD-3-Clause |
| packaging | Apache-2.0 OR BSD-2-Clause |

Source checks also use jinja2 (BSD-3-Clause), Pillow (HPND), pytest (MIT), and
the family core, axis and toolchain under the licences in their pinned releases.
Dependencies are imported, never vendored. The shipped package data is the
validator descriptor; the schema resources and host-name registry are explicit
data files. Wheel installation remains unproven by the source gate.

Measured release results and deviations are recorded in [acceptance](docs/acceptance.md).
