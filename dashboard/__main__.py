from __future__ import annotations

import logging

import uvicorn

from dashboard.app import create_app
from dashboard.config import DashboardSettings


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = DashboardSettings.from_env()
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
