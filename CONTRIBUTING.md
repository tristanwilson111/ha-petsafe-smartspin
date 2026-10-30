# Contributing

Start with an issue describing the exact model, firmware, app version, HA
version, and behavior. Do not upload identifying account/device information or
secrets. Diagnostics must be redacted; inspect them yourself before sharing.

Contributions should keep device operation read-only, preserve Companion pairing,
use synthetic fixtures, and test setup errors, recovery, unload, duplicate IDs,
and secret redaction. A new DP interpretation requires evidence from the actual
model/firmware; do not rename a guessed fault bit as bin-full.

Do not test by issuing factory resets, changing safety settings, forcing cleaning,
or contacting another person's appliance. Never submit real account credentials,
local keys, raw device/account exports, profiles, APKs, or disassembled binaries.

## Run the checks

Run these from the repository folder with Python 3.14:

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/ruff check custom_components tests tools conftest.py
```

On Windows, use `python` to create the environment and executables under
`.venv\\Scripts\\` instead of `.venv/bin/`.

Tests use synthetic fixtures and mocked account/device connections. Do not run
CI against a real account or litter box. GitHub Actions also runs hassfest and
HACS validation.

## Documentation

Keep the README focused on PetSafe installation, supported features, and the
shortest honest setup path. Put detailed troubleshooting and app-profile work
in linked guides. Do not describe private deployments as released features or
include household-specific automations. Clearly explain prerequisites that the
setup flow cannot discover for the user.

## License

The project is MIT licensed; include attribution for copied permissively licensed
code and do not submit third-party assets without redistribution rights.
