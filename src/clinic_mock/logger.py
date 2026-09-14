import sys

from loguru import logger

from clinic_mock.config import settings


def setup_logging() -> None:
    logger.remove()
    if settings.log.JSON_LOGS:
        logger.add(sys.stdout, level=settings.log.LEVEL, serialize=True)
    else:
        logger.add(
            sys.stdout,
            level=settings.log.LEVEL,
            format="<level>{level: <8}</level> | {name}:{function} - <level>{message}</level>",
        )


setup_logging()
