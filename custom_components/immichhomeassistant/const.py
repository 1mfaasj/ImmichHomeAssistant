from __future__ import annotations

DOMAIN = "immichhomeassistant"

CONF_WATCHED_ALBUMS = "watched_albums"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_NO_REPEAT_WINDOW = "no_repeat_window"
CONF_TAG_FILTER = "tag_filter"
CONF_SHUFFLE_MODE = "shuffle_mode"
CONF_RANDOM_SPEED = "random_speed"

DEFAULT_REFRESH_INTERVAL = 300
DEFAULT_NO_REPEAT_WINDOW = 10
DEFAULT_TAG_FILTER = ""
DEFAULT_SHUFFLE_MODE = False
DEFAULT_RANDOM_SPEED = False

ID_LIST_REFRESH_INTERVAL_SECONDS = 12 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 30
MIN_REFRESH_INTERVAL = 10
MAX_REFRESH_INTERVAL = 3600
MIN_NO_REPEAT_WINDOW = 0
MAX_NO_REPEAT_WINDOW = 200

SEARCH_PAGE_SIZE = 1000
MAX_SEARCH_PAGES = 200

# Unique IDs. Deze blijven gelijk aan eerdere versies zodat entity_id's
# (en dus bestaande dashboards) behouden blijven.
UID_PREFIX = "immichhomeassistant"
UID_FAVORITES = f"{UID_PREFIX}_favorite_image"
UID_SHUFFLE_MODE = f"{UID_PREFIX}_shuffle_mode"
UID_RANDOM_SPEED = f"{UID_PREFIX}_random_speed"
UID_REFRESH_INTERVAL = f"{UID_PREFIX}_refresh_interval"


def album_unique_id(album_id: str) -> str:
    return f"{UID_PREFIX}_album_{album_id}"


def original_unique_id(source_unique_id: str) -> str:
    return f"{source_unique_id}_original"


def next_button_unique_id(source_unique_id: str) -> str:
    return f"{source_unique_id}_next"
