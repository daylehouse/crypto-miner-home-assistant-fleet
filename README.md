# ₿ CRYPTO MINER FLEET MONITOR

```text
  ██████╗██████╗ ██╗   ██╗██████╗ ████████╗ ██████╗
 ██╔════╝██╔══██╗╚██╗ ██╔╝██╔══██╗╚══██╔══╝██╔═══██╗
 ██║     ██████╔╝ ╚████╔╝ ██████╔╝   ██║   ██║   ██║
 ██║     ██╔══██╗  ╚██╔╝  ██╔═══╝    ██║   ██║   ██║
 ╚██████╗██║  ██║   ██║   ██║        ██║   ╚██████╔╝
  ╚═════╝╚═╝  ╚═╝   ╚═╝   ╚═╝        ╚═╝    ╚═════╝

 ███╗   ███╗ ██████╗ ███╗   ██╗██╗████████╗ ██████╗ ██████╗
 ████╗ ████║██╔═══██╗████╗  ██║██║╚══██╔══╝██╔═══██╗██╔══██╗
 ██╔████╔██║██║   ██║██╔██╗ ██║██║   ██║   ██║   ██║██████╔╝
 ██║╚██╔╝██║██║   ██║██║╚██╗██║██║   ██║   ██║   ██║██╔══██╗
 ██║ ╚═╝ ██║╚██████╔╝██║ ╚████║██║   ██║   ╚██████╔╝██║  ██║
 ╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝

      TRACK YOUR MINERS  >>>  READY
```

> **PLAYER ONE — YOUR MINERS ARE NOW IN HOME ASSISTANT.**

An arcade-themed Home Assistant integration for monitoring and managing Bitaxe, NerdAxe, Avalon, and Goldshell ASIC miners. Crypto Miner Fleet Monitor is the telemetry backend for the companion [Bitcoin Miner Card](https://github.com/daylehouse/bitcoin-miner-card), exposing the live stats, thermal data, fan speed, pool details, thresholds, and fleet rollups the card expects.

Version 1.2.0 adds Goldshell Byte support with dual-algorithm ALEO and LTC monitoring, controls, and fleet aggregation alongside the existing Bitaxe, NerdAxe, and Avalon support.

<img src="https://raw.githubusercontent.com/daylehouse/bitcoin-miner-card/refs/heads/GA-Branch/concept.png" alt="Bitcoin Miner Card concept preview" width="560">

---

## 🕹️ FEATURES — POWER-UPS ONLINE

| Feature | Status |
|---|---|
| Config flow setup for miners plus one shared fleet entry | ✅ ACTIVE |
| Bitaxe, NerdAxe, Avalon, and Goldshell support | ✅ ACTIVE |
| Per-miner sensors for hashrate, power, temperature, uptime, shares, pool data, firmware, and diagnostics | ✅ ACTIVE |
| Restart button and supported control entities | ✅ ACTIVE |
| Fleet rollups for hashrate, power, efficiency, online state, pool activity, and overheating | ✅ ACTIVE |
| Overheat threshold sliders per miner or per Goldshell board | ✅ ACTIVE |
| Overheated status outputs for miner-level automation | ✅ ACTIVE |
| Goldshell Byte ALEO and LTC board separation | ✅ ACTIVE |
| Goldshell idle mode switch and power mode select | ✅ ACTIVE |
| Companion-ready entity model for Bitcoin Miner Card dashboards | ✅ ACTIVE |
| One-touch pool selection for up to three predefined pools | ✅ ACTIVE |

---

## 🚀 INSTALLATION — INSERT COIN

### HACS *(recommended — fastest route to the control room)*

1. Open HACS in Home Assistant.
2. Add this repository as a custom integration repository.
3. Install **Crypto Miner Fleet Monitor**.
4. Restart Home Assistant.

### Manual *(old-school mode)*

1. Copy this integration to `/config/custom_components/axeos/`.
2. Restart Home Assistant.
3. Open **Settings** → **Devices & Services** → **Add Integration**.
4. Search for **Crypto Miner Fleet Monitor**.

---

## ⚙️ CONFIGURATION — CHOOSE YOUR FIGHTER

This integration supports two config entry types:

| Entry Type | Description |
|---|---|
| `Miner` | Adds one Bitaxe, NerdAxe, Avalon, or Goldshell device |
| `Fleet` | Adds a shared aggregate device with cross-miner sensors |

Add each miner as its own config entry. Once your miners are online, add one fleet entry for the aggregate sensors.

### Supported miner types

| Miner | Notes |
|---|---|
| Bitaxe | Uses the AxeOS API |
| NerdAxe | Uses the same API structure as Bitaxe |
| Avalon | Uses CGMiner-compatible API on port `4028` |
| Goldshell Byte | Uses current firmware `/mcb` endpoints |

---

## 📡 ENTITIES — LIVE TELEMETRY FEED

### Per-miner entities

| Entity Group | What you get |
|---|---|
| Core metrics | Hashrate, power, uptime, model, firmware, hostname, IPv4, MAC |
| Thermal metrics | ASIC, VR, exhaust, board temperatures, overheat outputs, threshold sliders |
| Cooling metrics | Fan speed and fan RPM where exposed |
| Pool metrics | URL, port, user, active state, difficulty, accepted/rejected shares |
| Controls | Restart button, pool/profile selects where supported |
| Diagnostics | Status and firmware-dependent health metrics |

### Goldshell Byte notes

| Goldshell feature | Details |
|---|---|
| Dual board telemetry | Separate ALEO and LTC sensors |
| Thermal thresholds | Separate ALEO and LTC overheat sliders |
| Fan telemetry | Separate fan RPM and percentage-based fan speed sensors |
| Pool handling | Monitoring only, no writable pool service |
| Device controls | Idle mode switch and shared power mode select |

### Fleet entities

| Fleet sensor | Description |
|---|---|
| Fleet Hashrate | Total fleet hashrate |
| Fleet ALEO Hashrate | Total ALEO hashrate across Goldshell devices |
| Fleet LTC Hashrate | Total LTC hashrate across Goldshell devices |
| Fleet Power | Total fleet power draw |
| Fleet Energy Efficiency | Aggregate efficiency metric |
| Fleet Hashrate per Watt | Fleet performance ratio |
| Fleet Miners Configured | Number of miners added |
| Fleet Miners Online | Online miner count |
| Fleet Miners Offline | Offline miner count |
| Fleet Miners Online Percentage | Online rate |
| Fleet Miners Unknown Pool | Miner count with unmatched pool data |
| Fleet Miners Overheated | Count of miners above configured thresholds |

The fleet overheated sensor also exposes the `overheated_miner_hostnames` attribute so automations can target exactly which devices are too hot.

---

## 🎛️ SERVICES — CONTROL PANEL

### `axeos.set_pool`

Updates the active pool settings on a miner.

This service is intended for miner types that support writable pool configuration. Goldshell pool entities are read-only and are not controlled through this service.

```yaml
service: axeos.set_pool
data:
  device_id: "192.168.3.199"
  stratum_url: "stratum+tcp://public-pool.io"
  stratum_port: 21496
  stratum_user: "wallet.worker"
  stratum_password: "x"
```

---

## 🧠 AUTOMATIONS — IF HEAT, THEN REACT

Use the fleet overheat attribute in templates and automations:

```yaml
{{ state_attr('sensor.axeos_fleet_fleet_miners_overheated', 'overheated_miner_hostnames') }}
```

This returns a list of miner hostnames currently above their configured overheat threshold.

The entity namespace remains `axeos` to avoid breaking existing dashboards and automations.

---

## 🖥️ COMPANION CARD — PERFECT COMBO MOVE

This integration is designed to pair with the [Bitcoin Miner Card](https://github.com/daylehouse/bitcoin-miner-card).

For standard miners like Bitaxe, NerdAxe, and Avalon, the card-ready entity suffixes are:

| Card input | Entity suffix |
|---|---|
| Title / miner label | `hostname` or device name |
| Miner IP | `ipv4_address` |
| Hashrate | `hashrate` |
| Temperature | `temp_asic` |
| Overheat state | `overheated` |
| Fan speed | `fan_speed` |
| Pool URL | `pool_url` |
| Pool port | `pool_port` |
| Accepted shares | `shares_accepted` |
| Rejected shares | `shares_rejected` |
| Power | `power` |
| Model | `asic_model` or `device_model` |

For Goldshell Byte, use the algorithm-specific sensors instead:

| Goldshell card input | Entity suffix |
|---|---|
| ALEO hashrate | `aleo_hashrate` |
| LTC hashrate | `ltc_hashrate` |
| ALEO temperature | `aleo_temp_1` |
| LTC temperature | `ltc_temp_1` |
| ALEO fan speed | `aleo_fan_speed` |
| LTC fan speed | `ltc_fan_speed` |

If you want the card and integration to feel like one system, this is the backend piece that makes that work.

---

## 🛠️ NOTES — KNOW BEFORE YOU DEPLOY

| Note | Value |
|---|---|
| Poll interval | `30` seconds |
| Network mode | Local HTTP on your LAN |
| Restart handling | Tolerates transient timeouts during reboots |
| Goldshell auth | Supported in config flow when firmware requires it |
| Goldshell read access | Current Byte firmware may expose status locally without login |

---

## 🔗 LINKS — WARP GATE

- [Code](https://github.com/daylehouse/crypto-miner-home-assistant-fleet)
- [Issues](https://github.com/daylehouse/crypto-miner-home-assistant-fleet/issues)
- [Bitcoin Miner Card](https://github.com/daylehouse/bitcoin-miner-card)
- [Bitaxe API Reference](https://osmu.wiki/bitaxe/api/)

---

*GAME OVER? Not here. The fleet stays online.*

## ₿ SUPPORT THE DEV — INSERT COIN FOR REAL

If this intergration saved you time, made your dashboard look sick, or your miner just hit a new all-time best difficulty — buy the dev a satoshi.

**Bitcoin:** `bc1qqa5weng9wh682vcas6a8c8jqw43t4hnt8f7ks9`

**Bitcoin Cash:** `qzcv0zwwguz0z9j0v8nd8yp4rxuqpadtegmr09tmer`

```
  ⣿⣿⣿⣿⣿ THANK YOU FOR PLAYING ⣿⣿⣿⣿⣿
