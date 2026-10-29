# Security policy

## Scope

This is experimental, unofficial software. Report suspected credential leakage
privately using GitHub's private vulnerability reporting when available. Do not
paste logs, local keys, passwords, application profiles, invitation links,
OAuth tokens, raw cloud responses, APK dumps, or your Home Assistant `.storage`
files into public issues.

## Credential handling

- Local keys permit access to the appliance; treat them as secrets even though
  this integration implements no controls.
- HA config-entry data is stored on disk, not promised to be encrypted. Protect
  the HA configuration directory and its backups.
- Companion bootstrap credentials and signing profiles are used in memory and
  are not intentionally retained in the config entry or logs.
- SDK errors are translated to fixed messages. Integration diagnostics must not
  include host, device ID, keys, account identifiers, profiles, or raw responses.
- No live account/device tests run in CI. All test credentials are synthetic.
- No downloaded application code or vendor native library is executed by setup.

## Physical safety

Do not disable or override the box's safety sensors, infer successful cleaning
from an old `finish_clean` snapshot, or force an automatic vacuum run on restart.
A raw fault value of zero is not a substitute for a physical safety check or a
verified bin-full signal. Preserve manufacturer safeguards and normal operation.

## App profiles

Application signing material embedded in a distributed mobile application is
not a user's account password, but publishing it still needs deliberate review.
This project accepts a profile privately and does not bundle extracted PetSafe
identity material. Keep generated files outside the repository and never attach
them to issues. The helper does not authorize account access, prove vendor
endorsement, or guarantee future API compatibility.
