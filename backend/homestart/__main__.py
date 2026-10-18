import logging
import sys

import uvicorn

from .config import ConfigError, load_settings


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)
    log = logging.getLogger("homestart")

    try:
        settings = load_settings()
        from .main import create_app

        app = create_app(settings)
    except ConfigError as exc:
        log.error("Configuration error, HomeStart is not started: %s", exc)
        return 1
    except Exception:
        log.exception("HomeStart failed to start")
        return 1

    log.info("HomeStart listening on %s:%s", settings.host, settings.port)
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None, proxy_headers=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
