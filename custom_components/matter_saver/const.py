"""Constants for Matter Saver."""

DOMAIN = "matter_saver"
DEFAULT_NAME = "Matter Saver"

CONF_MATTER_URL = "matter_url"
DEFAULT_MATTER_URL = "ws://core-matter-server:5580/ws"

SCAN_INTERVAL_SECONDS = 60

# How often the Thread counters of mains-powered nodes are read from the device
COUNTER_REFRESH_SECONDS = 300
