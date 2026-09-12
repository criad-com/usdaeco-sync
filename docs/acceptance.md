# Protocol acceptance

Version 0.5.5 runs from source against core v0.9.5, axis v0.1.5 and
toolchain v0.3.10. The optional CCTV regression companion remains v0.5.2;
it is not a flake input. Exact checked revisions and runtime versions are in
[dependencies.json](../dependencies.json).

This public re-pin changes all three family flake URLs to the published release
tags. The intent/result/diagnostics protocol, engine and host interface are
unchanged. Both requirement ranges still contain the new pins.

| Acceptance item | Observed result |
|---|---|
| Python gate | 52 checks, 0 failed, 0 not run |
| Regression tests | 275 passed, 0 skipped; setuptools absent |
| Initial schema and requirement smoke | 23 passed |
| Raw structure lint | 29 checks, 0 failed under toolchain v0.3.10, including S05 |
| Public inputs | 3/3 family inputs use release tags under criad-com; 0 obsolete-org refs, 0 commit-hash family refs |
| Checked pins | toolchain v0.3.10, core v0.9.5, axis v0.1.5; all 3 tagged revisions verified |
| Requirement ranges | 2/2 pins satisfy existing ranges; 0 ranges changed |
| Release version | 0.5.5 in library, package, runtime and generated plugin metadata |
| Packaging paths | 4 packages and 5 data files exist; 0 missing paths |
| Schema generation | documented build.sh --generate-only completed against core v0.9.5 and axis v0.1.5 |
| Artifact comparison | 6/6 existing files byte-identical: 2 schema files, 3 example/documentation USD files and 1 image |
| Generated plugin | Only Info.aeco.version changes from 0.5.4 to 0.5.5 |
| Sync validators | 2/2 discovered and loaded |
| Core validators | 8/8 imported and loaded through UsdValidation; duplicate identity caught |
| Existing minimal stages | 2 compose without family plugins; validation has 0 errors, 2 classification warnings |
| Protocol vocabulary | Exact legacy class/property sets preserved |
| Documentation image | 1280 × 800, 131395 bytes, 4118 colors; original hash retained |
| Sanitization and whitespace | S25 passes; git diff --check clean |
| Nix | 1 offline attempt, 6 local overrides, 5 Darwin derivations evaluated; interrupted during source-fetch builds, exit 1; builds not proven |

The [machine-readable report](acceptance.json) includes all raw structure rows,
the checked dependency revisions and before/after SHA-256 hashes. Source checks
used frozen archives of the exact release tags and their committed schema
resources; no sibling checkout was modified or built. All four active plugin
versions were checked against that evidence. S08/S09 use the existing explicit
class-prefix and namespace declarations in library.json.

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

The host integration repositories own executable round-trip examples. Sync's
fake host tests exercise publication, refusals, stale intent, rollback,
lifecycle and discovery. No dependency behavior change was observed. Existing
CHANGELOG entries and the explicitly historical requirements audit retain their
original pins; they are not current flake inputs.

## Deviations

- The single offline Nix attempt with six local source overrides evaluated five
  Darwin derivations, then started uncached external source-fetch builds despite
  --offline. The agent interrupted the attempt to honor the network restriction
  (exit 1); no retry or lockfile was written. Nix builds remain not proven.
- Public tag availability comes from the supplied release table. Clean online
  GitHub resolution remains for the release reviewer to verify.
- This library has no result crate or vanilla render to republish. The
  documentation image was retained byte-identically; S23/S24 passed.
- Wheel installation remains not proven. Packaging declarations were inspected
  from source, and pytest ran without setuptools or an editable install.
