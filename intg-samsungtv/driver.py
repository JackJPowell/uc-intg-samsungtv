"""
This module implements a Remote Two integration driver for Samsung TV devices.

:copyright: (c) 2023-2024 by Unfolded Circle ApS.
:license: Mozilla Public License Version 2.0, see LICENSE for more details.
"""

import asyncio
import logging
import os

from const import SamsungConfig
from discover import SamsungTVDiscovery
from media_player import SamsungMediaPlayer
from remote import SamsungRemote
from select_entity import SamsungAppSelect
from setup import SamsungSetupFlow
from tv import SamsungTv
from ucapi_framework import BaseConfigManager, BaseIntegrationDriver, get_config_path

_LOG = logging.getLogger(__name__)


async def main():
    """Start the Remote Two integration driver."""
    logging.basicConfig()

    level = os.getenv("UC_LOG_LEVEL", "DEBUG").upper()
    logging.getLogger("tv").setLevel(level)
    logging.getLogger("driver").setLevel(level)
    logging.getLogger("config").setLevel(level)
    logging.getLogger("discover").setLevel(level)
    logging.getLogger("setup").setLevel(level)
    logging.getLogger("select_entity").setLevel(level)
    _LOG.setLevel(level)

    _LOG.info("Starting Samsung TV integration driver with log level %s", level)

    driver = BaseIntegrationDriver(
        device_class=SamsungTv,
        entity_classes=[
            SamsungMediaPlayer,
            SamsungRemote,
            lambda config_device, device: (
                [SamsungAppSelect(config_device, device)]
                if device.app_list
                else []
            ),
        ],
    )

    _LOG.debug("Created BaseIntegrationDriver for Samsung TV integration")

    driver.config_manager = BaseConfigManager(
        get_config_path(driver.api.config_dir_path),
        driver.on_device_added,
        driver.on_device_removed,
        config_class=SamsungConfig,
    )

    _LOG.debug(
        "Configured BaseConfigManager using config path %s",
        get_config_path(driver.api.config_dir_path),
    )

    await driver.register_all_configured_devices()
    _LOG.debug("Completed registration of all configured Samsung TV devices")

    discovery = SamsungTVDiscovery(timeout=2, search_pattern="Samsung")
    _LOG.info(
        "Created SamsungTVDiscovery with timeout=%s search_pattern=%s",
        2,
        "Samsung",
    )

    setup_handler = SamsungSetupFlow.create_handler(driver, discovery)
    _LOG.debug("Created Samsung setup handler with SamsungTVDiscovery")

    await driver.api.init("driver.json", setup_handler)
    _LOG.info("Samsung TV driver API initialized; setup flow ready")

    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
