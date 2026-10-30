# Advanced: retrieve a local key with your Companion account

[Back to setup](setup.md)

**This is not an email-and-password-only login.** It also requires a private
application-profile file, the box's device ID, and its IP address. If you already
have a local key, skip this page and choose **Local credentials** in HA.

An application profile lets this integration make requests compatible with
Companion. It is not your password. The repository does not include one, and
you must keep your generated file private.

## 1. Gather what you need

On your own computer, not in the Home Assistant terminal:

- Install [Python 3.14](https://www.python.org/downloads/).
- Download this repository (**Code → Download ZIP**) and unzip it.
- Obtain a trusted **PetSafe Pet Companion Android APK** for package
  `net.petsafe.petsafelitterbox`. Version **1.2.9** was tested; other versions
  may not work. An iPhone user can do this too; an Android phone isn't needed.
- Have your Companion email/password, account country/region, device ID, and
  box IP address ready. See [connection details](setup.md#getting-your-connection-details).

**Obtaining a trusted APK is a manual prerequisite.** This project doesn't
provide an APK, an automatic downloader, or a device-ID discovery tool. Don't
use a modified/repackaged app or reset your box to follow this guide.

## 2. Prepare the files

Rename the APK to `companion.apk` and put it **next to the unzipped repository
folder**, not inside it. Open a terminal inside the repository folder.

Run:

```sh
python --version
python -m venv .profile-env
```

The version should be Python 3.14. If your system calls it `python3.14`, use that
instead of `python` for these two commands.

Install the helper's dependencies:

**Windows (PowerShell):**

```powershell
.\.profile-env\Scripts\python.exe -m pip install androguard==4.1.4 apksigtool==0.1.0
.\.profile-env\Scripts\python.exe tools/extract_app_profile.py ../companion.apk --output ../petsafe-app-profile.json
```

**macOS / Linux:**

```sh
.profile-env/bin/python -m pip install androguard==4.1.4 apksigtool==0.1.0
.profile-env/bin/python tools/extract_app_profile.py ../companion.apk --output ../petsafe-app-profile.json
```

Success prints **“Created private profile…”** and creates
`petsafe-app-profile.json` next to the repository. The helper checks the APK's
signature and reads its files; it does not run the app.

Only use an APK from a source you trust: a valid signature alone doesn't prove
who published it. If you independently know the publisher's certificate SHA256,
add `--expected-certificate YOUR_TRUSTED_SHA256` to the extraction command.

## 3. Use the profile in Home Assistant

1. Open `petsafe-app-profile.json` in a text editor and copy its entire contents.
2. In HA, open **Settings → Devices & services → Add integration → PetSafe
   SmartSpin → Companion account bootstrap**.
3. Enter your Companion email/password, country code, region, box IP address,
   and device ID. For a US/Canada account, country code is `1` and region `us`.
4. Paste the file contents into **Application profile** and submit.

Setup retrieves the key for that exact device and checks the local connection.
The integration keeps the local connection details, **not** your account
password or application profile. It doesn't change your Companion pairing.

## If it fails

- **Profile extraction failed:** check Python/dependencies, APK version and
  source, and file locations. The output must be outside the repository and
  must not already exist. Keep any existing profile safe before trying a new
  output filename.
- **Sign-in needs verification, MFA, CAPTCHA, or Apple/Google login:** this setup
  cannot complete those flows. Don't keep retrying; use a separately obtained
  local key or stop here.
- **Sign-in succeeds but the connection fails:** follow [Cannot connect](setup.md#cannot-connect).

Never post the profile, APK, password, or local key in an issue. Delete the
profile when finished if you don't need a private backup.
