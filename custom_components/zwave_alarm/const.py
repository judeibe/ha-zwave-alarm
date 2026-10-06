"""Shared constants for the Z-Wave Alarm custom component (T035)."""

DOMAIN = "zwave_alarm"

# Config-entry key for "use https/wss" (contracts/websocket-events.md serves the stream over wss).
CONF_SSL = "ssl"

# The service's default HTTP port (src/config/index.ts's HTTP_PORT); used only
# to pre-fill the config flow form, not enforced.
DEFAULT_PORT = 3000

# Keypad contract v1.1 capability that gates the chime service.
CAPABILITY_CHIME = "chime"

# Options-flow key: show the configuration panel in the sidebar (it stays reachable by URL either way).
CONF_SHOW_IN_SIDEBAR = "show_in_sidebar"
