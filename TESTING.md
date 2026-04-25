# Installation & Testing Guide for Bitaxe/NerdAxe Integration

## Pre-Flight Checklist

- [ ] Home Assistant 2024.1.0 or later installed
- [ ] Bitaxe/NerdAxe miner powered on and accessible at 192.168.3.199
- [ ] Home Assistant server on same network as miner
- [ ] Integration files copied to `/config/custom_components/axeos/`

## Step 1: Copy Integration Files

All integration files are in `/Volumes/config/custom_components/axeos/`:
- `manifest.json`
- `__init__.py`
- `const.py`
- `config_flow.py`
- `api_client.py`
- `coordinator.py`
- `sensor.py`
- `button.py`
- `switch.py`
- `services.py`
- `services.yaml`
- `strings.json`
- `README.md`

Ensure all files are in the `axeos` directory under `custom_components`.

## Step 2: Restart Home Assistant

1. Navigate to **Settings → System → Restart**
2. Click **Restart Home Assistant**
3. Wait for restart to complete (2-3 minutes)

## Step 3: Add Integration

1. Go to **Settings → Devices & Services**
2. Click **+ Create Integration** button (bottom right)
3. Search for **"Bitaxe/NerdAxe"**
4. Select the integration
5. Choose **miner type** (Bitaxe or NerdAxe)
6. Enter **Host**: `192.168.3.199`
7. Click **Next** to confirm

The integration will validate connectivity to the miner. If successful, the entry will be created.

## Step 4: View Sensors

1. Go to **Settings → Devices & Services → Devices**
2. Find your miner device (named like "Bitaxe 192.168.3.199")
3. Click on it to see all sensors

### Key Sensors to Check
- **Hashrate**: Should show active hashrate in GH/s
- **Power**: Should show power consumption in W
- **ASIC Temperature**: Should show temperature in °C
- **Uptime**: Should show seconds of uptime
- **Pool URL / User**: Should show current pool configuration

## Step 5: Test Restart Action

1. Go to the device page
2. Look for the **Restart** button
3. Click it to trigger a system restart
4. Verify the miner restarts (check device display or check uptime resets)

## Step 6: Test Pool Reconfiguration Service

1. Go to **Developer Tools → Services**
2. Choose service: **axeos.set_pool**
3. Fill in the parameters:
   ```
   device_id: 192.168.3.199
   stratum_url: stratum+tcp://public-pool.io
   stratum_port: 21496
   stratum_user: your_wallet.worker_name
   stratum_password: x
   ```
4. Click **Call Service**
5. Verify miner connects to new pool (check Pool URL sensor updates)

## Troubleshooting

### Integration won't load
- Check Home Assistant logs: **Settings → System → Logs**
- Verify miner is powered on and at correct IP
- Try `ping 192.168.3.199` from Home Assistant server

### Sensors not updating
- Check if coordinator is polling: Look for "Bitaxe" in logs
- Verify connection is stable
- Try toggling integration off/on via Settings → Devices & Services

### Services not appearing
- Restart Home Assistant again
- Check `services.yaml` is in the axeos directory
- Verify `services.py` imports correctly

### Connection timeout errors
- Ensure miner and Home Assistant are on same network
- Check if miner IP has changed
- Try accessing miner web UI directly: `http://192.168.3.199`

## Monitoring Dashboard

Create a dashboard to monitor your miner:

1. Create a new card with:
   - **Hashrate** (main stat)
   - **Power** (chart)
   - **Temperature** (gauge)
   - **Uptime** (total)
   - **Pool URL** (text display)

Example dashboard card:
```yaml
type: entity
entity: sensor.bitaxe_192_168_3_199_hashrate
```

## Advanced Usage

### Multiple Miners

Repeat the "Add Integration" steps for each miner. Each will:
- Get its own device entry
- Get its own set of sensors
- Be manageable independently

### Automation Examples

**Auto-restart on timeout:**
```yaml
alias: Restart Miner on Timeout
trigger:
  - platform: state
    entity_id: sensor.bitaxe_connectivity
    to: "unavailable"
    for:
      minutes: 5
action:
  - service: button.press
    target:
      entity_id: button.bitaxe_192_168_3_199_restart
```

**Switch pools on low hashrate:**
```yaml
alias: Switch to backup pool
trigger:
  - platform: numeric_state
    entity_id: sensor.bitaxe_hashrate
    below: 500
action:
  - service: axeos.set_pool
    data:
      device_id: "192.168.3.199"
      stratum_url: "stratum+tcp://backup-pool.io"
      stratum_port: 3333
      stratum_user: "your_wallet.backup"
      stratum_password: "x"
```

## Next Steps

- [ ] Verify all sensors are updating
- [ ] Test restart action
- [ ] Test pool reconfiguration service
- [ ] Create monitoring dashboard
- [ ] Add additional miners if applicable
- [ ] Set up automations/alerts
