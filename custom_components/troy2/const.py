"""Constants for the Screen Innovations TRO.Y 2 integration."""

DOMAIN = "troy2"
PLATFORMS = ["cover"]

SERVICE_SET_WIRED_SPEEDS = "set_wired_speeds"

ATTR_UP_SPEED = "up_speed"
ATTR_DOWN_SPEED = "down_speed"
ATTR_SLOW_SPEED = "slow_speed"

MIN_WIRED_SPEED = 10
MAX_WIRED_SPEED = 25

CONF_NODE_ID = "node_id"
CONF_SHADE_NAME = "shade_name"

DEFAULT_NAME = "TRO.Y Shade"
DEFAULT_NODE_ID = "0000"
DEFAULT_SCAN_INTERVAL_SECONDS = 5

# Poll much faster after a movement command so Home Assistant and HomeKit
# follow the physical shade without permanently hammering the TRO.Y controller.
MOVEMENT_POLL_INTERVAL_SECONDS = 1
MOVEMENT_POLL_TIMEOUT_SECONDS = 90
MOVEMENT_MINIMUM_POLL_SECONDS = 4
MOVEMENT_STABLE_POLLS = 3
