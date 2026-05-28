from app.main import _run_uuid_reconciliation
from app.database import engine

if __name__ == "__main__":
    print("Running manual reconciliation...")
    _run_uuid_reconciliation()
    print("Done.")
