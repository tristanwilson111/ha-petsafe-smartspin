# Setup and troubleshooting

## Getting your connection details

Choose the situation that matches yours:

- **I already have a local key:** use **Local credentials** in the integration.
- **I only have my Companion email and password:** those alone are not enough.
  The [advanced account guide](application-profile.md) can retrieve the key, but
  requires Python and a trusted Companion Android app file.
- **I want a setup with no command line or app-file work:** that isn't available
  yet. You haven't missed a setting. Don't reset or unpair your litter box to
  work around this limitation.

### IP address

This is the box's address on your home network, such as `192.168.1.50`.

1. Open your router's app or administration page.
2. Find **Connected devices**, **Clients**, or **DHCP leases**.
3. Identify the litter box. If the name is unclear, compare its Wi-Fi/MAC address
   with the device information in Companion, if your app version shows it.
4. Copy the IP address. Don't use the router's own address or a website address.

A router address reservation keeps this value from changing later.

### Device ID

This is Tuya's identifier for the box, not its IP address, MAC address, serial
number, or local key. Check the device-information screen in your app; available
fields vary by app version. If the required ID is not shown, the public setup
flow cannot discover it for you. You'll need an existing trusted device export
or other independently obtained device details before proceeding.

### Local key

This is a 16-character secret used to connect to the box locally. **It is not
your Companion password**, a Wi-Fi password, or a pairing code.

If you already have it from a trusted device export or previous local setup,
enter it directly. Otherwise, the optional [advanced guide](application-profile.md)
uses a private Companion app profile to retrieve it for a device ID you already
know. This project does not currently provide a beginner-friendly key-discovery
wizard or device-ID lookup.

Keep the key private. Don't post it in a support request.

## Install with HACS

1. Open **HACS → menu → Custom repositories**.
2. Paste `https://github.com/tristanwilson111/ha-petsafe-smartspin`.
3. Select **Integration** as the category and add it.
4. Find **PetSafe SmartSpin** in HACS and download it.
5. Restart Home Assistant.

This is a HACS custom repository, not a default-catalog integration.

## Manual installation

1. Download and unzip the repository from GitHub (**Code → Download ZIP**).
2. Find `custom_components/petsafe_smartspin` in the downloaded folder.
3. Copy the entire `petsafe_smartspin` folder into your Home Assistant
   configuration's `custom_components` folder. Create `custom_components` if it
   doesn't exist.
4. Check that the result includes
   `/config/custom_components/petsafe_smartspin/manifest.json`.
5. Restart Home Assistant.

Copy only the integration folder, not the whole repository. No YAML setup is
required. Accessing `/config` depends on your installation; use your existing
file editor, file share, or administrator access.

## Add the integration

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **PetSafe SmartSpin** and choose **Local credentials**.
3. Enter the IP address, device ID, and local key collected above.
4. Submit. If the connection check succeeds, the device and sensors are added.

Keep your existing Companion pairing. No reset or app migration is needed.

## Common problems

### “Cannot connect”

- Confirm that the litter box is powered on and online in Companion.
- Recheck its current IP address in your router.
- Confirm that Home Assistant can reach the box's network. Guest Wi-Fi or
  client isolation can prevent local connections even when Companion works.
- Recheck the device ID and local key; they must belong to the same box.

### The integration doesn't appear in “Add integration”

Confirm that you restarted Home Assistant after installation. For a manual
install, check the exact folder path above. Then refresh the browser/app.

### “Already configured”

This device ID already exists in Home Assistant. Open its existing entry in
**Settings → Devices & services** rather than adding another one.

### The box's IP address or key changed

Open **Settings → Devices & services → PetSafe SmartSpin → entry menu →
Reconfigure**. Enter the current address and key.

### “Last seen” keeps changing

That's expected: it records each successful connection check, not a cat visit.
The cleaning-history sensor can retain an old value, too; it isn't a new-event
notification.

### Some app features are missing

The [README](../README.md#what-youll-see) lists the local sensors. Weight, duration,
visit time, and recent visits need [optional cloud history](cloud-history.md),
which is disabled by default. Bin-full detection and device controls are not
included.

## Ask for help safely

Include your model, app version, Home Assistant version, and the exact error
message. Review diagnostics before sharing them. Never include your password,
local key, application-profile JSON, or raw device/account exports.
