# PetSafe SmartSpin for Home Assistant

See your **PetSafe ScoopFree SmartSpin** in Home Assistant while keeping it paired
with **PetSafe Pet Companion**.

This unofficial integration reads information from your litter box over your home
network. It does not start cleaning or change the box's settings.

> **Before you install:** you need the box's IP address, device ID, and local key.
> These are not your PetSafe email and password. If you don't have them, read
> [Getting your connection details](docs/setup.md#getting-your-connection-details)
> first. There is no simple email-and-password-only setup yet.

## What you'll see

- Operating status
- Visits today
- Raw fault code
- Cleaning-history value
- Clean-control state (reported information, not a button)
- Last successful connection check

**The connection-check timestamp updates whenever a poll succeeds. It is not the
last visit time.** Cleaning history can also keep its previous value.

The public integration does **not** currently include weight, visit duration,
visit history, or a bin-full indicator. The daily visit count is not a bin level.

## Install

You need Home Assistant **2026.7.4 or newer**, HACS, and a SmartSpin reachable on
your home network. Other PetSafe models are not confirmed to work.

1. Open **HACS → menu → Custom repositories**.
2. Add `https://github.com/tristanwilson111/ha-petsafe-smartspin`.
3. Choose **Integration**, then download **PetSafe SmartSpin**.
4. Restart Home Assistant.

No HACS? Use the [manual installation instructions](docs/setup.md#manual-installation).

## Connect your litter box

1. Open **Settings → Devices & services → Add integration**.
2. Search for **PetSafe SmartSpin**.
3. Choose **Local credentials**.
4. Enter your box's **IP address**, **device ID**, and **local key**.
5. Submit. The integration checks the connection before adding the device.

You do **not** need to reset the box, remove it from Companion, or change apps.

Need help finding those values or fixing a connection error? See the
[setup guide](docs/setup.md).

## Advanced setup

Already comfortable with Python and Android app files? The optional
[Companion account setup guide](docs/application-profile.md) explains how to
retrieve a local key using your existing account. It needs a private app profile
as well as your login; it is **not** the beginner setup path.

## Help and project information

- [Setup and troubleshooting](docs/setup.md)
- [Report a problem](https://github.com/tristanwilson111/ha-petsafe-smartspin/issues/new/choose) — never post passwords, local keys, or app profiles.
- [Security and privacy](SECURITY.md)
- [Development and contributing](CONTRIBUTING.md)
- [License and third-party notices](THIRD_PARTY_NOTICES.md)

Experimental software, tested with one SmartSpin and Companion 1.2.9. Not
affiliated with PetSafe, Radio Systems Corporation, Tuya, Home Assistant, or HACS.
Project code is [MIT licensed](LICENSE).
