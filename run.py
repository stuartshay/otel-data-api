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

config = Config.from_env()
app = create_app(config)

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("run:app", host="0.0.0.0", port=port, reload=True)
