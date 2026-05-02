"""Constants for the Bitaxe/NerdAxe/Avalon/Goldshell integration."""

DOMAIN = "axeos"
NAME = "Bitaxe/NerdAxe/Avalon/Goldshell Miner"
PLATFORMS_MINER = ["sensor", "button", "switch", "select", "number"]
PLATFORMS_FLEET = ["sensor"]
PLATFORMS = PLATFORMS_MINER

# Miner types
MINER_TYPE_BITAXE = "bitaxe"
MINER_TYPE_NERDAXE = "nerdaxe"
MINER_TYPE_AVALON = "avalon"
MINER_TYPE_GOLDSHELL = "goldshell"
MINER_TYPES = [MINER_TYPE_BITAXE, MINER_TYPE_NERDAXE, MINER_TYPE_AVALON, MINER_TYPE_GOLDSHELL]

# Config entry keys
CONF_HOST = "host"
CONF_MINER_TYPE = "miner_type"
CONF_DEVICE_NAME = "device_name"
CONF_DEVICE_SLUG = "device_slug"
CONF_POOLS = "pools"
CONF_ENTRY_TYPE = "entry_type"
# Legacy ASIC threshold key (kept for backward compatibility)
CONF_OVERHEAT_THRESHOLD_C = "overheat_threshold_c"
CONF_ASIC_OVERHEAT_THRESHOLD_C = "asic_overheat_threshold_c"
CONF_VR_OVERHEAT_THRESHOLD_C = "vr_overheat_threshold_c"
# Preferred Goldshell per-card threshold keys
CONF_GOLDSHELL_ALEO_OVERHEAT_THRESHOLD_C = "goldshell_aleo_overheat_threshold_c"
CONF_GOLDSHELL_LTC_OVERHEAT_THRESHOLD_C = "goldshell_ltc_overheat_threshold_c"
# Legacy Goldshell threshold keys (kept for backward compatibility)
CONF_GOLDSHELL_TEMP1_OVERHEAT_THRESHOLD_C = "goldshell_temp1_overheat_threshold_c"
CONF_GOLDSHELL_TEMP2_OVERHEAT_THRESHOLD_C = "goldshell_temp2_overheat_threshold_c"
CONF_AVALON_USERNAME = "avalon_username"
CONF_AVALON_PASSWORD = "avalon_password"
CONF_GOLDSHELL_USERNAME = "goldshell_username"
CONF_GOLDSHELL_PASSWORD = "goldshell_password"

# Config entry types
ENTRY_TYPE_MINER = "miner"
ENTRY_TYPE_FLEET = "fleet"

# API endpoints
API_SYSTEM_INFO = "/api/system/info"
API_SYSTEM_ASIC = "/api/system/asic"
API_SYSTEM_RESTART = "/api/system/restart"
API_SYSTEM = "/api/system"
# Goldshell endpoints
API_GOLDSHELL_DEVS = "/mcb/cgminer?cgminercmd=devs"
API_GOLDSHELL_POOLS = "/mcb/pools"
API_GOLDSHELL_RESTART = "/mcb/restart"

# Update intervals (seconds)
SCAN_INTERVAL = 30

# HTTP defaults
DEFAULT_TIMEOUT = 10
CONNECTION_TIMEOUT = 5

# Overheat threshold defaults (C)
OVERHEAT_THRESHOLD_MIN_C = 55.0
OVERHEAT_THRESHOLD_MAX_C = 75.0
OVERHEAT_THRESHOLD_DEFAULT_C = 65.0

AVALON_OVERHEAT_THRESHOLD_MIN_C = 70.0
AVALON_OVERHEAT_THRESHOLD_MAX_C = 95.0
AVALON_OVERHEAT_THRESHOLD_DEFAULT_C = 80.0


def overheat_threshold_profile(miner_type: str) -> tuple[float, float, float]:
	"""Return (min, max, default) overheat threshold profile by miner type."""
	if miner_type == MINER_TYPE_AVALON:
		return (
			AVALON_OVERHEAT_THRESHOLD_MIN_C,
			AVALON_OVERHEAT_THRESHOLD_MAX_C,
			AVALON_OVERHEAT_THRESHOLD_DEFAULT_C,
		)
	return (
		OVERHEAT_THRESHOLD_MIN_C,
		OVERHEAT_THRESHOLD_MAX_C,
		OVERHEAT_THRESHOLD_DEFAULT_C,
	)

# Error messages
ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_HOST = "invalid_host"
ERROR_CONNECTION_TIMEOUT = "connection_timeout"
ERROR_UNKNOWN = "unknown"
