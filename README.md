# PetSafe SmartSpin for Home Assistant

**Experimental, unofficial, read-only integration for the PetSafe ScoopFree SmartSpin.**
Keep your litter box paired with **PetSafe Pet Companion**. Normal operation uses
its local Tuya 3.5 connection; this integration never starts cleaning, resets the
box, changes safety settings, or switches its power.

Not affiliated with or endorsed by PetSafe, Radio Systems Corporation, Tuya,
Home Assistant, or HACS. Start with supervised observation, not safety-critical
or unattended physical-device automations.

## What works

- Native **Settings → Devices & services → Add integration** setup.
- Local setup using your device ID, local encryption key, and LAN address.
- Optional advanced Companion email/password bootstrap using a **privately
  supplied application profile**; the account password is not retained.
- Six local sensors: operating state, raw fault bitmap, clean-control state,
  cleaning-history value, daily usage count, and last successful observation.
- Shared polling, unavailable/recovery handling, options, reconfiguration, and
  redacted diagnostics.

Initial compatibility evidence is one SmartSpin using protocol 3.5 and the
Companion 1.2.9 application identity. Other models, firmware, regions, and
account types are not verified. Minimum targeted Home Assistant: **2026.7.4**.

## Important limitations

- **No reliable cleaning-completed event yet.** `finish_clean` may be a cached
  history value. Do not trigger a vacuum just because it appears after startup
  or a reconnect.
- **No mapped waste-bin-full sensor yet.** The hardware has drawer-full sensors,
  but the corresponding telemetry bit has not been verified. Raw fault `0`
  alone must not be presented as a confirmed bin-empty reading.
- Fault descriptions and the meaning of additional data points are not guessed.
- The usage counter can reset daily; it is not a lifetime counter or bin level.
- No controls, switches, services, vacuum commands, or safety-sensor overrides.
- Google/Apple sign-in, MFA, and CAPTCHA are not automated. Use local setup if
  advanced account bootstrap cannot authenticate.
- A LAN local key grants device access even though this integration is read-only.

## Install with HACS

This is a **custom repository**, not a claim of inclusion in HACS's default catalog.

1. In HACS, open its menu → **Custom repositories**.
2. Add `https://github.com/tristanwilson111/ha-petsafe-smartspin` with category **Integration**.
3. Download **PetSafe SmartSpin** and restart Home Assistant.
4. Add **PetSafe SmartSpin** under **Settings → Devices & services**.

Alternatively, copy only `custom_components/petsafe_smartspin/` to your HA
`config/custom_components/` directory and restart HA. Do not copy development
files, app packages, credentials, or a research folder into HA.

## Setup modes

### Local credentials — recommended when you already have the key

Enter the box's LAN address, device ID, and 16-character local encryption key.
The device ID is not the key. Setup performs a real status read before adding
the device; duplicate device IDs are rejected. Reserve its address in your
router if practical. Your Companion pairing stays intact.

### Companion account bootstrap — advanced

A public mobile-app signing identity is needed to speak the OEM account API.
**This repository deliberately does not publish extracted application signing
secrets, your account credentials, or a prefilled profile.** Consequently this
mode is not an out-of-the-box email/password-only setup.

Supply your own application-profile JSON privately, plus your Companion email,
its password, account region/country code, device ID, and LAN address. A local
static-analysis helper is documented in [Application profiles](docs/application-profile.md).
An Android phone is not required to inspect an APK, and the app is never executed.
Only obtain app packages you are entitled to use from a source you trust.

The bootstrap performs one bounded password submission and read-only retrieval
for the exact requested device. It does not migrate, re-pair, reset, register
another account, or publish device commands. The returned key must pass a local
status read. Only the device's local configuration is retained, not your
Companion password or application profile. If authentication requires user
interaction or the application identity is rejected, setup stops with an error.

See [Security](SECURITY.md) before collecting diagnostics or opening an issue.

## Sensors and automations

All sensors belong to one HA device. Entity IDs follow HA's naming conventions;
use the entity picker rather than assuming a fixed ID.

The last-seen timestamp means a valid fresh status response was received. It is
**not** the time of the last cat visit or cleaning completion. Sensor state
changes are ordinary HA updates, not certified completion events.

Roborock, other vacuums, notifications, and dashboards remain separate
integrations/automations. Observe real successful, interrupted, and faulted
cycles before building physical actions. No vacuum blueprint is shipped until
a fresh-completion signal is validated; a cached history-value trigger would be unsafe.

## Development

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/ruff check custom_components tests tools
```

Tests use synthetic fixtures and mocked device/account I/O; CI never contacts
real accounts or litter boxes. See [Contributing](CONTRIBUTING.md).

## Attribution and license

Project code is MIT licensed. Runtime dependencies and any vendored portions
retain their own notices; see [Third-party notices](THIRD_PARTY_NOTICES.md).
No APKs, vendor native libraries, or official brand assets are redistributed.
