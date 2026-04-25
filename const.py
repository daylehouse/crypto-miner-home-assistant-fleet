"""Constants for the Bitaxe/NerdAxe integration."""

DOMAIN = "axeos"
NAME = "Bitaxe/NerdAxe/Avalon Miner"
PLATFORMS_MINER = ["sensor", "button", "switch", "select", "number"]
PLATFORMS_FLEET = ["sensor"]
PLATFORMS = PLATFORMS_MINER

# Miner types
MINER_TYPE_BITAXE = "bitaxe"
MINER_TYPE_NERDAXE = "nerdaxe"
MINER_TYPE_AVALON = "avalon"
MINER_TYPES = [MINER_TYPE_BITAXE, MINER_TYPE_NERDAXE, MINER_TYPE_AVALON]

# Config entry keys
CONF_HOST = "host"
CONF_MINER_TYPE = "miner_type"
CONF_DEVICE_NAME = "device_name"
CONF_DEVICE_SLUG = "device_slug"
CONF_POOLS = "pools"
CONF_ENTRY_TYPE = "entry_type"
CONF_OVERHEAT_THRESHOLD_C = "overheat_threshold_c"
CONF_AVALON_USERNAME = "avalon_username"
CONF_AVALON_PASSWORD = "avalon_password"

# Config entry types
ENTRY_TYPE_MINER = "miner"
ENTRY_TYPE_FLEET = "fleet"

# API endpoints
API_SYSTEM_INFO = "/api/system/info"
API_SYSTEM_ASIC = "/api/system/asic"
API_SYSTEM_RESTART = "/api/system/restart"
API_SYSTEM = "/api/system"

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
