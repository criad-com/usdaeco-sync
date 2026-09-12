# Changelog

## 0.5.5

- public re-pin: usdaeco-toolchain v0.3.10, usdaeco-core v0.9.5, usdaeco-axis v0.1.5.
- Record checked tag revisions; retain the supported requirement ranges and optional CCTV v0.5.2 fixture.
- Regenerate plugin metadata for v0.5.5; preserve the schema, example layers and documentation image.
- Verify 52 checks and 275 tests; record the single offline Nix attempt separately as not proven.

## 0.5.4

- Public names → github.com/criad-com.
- Pin toolchain v0.3.8 for public-name structure checks.

## 0.5.3

- Re-pin to train aeco-0.7.0: core v0.9.2, axis v0.1.2 and toolchain v0.3.5.
- Record optional CCTV v0.5.2 acceptance and declare historical test fixtures separately.

## 0.5.2

- Publish under MIT and name the runtime dependency licences.
- Pin toolchain v0.3.2 and core v0.9.2; require core >=0.9.2,<1.0.
- Declare the existing class prefixes and namespaces for raw structure lint.
- Restrict package data to the shipped validator descriptor and declare the package licence.
- Check packaging paths from source and require all eight core validators in the gate.
- Retain the protocol, engine and host interface; executable examples remain in integrations.

## 0.5.1

- Re-pin to core v0.9.1, axis v0.1.0 and toolchain v0.2.1.
- Register core before axis and validate both active plugin versions.
- Preserve axis derivation, protocol vocabulary and engine behavior.
- Accept the core 0.9 CCTV v0.5 companion and its flat plugin layout.
- Confirm the removed integration script package-data entry remains absent.

## 0.5.0

- Split native host integrations from the protocol and engine.
- Add an abstract host lifecycle, entry-point discovery and explicit module override.
- Preserve identity, transaction rollback, convergence and library plugin registration.
- Adopt the flat schema and Python validator plugin skeleton with documented legacy naming exceptions.
- Test the engine with in-memory and file-backed fake hosts, without native dependencies.


## 0.4.5

- Delegate IFC camera reads to the registered optional CCTV reference reader
  in `>=0.4.8,<0.5`; retain the standalone path for older supported or absent
  companions and for the no-USD Blender process.
- Keep native IFC writing and host dialect mappings in sync, with lazy reader
  selection and propagation of errors inside an installed companion.
- Test exact shared/fallback driver dictionary parity on synthetic unit
  combinations and the optional generated 45-camera IFC.
- Keep the sync schema at 0.1.0.

## 0.4.4

- Accept core schema `>=0.8.1,<0.9`; pin builds to core v0.8.3 and preserve
  its real manifest in Nix instead of rewriting the version.
- Keep CCTV optional and require `>=0.4.4,<0.5` when installed. Validate
  plugin metadata during registration, including an already loaded companion.
- Separate compatible ranges from exact source pins in packaging metadata.
- Pin camera acceptance to the compatible CCTV 0.4.5 candidate revision.
- Honor an explicit core checkout in the no-CCTV subprocess regression.
- Add lower/upper-bound regressions for core and CCTV. Sync schema 0.1.0
  and host transaction behavior remain unchanged.

## 0.4.3

- Resolve all generated data-centre case counts and selected camera, preset,
  type and space identities from the generator plan, manifest and contracts.
- Check exact native/import censuses and print expectations for every case;
  retain all nine IFC/Bonsai operations and zero mutations on repeat apply.
- Exercise all nine IFC cases after changing corridor spacing in a temporary
  spec; reject missing or inconsistent expectation artifacts.
- Resolve live demo snapshot and full-convergence camera counts from the seed
  session; cover changed populations and incomplete receipts offline.
- Report the current package version in camera acceptance output. The codeless
  schema remains 0.1.0 and host operation implementations are unchanged.

## 0.4.1

- Parameterized live camera gate: exact background document, native IFC seed,
  synthetic camera fixture or twelve data-centre cases, smoke subsets and retained evidence.
- Native catalog bindings stay on their class across repeated read-back;
  catalog sensor aliases no longer replace symbol paths.
- Camera-scoped receipts retain full adapter rollback fingerprints, compress
  paged payloads with bounded decoding, and publish changed cameras on edits.
- Optical comparison retains measurable values when a native density threshold
  is invalid; missing or divergent observations cannot pass convergence.
- Native IFC Status/Tier A probe and live results are recorded separately from
  the offline release gate. The schema remains 0.1.0.

## 0.4.0

- Write and read the unit-explicit IFC camera contract, preserving all optics,
  controls, presets and tour order. Rewrite empty native preset tables.
- Publish unbound USD camera catalog classes as native IFC camera types during
  create/type-swap transactions and bind them on read-back.
- Execute camera operations in Bonsai's IFC store through the shared JSON
  protocol; retain native read-back and refusal diagnostics.
- Name unsupported operations and register family plugins before opening
  library sessions, applying intent or publishing read-back diagnostics.
- Resolve Revit camera levels through spatial ancestry and keep Mark labels
  separate from IFC_GUID identities. These changes are tested offline.
- Add generated data-centre camera cases for both IFC and Bonsai; pin core
  v0.8.0, CCTV v0.4.0 and the data-centre generator v0.1.0.

These releases used sync schema 0.1.0. Current source acceptance is recorded
in [acceptance](docs/acceptance.md); live integration gates belong to the host repositories.
