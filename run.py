"""Entrypoint for otel-data-api. Used by uvicorn as 'run:app'."""

import os

import structlog
from dotenv import load_dotenv

from app import create_app
from app.config import Config
from app.logging import configure_logging

load_dotenv()

config = Config.from_env()
configure_logging(config)

logger = structlog.get_logger("otel-data-api")

# --- New Relic (optional, env-gated) ---
if os.getenv("NEW_RELIC_LICENSE_KEY"):
    try:
        import newrelic.agent  # pyright: ignore[reportMissingImports]

        newrelic.agent.initialize()
        newrelic.agent.register_application(timeout=10)

        logger.info("New Relic agent initialized with trace correlation")
    except Exception:
        logger.exception("New Relic agent failed to initialize — continuing without it")

app = create_app(config)

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("run:app", host="0.0.0.0", port=port, reload=True)
