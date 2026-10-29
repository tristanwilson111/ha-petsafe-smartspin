# Application profiles (advanced)

PetSafe Pet Companion is a Tuya-powered application. Talking to its account API
requires the application's own signing identity. Those values live inside the
distributed Android package; they are **not** your account password, and they are
**not** bundled with this repository.

This page explains how to produce a profile **privately** from an APK you are
entitled to use. It does not grant authorization, does not imply vendor
endorsement, and does not guarantee future API compatibility. Keep the result
private; never attach it to an issue, commit it, or paste it into chat.

## Requirements

- Python 3.14 with the optional analysis dependencies:
  `pip install androguard==4.1.4 apksigtool==0.1.0`
- An APK of **PetSafe Pet Companion** (`net.petsafe.petsafelitterbox`) from a
  source you trust, matching a version you use. This project's authors verified
  1.2.9; others may differ.

Prefer the app package distributed by PetSafe/Radio Systems for your region.
Avoid unofficial repackaged builds: they may be modified, and their signing
certificate will not match the vendor's.

## Generate the profile

```sh
python tools/extract_app_profile.py \
  ~/Downloads/companion.apk \
  --output ~/petsafe-app-profile.json \
  --expected-certificate <independently-trusted-sha256-fingerprint>
```

The helper:

1. Verifies the APK's v2/v3 signature.
2. Confirms the package name and a single consistent signer certificate.
3. Reads production application constants from the DEX **without executing any
   application or vendor native code**.
4. Decodes the signing resource using rational interpolation.
5. Refuses to write inside this repository and writes the file mode `0600`.

Omit `--expected-certificate` only if you have another way to corroborate the
publisher. A self-consistent signature alone does not prove publisher identity.

## Using it

In **Settings → Devices & services → Add integration → PetSafe SmartSpin →
Companion account bootstrap**, paste the profile JSON into the advanced field,
then supply:

- your Companion email address,
- its password,
- the account region and country code,
- the box's device ID, and
- the box's LAN address.

Setup performs one bounded password submission and read-only retrieval for that
exact device, then a local status read. The password and profile are not kept in
the configuration entry. If the service rejects the application identity or
requires interactive sign-in, use **Local credentials** instead.

## Removing the profile

Delete the JSON file when finished. The account password is not written to
disk by this integration, but your password manager and browser history may
still hold it.
