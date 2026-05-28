from __future__ import annotations

import uvicorn

from api import create_app
from settings import AppConfig


def main() -> None:
    config = AppConfig.local_http_stack()
    app = create_app(config)
    uvicorn.run(app, host=config.api_host, port=config.api_port, reload=False)


if __name__ == "__main__":
    main()
