# Hardware setup: USR-W610 + CXA81

> **Status: draft, not yet performed.** Steps marked *verify* depend on information that neither Cambridge nor PUSR publishes in the documents we reviewed. Record what you find in [hardware-validation.md](hardware-validation.md).

## 1. Verify the cable before connecting anything
Neither the CXA81 manual nor protocol document AP36646/2 states the RS232 connector gender or pinout. Nor does the PUSR product page. Don't assume a straight-through cable is correct.

1. Note the connector gender on the **CXA81** rear panel and on the **USR-W610**.
2. Find each device's pinout. For the W610, check the PUSR user manual or the label on the unit. For the CXA81, ask Cambridge support if nothing is printed on the unit. Record which pin is TX, which is RX and which is GND on each device.
3. Rule: one device's TX must reach the other's RX, and GND must reach GND. If both devices transmit on the same pin number, you need a **null-modem (crossover)** cable or adapter. If they transmit on different pins (one DTE, one DCE), use a straight-through cable.
4. With both devices **unpowered**, use a multimeter in continuity mode to check the cable's pin mapping.
5. If you're unsure, a cheap DB9 null-modem adapter and a gender changer cover the other case. Trying the wrong wiring at RS232 levels is usually harmless, but don't rely on that.

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
