from app.main import _run_migrations
import logging

logging.basicConfig(level=logging.INFO)
print("Manually running migrations...")
_run_migrations()
print("Migrations complete.")
