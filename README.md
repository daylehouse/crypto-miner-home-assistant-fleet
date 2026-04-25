# Bitaxe/NerdAxe Miner Home Assistant Integration

Home Assistant integration for monitoring and managing Bitaxe and NerdAxe ASIC miners running AxeOS.

Version 1.0.0 adds fleet monitoring, pool-aware fleet counts, per-miner overheat thresholds, and local brand assets for the config flow.

## Features

- Config flow setup for miner entries and a standalone fleet entry
- Support for Bitaxe and NerdAxe devices using the same AxeOS API
- Per-miner monitoring for hashrate, power, temperatures, uptime, shares, pool details, firmware, and more
- Restart button and pool configuration service
- Fleet-wide sensors for hashrate, power, efficiency, online/offline counts, and pool activity
- Per-miner overheat threshold slider from 55°C to 75°C
- Per-miner `Overheated` output sensor
- Fleet overheated miner count plus hostname list attribute for automations
- Local brand assets for Home Assistant config flow and integrations UI

## Installation

### HACS

1. Open HACS in Home Assistant.
2. Add this repository as a custom integration repository.
3. Install `Bitaxe/NerdAxe Miner`.
4. Restart Home Assistant.

### Manual

1. Copy this integration to `/config/custom_components/axeos/`.
2. Restart Home Assistant.
3. Go to Settings > Devices & Services > Add Integration.
4. Search for `Bitaxe/NerdAxe Miner`.

## Configuration

The config flow supports two entry types:

- Miner: Adds a single Bitaxe or NerdAxe device
- Fleet: Adds an aggregate fleet device with cross-miner sensors

Each miner should be added as its own config entry. After miner entries are configured, add one fleet entry to expose the fleet sensors.

## Entities

### Per-miner entities

- Sensors for hashrate, power, ASIC/VR temperature, fan metrics, shares, pool details, firmware, hostname, MAC, uptime, and diagnostics
- `Mining Active` read-only output sensor
- `Overheated` read-only output sensor
- `Overheat Alert Threshold` slider (`number`) with range 55-75°C
- Restart button
- Pool/profile selects where supported

### Fleet entities

- Fleet Hashrate
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

## Notes

- Poll interval is 30 seconds
- Communication is local HTTP on your network
- The integration tolerates transient timeouts during miner restarts/reboots

## Repository

- Documentation: https://github.com/daylehouse/crypto-miner-home-assistant-fleet
- Issues: https://github.com/daylehouse/crypto-miner-home-assistant-fleet/issues

## Reference

- Bitaxe API: https://osmu.wiki/bitaxe/api/
