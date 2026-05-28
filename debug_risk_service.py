from __future__ import annotations

import uvicorn

from risk_service import create_risk_service_app
from settings import AppConfig


def main() -> None:
    config = AppConfig.local_http_stack()
    app = create_risk_service_app(config)
    uvicorn.run(app, host=config.risk_service_host, port=config.risk_service_port, reload=False)


if __name__ == "__main__":
    main()
