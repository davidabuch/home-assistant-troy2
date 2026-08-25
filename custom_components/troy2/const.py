"""Constants for the Screen Innovations TRO.Y 2 integration."""

DOMAIN = "troy2"
PLATFORMS = ["cover"]

CONTROLLER_TITLE = "TRO.Y 2 Shade Controller"
INTEGRATION_VERSION = "0.3.17"

SERVICE_SET_WIRED_SPEEDS = "set_wired_speeds"

ATTR_UP_SPEED = "up_speed"
ATTR_DOWN_SPEED = "down_speed"
ATTR_SLOW_SPEED = "slow_speed"

MIN_WIRED_SPEED = 10
MAX_WIRED_SPEED = 25

CONF_NODE_ID = "node_id"
CONF_SHADE_NAME = "shade_name"

DEFAULT_NAME = "TRO.Y Shade"
DEFAULT_SCAN_INTERVAL_SECONDS = 20
COMMUNICATION_FAILURE_GRACE_SECONDS = 60
MAX_FAILURE_POLL_BACKOFF_SECONDS = 300

# Poll much faster after a movement command so Home Assistant and HomeKit
# follow the physical shade without permanently hammering the TRO.Y controller.
MOVEMENT_POLL_INTERVAL_SECONDS = 1
MOVEMENT_POLL_TIMEOUT_SECONDS = 90
MOVEMENT_MINIMUM_POLL_SECONDS = 4
MOVEMENT_STABLE_POLLS = 3
