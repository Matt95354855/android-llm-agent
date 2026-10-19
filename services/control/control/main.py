from __future__ import annotations

import logging
import os

import uvicorn


def run() -> None:
    logging.basicConfig(level=os.environ.get("PE_LOG_LEVEL", "INFO"))
    uvicorn.run(
        "control.api:create_app",
        factory=True,
        host=os.environ.get("PE_HOST", "0.0.0.0"),
        port=int(os.environ.get("PE_PORT", "8000")),
        proxy_headers=True,
    )


if __name__ == "__main__":
    run()
