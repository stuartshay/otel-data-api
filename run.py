"""Entrypoint for otel-data-api. Used by uvicorn as 'run:app'."""

import os

import structlog
from dotenv import load_dotenv

from app import create_app
from app.config import Config
from app.logging import configure_logging

load_dotenv()

config = Config.from_env()
log_provider = configure_logging(config)

logger = structlog.get_logger("otel-data-api")

app = create_app(config)
app.state.log_provider = log_provider

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("run:app", host="0.0.0.0", port=port, reload=True)
