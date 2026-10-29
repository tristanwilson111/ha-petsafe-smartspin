# Third-party notices

This project is MIT licensed (see `LICENSE`). It redistributes or depends on the
following third-party components, each under its own license.

## Vendored Tuya mobile API client

- Path: `custom_components/petsafe_smartspin/vendor/`
- Upstream: https://github.com/abovecolin/tuya-mobile
- Upstream commit: `86301173cb3c9fc543841f269805438151460dad`
- Upstream license: MIT — see `custom_components/petsafe_smartspin/vendor/LICENSE`
- Modifications: see `custom_components/petsafe_smartspin/vendor/PROVENANCE.txt`.

No upstream application identity, signing secret, or bundled device profile is
redistributed.

## Runtime dependency

- `tinytuya` 1.20.0 — MIT License. https://pypi.org/project/tinytuya/
  Installed by Home Assistant from the integration manifest's `requirements`.

## Development-only dependencies

- `pytest-homeassistant-custom-component` 0.13.348 — MIT License.
- `androguard` 4.1.4 — Apache-2.0. Used only by `tools/extract_app_profile.py`.
- `apksigtool` 0.1.0 — used only by `tools/extract_app_profile.py`.

## Not redistributed

- PetSafe Pet Companion application packages, resources, DEX code, native
  libraries, or extracted signing constants.
- PetSafe, Radio Systems Corporation, Tuya, or Smart Life brand assets.
- Official Home Assistant or HACS brand assets.
