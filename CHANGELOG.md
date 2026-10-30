# Changelog

## 0.2.1

- Fix local, reconfiguration, and Companion setup forms failing to render in
  Home Assistant's HTTP API. Keep strict connection validation after submission.
- Add regression checks using the same schema serializer as HA's flow views.

## 0.2.0

- Add optional Companion cloud history: last-visit weight, duration, visit time,
  up to ten recent visits as entity attributes, and a diagnostic cloud-check time.
- Keep cloud history disabled by default. Enable it in the integration options
  with explicit consent to save a sensitive session and private app profile.
  Passwords are never retained.
- Share one cloud history read every five minutes, reuse results during the
  refresh cooldown, back off on transient failures, and stop requests on
  recognized authentication expiry until the session is renewed.
- Allow cloud-session renewal and removal without replacing the local setup.
- Keep cloud failures independent from local sensor availability.
- Rename the local poll timestamp to “Local connection checked” without changing
  its unique ID. It is not a visit timestamp.
- Add an AI-creation disclosure and maintainer-validation notice to the README.
- Bin-full detection, cleaning-completed events, and appliance controls remain
  unsupported.

## 0.1.0

- Initial experimental local read-only integration with six sensors, native UI
  setup, optional one-time Companion local-key bootstrap, and HACS packaging.
