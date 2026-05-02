# Bitaxe/NerdAxe/Avalon/Goldshell Miner Home Assistant Integration

Home Assistant integration for monitoring and managing Bitaxe, NerdAxe, Avalon, and Goldshell ASIC miners.

Version 1.2.0 adds Goldshell Byte support, including dual-algorithm ALEO/LTC monitoring, device controls, and fleet rollups alongside the existing Bitaxe, NerdAxe, and Avalon support.

## Features

- Config flow setup for miner entries and a standalone fleet entry
- Support for Bitaxe, NerdAxe, Avalon, and Goldshell devices
- Per-miner monitoring for hashrate, power, temperatures, uptime, shares, pool details, firmware, and more
- Restart button and pool configuration service where supported
- Fleet-wide sensors for hashrate, power, efficiency, online/offline counts, and pool activity
- Per-miner overheat threshold sliders from 55°C to 75°C
- Per-miner `Overheated` output sensors
- Fleet overheated miner count plus hostname list attribute for automations
- Local brand assets for Home Assistant config flow and integrations UI
- Goldshell-specific idle mode switch and shared power mode select
- Goldshell read-only pool monitoring for both ALEO and LTC boards

## Installation

### HACS

1. Open HACS in Home Assistant.
2. Add this repository as a custom integration repository.
3. Install `Bitaxe/NerdAxe/Avalon/Goldshell Miner`.
4. Restart Home Assistant.

### Manual

1. Copy this integration to `/config/custom_components/axeos/`.
2. Restart Home Assistant.
3. Go to Settings > Devices & Services > Add Integration.
4. Search for `Bitaxe/NerdAxe/Avalon/Goldshell Miner`.

## Configuration

The config flow supports two entry types:

- Miner: Adds a single Bitaxe, NerdAxe, Avalon, or Goldshell device
- Fleet: Adds an aggregate fleet device with cross-miner sensors

Each miner should be added as its own config entry. After miner entries are configured, add one fleet entry to expose the fleet sensors.

## Entities

### Per-miner entities

- Sensors for hashrate, power, ASIC/board temperature, fan metrics, shares, pool details, firmware, hostname, MAC, uptime, IPv4 address, and diagnostics
- `Mining Active` read-only output sensor
- `Overheated` read-only output sensor
- `Overheat Alert Threshold` slider (`number`) with range 55-75°C
- Restart button
- Pool/profile selects where supported

Goldshell notes:

- Goldshell Byte exposes separate ALEO and LTC sensors, including hashrate, power, temperatures, shares, reject rate, hardware error rate, and pool monitoring
- Goldshell does not use the preset pool selection flow used by Bitaxe and similar miners
- Goldshell includes an idle mode switch and a shared power mode select with `Paused`, `High Power`, and `Standard Power`
- Goldshell overheat thresholds are configured separately for ALEO and LTC boards

### Fleet entities

- Fleet Hashrate
- Fleet ALEO Hashrate
- Fleet LTC Hashrate
- Fleet Power
- Fleet Energy Efficiency
- Fleet Hashrate per Watt
- Fleet Miners Configured
- Fleet Miners Online
- Fleet Miners Offline
- Fleet Miners Online Percentage
- Fleet Miners Unknown Pool
- Fleet Miners Overheated
- Per-pool active miner count sensors for configured pools

The fleet overheated sensor also exposes an attribute:

- `overheated_miner_hostnames`: list of hostnames currently above each miner's configured threshold

## Services

### `axeos.set_pool`

Update the active pool settings on a miner.

This service is intended for miner types that support writable pool configuration. Goldshell pool entities are monitoring-only and are not controlled through this service.

Example:

```yaml
service: axeos.set_pool
data:
  device_id: "192.168.3.199"
  stratum_url: "stratum+tcp://public-pool.io"
  stratum_port: 21496
  stratum_user: "wallet.worker"
  stratum_password: "x"
```

## Automation Example

You can use the fleet overheat sensor attribute in automations:

```yaml
{{ state_attr('sensor.axeos_fleet_fleet_miners_overheated', 'overheated_miner_hostnames') }}
```

This returns a list of miner hostnames currently above their configured overheat threshold.

## Supported Miners

- Bitaxe models supported by the AxeOS API
- NerdAxe models using the same API structure
- Avalon models exposing CGMiner-compatible API on port 4028 (for example Nano series)
- Goldshell Byte models exposing the `/mcb` API used by current firmware

## Notes

- Poll interval is 30 seconds
- Communication is local HTTP on your network
- The integration tolerates transient timeouts during miner restarts/reboots
- Goldshell authentication fields are available in config flow for firmware that requires them, but current Byte firmware may allow local read access to status endpoints without login

## Repository

- Documentation: https://github.com/daylehouse/crypto-miner-home-assistant-fleet
- Issues: https://github.com/daylehouse/crypto-miner-home-assistant-fleet/issues

## Reference

- Bitaxe API: https://osmu.wiki/bitaxe/api/
- Goldshell support in this integration is based on the local `/mcb` HTTP endpoints exposed by Goldshell Byte firmware
