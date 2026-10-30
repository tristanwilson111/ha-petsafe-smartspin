# Optional Companion cloud history

[Back to setup](setup.md)

Cloud history adds **last visit weight**, **last visit duration**, **last visit
time**, and recent visit records. It does not replace the local status sensors
or change how your box works in Companion.

## Enable it

1. Install version **0.2.0 or newer** and connect the box locally first.
2. Prepare your [private Companion application profile](application-profile.md).
3. Open **Settings → Devices & services → PetSafe SmartSpin**.
4. Open **Configure / Options**, enable **Companion cloud visit history**, and
   submit. The local polling interval only affects local sensors.
5. Enter your Companion email/password, country code, region, and profile JSON.
6. Read and accept the storage notice, then submit.

The integration checks the requested device and history access before saving.
Failed setup leaves your existing local configuration and cloud session intact.
No separate Tuya developer account, app migration, or device reset is needed.
The private app profile is still required; this isn't a password-only setup.

## What is saved?

**Only when you enable cloud history:** HA saves the authenticated cloud session,
private application profile, region, and installation identifier in the config
entry. These allow ongoing reads. **Your password is never saved.**

Treat the session and profile as secrets. HA's configuration and backups are not
promised to be encrypted. Protect both, and never attach a profile, session, raw
cloud response, or HA storage file to an issue. Local-key-only setup and the
one-time local-key bootstrap do not retain cloud credentials.

## How often does it contact the service?

One shared history request every **five minutes** updates all four cloud sensors.
It retrieves at most 20 recent records, not your complete account history.
Manual refreshes within that interval reuse the last successful result rather
than issuing another request. Initial sign-in also checks device access and
history; reloading the integration starts a new coordinator and initial read.

Transient errors cause progressively slower retries, capped at one hour.
Recognized expired sessions stop cloud requests until you renew them. No polling
request resubmits your password. We have not established an official PetSafe rate
limit; this cadence is a conservative project choice, not a vendor guarantee.

## Understanding the sensors

- **Last visit weight:** the weight reported for the newest visit, in kilograms
  (HA can convert units). It is not a live scale or a cat-identification feature.
- **Last visit duration:** the same visit's duration, stored in seconds.
- **Last visit:** when that visit was reported, shown in your HA timezone. Its
  `recent_visits` attribute contains up to 10 records with time, weight in kg,
  and duration in seconds.
- **Cloud last checked:** the last successful cloud read, a diagnostic timestamp.
  It updates even when no new visits exist.

No visits means no invented weight or duration. Failed cloud reads mark cloud
entities unavailable while local sensors continue. This is a recent-record list,
not a full-history browser or backfill into HA statistics. Home Assistant records
subsequent sensor changes according to your recorder settings.

## Renew an expired session

Open **Configure / Options**, leave cloud history enabled, select **Renew cloud
session**, and complete the sign-in form again. Your previous credentials are
not replaced unless the new setup verifies successfully. MFA/CAPTCHA/third-party
sign-in are not automated.

## Turn it off

Open **Configure / Options**, turn off cloud history, and submit. Cloud polling
stops and the cloud session/profile are removed from that config entry. Existing
HA recorder history and old backups are not erased. Local sensors remain enabled.

**Bin-full detection and cleaning-completed events are not included.**
