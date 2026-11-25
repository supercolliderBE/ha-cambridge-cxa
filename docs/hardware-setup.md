# Hardware setup: USR-W610 + CXA81

> **Status: draft, not yet performed.** Steps marked *verify* depend on information that neither Cambridge nor PUSR publishes in the documents we reviewed. Record what you find in [hardware-validation.md](hardware-validation.md).

## 1. Verify the cable before connecting anything

### What the sources say (researched 2026-11-25)
| Device | Connector | Pin assignment | Source and confidence |
|---|---|---|---|
| USR-W610 | **DB9 male** | Not published (no pin table in the manual) | PUSR *USR-W610 User Manual* (pusr.com, PDF dated 2024-06-14), spec table and hardware-interface photo. **Manufacturer.** |
| CXA81 | **DB9 female** | Not published | Audio Appraisal review: RS-232C "unusually on a female DB9 connector". **Secondary source.** Cambridge's manual and protocol PDF don't say. |
| Cambridge convention | Equipment is female; the controller (a "DTE", such as a PC) is male; use a **straight-through** cable | — | Cambridge FAQ for its CXR120/CXR200 receivers. **Manufacturer, but for a different product.** |

**Working hypothesis (unverified):** the W610 behaves like a PC-style male DTE port (transmits on pin 3, receives on pin 2), and the CXA81 follows Cambridge's female, straight-through convention (transmits on pin 2, receives on pin 3). In that case a **DB9 male-to-female straight-through** cable works: the female end goes on the W610, the male end on the CXA81. That is exactly the type of the candidate StarTech MXT10050CMBK. Confirm it with the measurement below before relying on it.

### Find the transmit pin with a multimeter (no documentation needed)
An idle RS232 transmit pin sits at a **negative voltage, typically −5 to −12 V**, relative to ground. A receive pin sits near 0 V.
1. Power on **one** device, with **nothing** plugged into its serial port.
2. Put the multimeter on DC volts. Black probe on **pin 5 (GND)**. Red probe on pin 2, then on pin 3.
3. The pin that reads clearly negative is that device's **TX**; the other is RX. Pin numbers are printed in tiny digits on most DB9 connectors.
4. Repeat for the other device.

| W610 TX on | CXA81 TX on | Cable needed |
|---|---|---|
| pin 3 | pin 2 | **Straight-through** male-to-female (the expected case) |
| pin 2 | pin 3 | Straight-through also works (both ends simply mirrored) |
| same pin number on both | same | **Null-modem**: swaps pins 2 and 3 |

### If they don't match: options
- **Inline null-modem adapter** (DB9 male-to-female, a few euros). Plug it between the straight-through cable and one device. Easiest, and fully reversible.
- **Null-modem cable** of the right genders instead of the straight-through cable.
- **Gender changer** (male-male or female-female) if the cable's ends don't fit. It changes only gender, not wiring, so combine it with a null-modem adapter if pins 2 and 3 also need swapping.
- **Three-wire custom cable**: only pins 2, 3 and 5 are needed (TX, RX and ground; no flow control). Wire TX to RX, RX to TX, and GND to GND.
- **Quick trial without a multimeter:** connect a straight-through cable and run the probe. Exit code `1` (bridge reachable, amplifier silent) usually means TX and RX are swapped; add a null-modem adapter and try again. RS232 transmitters are designed to survive a short to another driver, so a wrong guess is normally harmless. Still, connect cables with both devices powered off.

The W610's hardware flow control (RTS/CTS) must be **off**: the CXA81 protocol uses only TX, RX and GND.

## 2. Bridge provisioning (browser only)
Follow the PUSR instructions for your firmware: <https://www.pusr.com/support/faq/75.html>. Default SSID, IP and credentials vary by firmware, so take them from the label or manual, not from this document.

- Wi-Fi: **STA (client)** mode on your home network. Reserve its IP address in the router.
- Serial: **RS232, 9600 baud, 8 data bits, no parity, 1 stop bit** (documented by Cambridge). Flow control: none (*verify* the option exists and is off).
- Socket: **TCP server**, transparent transmission. Pick a port (8899 is common but *not guaranteed* as the default) and record it.
- **Disable** registration packets, heartbeat packets, Modbus and MQTT modes. Any injected bytes corrupt the serial stream. The probe shows anything the bridge sends when a client connects.
- Security: set a strong admin password. Never expose the bridge or its TCP port to the internet. Raw TCP has no authentication or encryption.
- Only one TCP client should use the bridge. The W610 accepts several, and extra clients confuse reply matching.

## 3. First contact (read-only)
From any machine with Python 3.11+ on the same LAN (no Home Assistant needed):

```sh
python tools/probe.py <bridge-ip> <port> --group-format both --listen 30 --jsonl first-contact.jsonl
```

During the listen window, press the remote's mute and source buttons. Exit codes:
- `0`: frames received.
- `1`: TCP connects but the amplifier is silent. Check the cable, serial settings and amplifier power.
- `2`: the bridge is unreachable.

The JSONL transcript is git-ignored. Redact IP addresses before sharing it.

Then confirm that the HA container itself can reach the bridge. The container may have different routing from your laptop.

## 4. Writes (opt-in, at a safe volume)
Turn the amplifier's volume down and play no music. Then:

```sh
python tools/probe.py <ip> <port> --allow-writes --set-mute on
python tools/probe.py <ip> <port> --allow-writes --set-mute off
python tools/probe.py <ip> <port> --allow-writes --set-source 20   # A1 Balanced
```

## 5. Add to Home Assistant
Once the probe works, install the integration as described in the [README](../README.md#installation-manual-for-testing). Then add it under **Settings → Devices & services** with the same IP address and port. If setup reports "Could not reach the bridge" but the probe works from your laptop, check that the HA container can reach the bridge (checklist item H16).

Only one TCP client should use the bridge: close any running probe before adding the integration.
