"""Constants for Acova Timerprog."""
from homeassistant.const import Platform

DOMAIN = "acova_timerprog"
PLATFORMS = [Platform.CLIMATE, Platform.BINARY_SENSOR, Platform.BUTTON]

CONF_PRIORITY = "priority"
PRIORITY_FACADE = "facade"  # (a) facade wins: HA reflects, never re-imposes
PRIORITY_HA = "ha"  # (b) HA wins: HA re-applies its last command (2h boost respected)
DEFAULT_PRIORITY = PRIORITY_FACADE

CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 300  # seconds
MIN_SCAN_INTERVAL = 60
MAX_SCAN_INTERVAL = 3600

DEFAULT_COMFORT = 19.0
MIN_TEMP = 7.0
MAX_TEMP = 30.0
ECO_DELTA = 3.5  # the app always sets eco = comfort - 3.5 °C
FROST_TEMP = 7.0
