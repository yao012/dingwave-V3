import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from web.api import app

import uvicorn

# Configure logging
log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(config.LOGS_DIR, "dingtalk-exporter.log"),
            encoding="utf-8",
        ),
    ],
)

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    logger.info(f"Starting DingTalk Exporter on {config.WEB_HOST}:{config.WEB_PORT}")
    logger.info(f"DingTalk version: v{config.DINGTALK_VERSION}")
    logger.info(f"Data directory: {config.DINGTALK_DATA_DIR}")
    logger.info(f"User UID: {config.USER_UID}")
    logger.info(f"Sync interval: every {config.SYNC_INTERVAL_HOURS} hours")

    if not os.path.exists(config.ENCRYPTED_DB):
        logger.warning(
            f"DingTalk database not found at: {config.ENCRYPTED_DB}\n"
            f"Make sure DingTalk desktop client is installed and logged in on this machine."
        )

    uvicorn.run(
        app,
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        log_level="info",
    )
