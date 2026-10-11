# Release Notes

## Since Yesterday (2026-10-10 to 2026-10-11)

### Highlights
- Added target temperature controls for Bitaxe and NerdAxe miner entries.
- Added a dedicated Bitaxe target temperature slider in Home Assistant.
- Switched NerdAxe target temperature writes to the V2 settings API endpoint.
- Kept NerdAxe shutdown/overheat threshold controls separate from target temperature.
- Added a Bitaxe Mining Active switch that pauses and resumes mining from the miner API.
- Fixed a runtime regression in number entity method wiring for Bitaxe target temperature.
- Fixed Bitaxe reboot hydration so target temperature no longer relinks local overheat sliders on startup.
- Improved threshold and warning behavior consistency (warning threshold uses setpoint minus 1 C).
- Improved startup stability by fixing duplicate hostname/IP miner entry handling.

### Thermal Control and Threshold Work
- Mapped NerdAxe ASIC/VR shutdown thresholds to expected API fields.
- Fixed multiple NerdAxe shutdown threshold update edge cases.
- Synced overheat thresholds with miner API values where expected.
- Deduplicated target temperature parsing helpers.

### Home Assistant Entity Changes
- Added number entity support for target temperature controls.
- Added local overheat alert behavior for Bitaxe where requested.
- Stabilized number entity behavior after refactors to prevent service-call failures.
- Preserved independent Bitaxe overheat slider values across restart and reload cycles.
- Added a stateful Bitaxe Mining Active switch with pause/resume control.

### Released Versions in This Window
- v1.2.1
- v1.2.2
- v1.2.11
- v1.2.12
- v1.2.13
- v1.3.0
- v1.3.1
- v1.3.2

### Key Commits
- e6010c6 - Fix hostname/IP duplicate miner entries on startup
- 5ef0d08 - Sync Bitaxe/NerdAxe overheat thresholds with miner API
- 48c25da - Map NerdAxe ASIC/VR shutdown thresholds
- db3a538 - Fix NerdAxe shutdown threshold updates
- 14b25ac - Align NerdAxe thresholds with API fields
- f116d7b - Adjust overheat warning threshold to setpoint minus one
- c78f558 - Add target temperature control for Bitaxe and NerdAxe
- 3f336d1 - Deduplicate target temp parsing helpers
- c1fd687 - Add Bitaxe target temp slider and local overheat alerts
- 69ffc75 - Fix Bitaxe target number setter regression
- 77c287d - Add NerdAxe target temperature number support
- 3a0efe9 - Use NerdAxe V2 settings endpoint for target temp
- b67a509 - Bump release version to 1.3.0
- 3674bb5 - Fix Bitaxe slider relink on reboot
