import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal, engine
from app import models
from datetime import datetime, timezone, timedelta
import time

def test_db_time():
    db = SessionLocal()
    # 1. Insert a mock log
    sender = "9999999999_test"
    db.query(models.MessageLog).filter(models.MessageLog.sender == sender).delete()
    db.commit()

    log = models.MessageLog(sender=sender)
    db.add(log)
    db.commit()

    time.sleep(1)

    # 2. Query it back
    log_db = db.query(models.MessageLog).filter(models.MessageLog.sender == sender).first()
    print(f"Stored DB Timestamp:      {log_db.timestamp}")
    print(f"Stored DB Timestamp tz:   {log_db.timestamp.tzinfo}")
    
    # 3. What does our check say?
    ten_seconds_ago = datetime.now(timezone.utc) - timedelta(seconds=10)
    print(f"Ten seconds ago (Python): {ten_seconds_ago}")
    print(f"Ten seconds ago tz:       {ten_seconds_ago.tzinfo}")
    
    # 4. Filter count
    count = db.query(models.MessageLog).filter(
        models.MessageLog.sender == sender,
        models.MessageLog.timestamp >= ten_seconds_ago
    ).count()
    print(f"Count using >= ten_seconds_ago: {count}")
    
    count_all = db.query(models.MessageLog).filter(models.MessageLog.sender == sender).count()
    print(f"Count without time filter:      {count_all}")
    
    db.close()

if __name__ == "__main__":
    test_db_time()
