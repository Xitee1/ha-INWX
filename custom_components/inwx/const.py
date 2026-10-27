"""Constants for the INWX integration."""

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "inwx"
LOGGER = logging.getLogger(__package__)

CONF_SHARED_SECRET: Final = "shared_secret"
CONF_FORECAST_DAYS: Final = "forecast_days"
CONF_INCLUDE_VAT: Final = "include_vat"

DEFAULT_FORECAST_DAYS: Final = 30
DEFAULT_INCLUDE_VAT: Final = True
MAX_FORECAST_DAYS: Final = 365

SCAN_INTERVAL: Final = timedelta(hours=1)

RENEWAL_MODE_AUTORENEW: Final = "AUTORENEW"
RENEWAL_MODES: Final = ["AUTORENEW", "AUTODELETE", "AUTOEXPIRE"]
