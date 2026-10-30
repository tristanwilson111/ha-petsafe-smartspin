# PetSafe SmartSpin for Home Assistant

> **AI transparency:** This project is **100% AI-created**, with functionality
> validated by **Tristan Wilson** on his own PetSafe SmartSpin. It remains
> experimental; this is not independent certification or vendor endorsement.

See your **PetSafe ScoopFree SmartSpin** in Home Assistant while keeping it paired
with **PetSafe Pet Companion**.

**Local mode:** status and daily visits are read over your home network. The
integration never starts cleaning or changes the box's settings.

**Optional cloud history:** adds last-visit weight, visit duration, visit time,
and recent visits using your existing Companion account.

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
- Local connection checked (timestamp of a successful LAN poll)
- With optional cloud history: **last visit weight**, **last visit duration**,
  **last visit time**, and up to **10 recent visits** in the Last visit entity's
  attributes, plus a diagnostic cloud-check timestamp

**Connection-check timestamps are not visit times.** Cleaning history can also
keep its previous value. Weight and duration describe a reported visit, not a
live scale reading or automatic identification of a particular cat.

**Bin-full detection is not included.** The daily visit count is not a bin level.

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

## Optional: weight, duration, and recent visits

After connecting locally, open the integration's **Configure / Options** button,
turn on **Enable Companion cloud visit history**, and follow the sign-in form.
You need your own [private app profile](docs/application-profile.md) as well as
your Companion login. This is still an advanced setup, not password-only login.

Cloud history uses **one shared request every five minutes**, not a login on each
poll. It saves a sensitive cloud session and private app profile with your
explicit consent, **never your password**. Local mode works without it.
[Cloud setup, privacy, and session renewal](docs/cloud-history.md).

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
