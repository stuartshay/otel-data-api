"""Entrypoint for otel-data-api. Used by uvicorn as 'run:app'."""

import logging
import os

from dotenv import load_dotenv

from app import create_app
from app.config import Config

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

logger = logging.getLogger("otel-data-api")

# --- New Relic (optional, env-gated) ---
if os.getenv("NEW_RELIC_LICENSE_KEY"):
    try:
        import newrelic.agent  # pyright: ignore[reportMissingImports]

        newrelic.agent.initialize()
        newrelic.agent.register_application(timeout=10)

        # Enable log-trace correlation by replacing the root log formatter
        # with NewRelicContextFormatter, which injects trace.id, span.id,
        # and entity metadata into every log record.
        from newrelic.agent import NewRelicContextFormatter  # pyright: ignore[reportMissingImports]

        for handler in logging.root.handlers:
            handler.setFormatter(
                NewRelicContextFormatter(
                    "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                ),
            )

        logger.info("New Relic agent initialized with trace correlation")
    except Exception:
        logger.exception("New Relic agent failed to initialize — continuing without it")

config = Config.from_env()
app = create_app(config)

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("run:app", host="0.0.0.0", port=port, reload=True)
