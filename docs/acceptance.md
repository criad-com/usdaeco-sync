# Protocol acceptance

Version 0.5.4 runs from source against core v0.9.2, axis v0.1.2 and
toolchain v0.3.8. The optional CCTV companion is v0.5.2. Exact revisions and
runtime versions are recorded in [dependencies.json](../dependencies.json).
This patch updates public names to github.com/criad-com and the toolchain pin.
The intent/result/diagnostics protocol, engine and host interface are unchanged.

| Acceptance item | Observed result |
|---|---|
| Python gate | 52 checks, 0 failed, 0 not run |
| Regression tests | 275 passed, 0 skipped; setuptools absent |
| Raw structure lint | 29 checks, 0 failed under toolchain v0.3.8 |
| Public names | 23 references updated in 5 files; 0 obsolete public references remain |
| Release version | 0.5.4 in library, package, runtime and plugin metadata; CHANGELOG updated |
| Other pins | Core v0.9.2, axis v0.1.2 and optional CCTV v0.5.2 unchanged |
| Packaging paths | 4 packages and 5 data files exist; 0 missing paths |
| Schema generation | core v0.9.2 and axis v0.1.2 closure; generated schema unchanged |
| Sync validators | 2/2 discovered and loaded |
| Core validators | 8/8 imported and loaded through UsdValidation; duplicate identity caught |
| Existing minimal stages | 2 compose without family plugins; validation has 0 errors, 2 classification warnings |
| Protocol vocabulary | Exact legacy class/property sets preserved |
| Sanitization | S25 passes with the public org name |
| Nix | 1 offline attempt; local daemon socket connection denied before evaluation; not proven |

The [machine-readable report](acceptance.json) includes all raw structure rows.
S08/S09 use explicit class-prefix and namespace declarations in library.json.
S29 is an additional structure rule in the new toolchain, accounting for the
increase from 51 to 52 gate checks.

| Publication-related rule | Applicability and result |
|---|---|
| S21 | PASS not applicable (library): no executable example tree |
| S22 | PASS not applicable (library): no publication manifest |
| S23 | PASS: existing documentation image meets render caps |
| S24 | PASS: 2 existing stage roots compose without family plugins |
| S25 | PASS: repository term sweep |
| S26 | PASS: family check contract |
| S27 | PASS not applicable (library): no result crate |
| S28 | PASS not applicable (library): no published vanilla render |
| S29 | PASS not applicable (library): no archived result layers |

The host integration repositories own executable round-trip examples. No
result or render was republished. The fake host tests exercise publication,
refusals, stale intent, rollback, lifecycle and discovery. Validation used
source archives of the exact release tags and their committed schema resources;
no sibling checkout was modified or built.

## Deviations

- The single offline Nix attempt failed before evaluation: the outbound-network
  restriction also denied access to the local Nix daemon socket. No retry was
  made; Nix evaluation and execution remain not proven.
- Wheel installation remains not proven. Packaging declarations were inspected
  from source, and pytest ran without setuptools or an editable install.
