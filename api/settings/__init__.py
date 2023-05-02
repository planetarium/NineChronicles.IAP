import logging
import os

from starlette.config import Config, Environ

env = os.environ.get("env")
if not env:
    logging.error("Config file not found")
    raise FileNotFoundError(f"No config file for environment")

if os.path.exists(os.path.join("api", "settings", f"{env}.py")):
    config = Config(os.path.join("api", "settings", f"{env}.py"))
else:
    config = Environ()

# Prepare settings
DEBUG = config("DEBUG", cast=bool, default=False)
LOGGING_LEVEL = logging.getLevelName(config("LOGGING_LEVEL", default="INFO"))
