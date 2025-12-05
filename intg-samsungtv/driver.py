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
from setup import SamsungSetupFlow
from tv import SamsungTv
from ucapi_framework import BaseConfigManager, BaseIntegrationDriver, get_config_path


async def main():
    """Start the Remote Two integration driver."""
    logging.basicConfig()

    level = os.getenv("UC_LOG_LEVEL", "DEBUG").upper()
    logging.getLogger("tv").setLevel(level)
    logging.getLogger("driver").setLevel(level)
    logging.getLogger("config").setLevel(level)
    logging.getLogger("discover").setLevel(level)
    logging.getLogger("setup").setLevel(level)

    driver = BaseIntegrationDriver(
        device_class=SamsungTv,
        entity_classes=[SamsungMediaPlayer, SamsungRemote],
    )

    driver.config_manager = BaseConfigManager(
        get_config_path(driver.api.config_dir_path),
        driver.on_device_added,
        driver.on_device_removed,
        config_class=SamsungConfig,
    )

    await driver.register_all_configured_devices()

    discovery = SamsungTVDiscovery(timeout=2, search_pattern="Samsung")
    setup_handler = SamsungSetupFlow.create_handler(driver, discovery)

    await driver.api.init("driver.json", setup_handler)

    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
