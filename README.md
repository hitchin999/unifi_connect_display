# UniFi Connect Display Integration for Home Assistant

**UniFi Connect Display** brings Ubiquiti’s UniFi Connect screens and “Cast” endpoints into Home Assistant. Control power, playback, volume, brightness (on supported models), and even load arbitrary URLs — all via the native Home Assistant UI.

---

## Features

* **Media Player**

  * Turn on/off
  * Play/Pause/Stop
  * Volume slider (maps to display brightness on supported models)
  * Select between “Cast” and “Website” inputs
  * Play a custom URL on your display via the Website source

* **Switch**

  * Dedicated power on/off toggle

* **Sensor**

  * Reports current power state, brightness, volume

* **Number**

  * Brightness slider (for UC-Display models)
  * Volume slider (for any model with audio)

* **Text**

  * Single‐line URL input to drive `load_website`

* **Button**

  * One button per action (reboot, locate, rotate, etc.)

---

## Supported Models

| Model            | Power | Play/Stop | Volume | Brightness | Load Website | Reboot | Locate | Rotate | … |
| ---------------- | :---: | :-------: | :----: | :--------: | :----------: | :----: | :----: | :----: | - |
| UC-Display-7     |   ✓   |     ✓     |    ✓   |      ✓     |       ✓      |    ✓   |    ✓   |    ✓   |   |
| UC-Display-13    |   ✓   |     ✓     |    ✓   |      ✓     |       ✓      |    ✓   |    ✓   |    ✓   |   |
| UC-Display-21    |   ✓   |     ✓     |    ✓   |      ✓     |       ✓      |    ✓   |    ✓   |    ✓   |   |
| UC-Display-27    |   ✓   |     ✓     |    ✓   |      ✓     |       ✓      |    ✓   |    ✓   |    ✓   |   |
| UC-Display-SE-7  |   ✓   |     ✓     |    ✓   |      ✓     |       ✓      |    ✓   |    ✓   |    ✓   |   |
| UC-Display-SE-13 |   ✓   |     ✓     |    ✓   |      ✓     |       ✓      |    ✓   |    ✓   |    ✓   |   |
| UC-Display-SE-21 |   ✓   |     ✓     |    ✓   |      ✓     |       ✓      |    ✓   |    ✓   |    ✓   |   |
| UC-Display-SE-27 |   ✓   |     ✓     |    ✓   |      ✓     |       ✓      |    ✓   |    ✓   |    ✓   |   |
| UC-Cast          |   ✓   |     ✓     |    ✓   |      —     |       —      |    ✓   |    ✓   |    ✓   |   |
| **UC-Cast-Pro**  |   ✓   |     ✓     |    ✓   |      —     |       —      |    ✓   |    ✓   |    ✓   |   |
| UC-EV-Station    |   —   |     —     |    —   |      ✓     |       —      |    ✓   |    ✓   |    —   | ✓ |

> Models marked “—” simply don’t expose that action in UniFi’s Connect API.

---

## Installation

1. **Copy** this folder into your Home Assistant `custom_components/unifi_connect_display/`.
2. Restart Home  Assistant.
3. In **Settings → Devices & Services** click **Add Integration**, search for **UniFi Connect Display**, and follow the prompts.

You will need your UniFi Connect controller’s **host**, **username**, **password**, and (optionally) **site**.

---

## Configuration Options

All via the UI config flow:

| Field        | Description                             |
| ------------ | --------------------------------------- |
| **Host**     | `<your_controller_address>:8443`        |
| **Username** | Your UniFi Connect account user         |
| **Password** | Your UniFi Connect account pass         |
| **Site**     | (Optional) site name in your controller |

---

## Usage

* **Media Player** cards will appear for all devices with `play`+`volume`.

  * Tap the Power icon to turn on.
  * Once ON, you’ll get ▶ ▌▌ ◼ and a volume (brightness) slider.
  * Choose your source (Cast vs Website) and, if Website, send a URL from the **Text** entity.

* **Switch** entities let you toggle power directly in Lovelace.

* **Sensor** shows “ON”/“OFF” and exposes brightness & volume as attributes.

* **Number** entities allow you to set volume and brightness even when the media card is collapsed.

* **Text** entity (“URL”) lets you type any website and send it to the display.

* **Buttons** for every other action: Reboot, Locate, Rotate, Sleep, Firmware Update, etc.

---

## Troubleshooting

* If you only see a power button in the media card, the player is still “OFF.” Tap it once to wake the display, then the full controls will appear.
* Cast-Pro does not support brightness—no slider will show for it.
* Make sure your `ACTION_MAPS` entries match the exact model strings (including `-Pro`).

---

## Contributing

1. Fork on GitHub
2. Add new model → UUID mappings in `const.py`
3. Update or add platform logic as needed
4. Send a PR

---

Enjoy seamless control of your UniFi Connect Displays right from Home Assistant!
