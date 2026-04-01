import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal
from app import models
from datetime import datetime
import time

def check_logs():
    db = SessionLocal()
    sender = "919999999999"
    logs = db.query(models.MessageLog).filter(models.MessageLog.sender == sender).order_by(models.MessageLog.timestamp).all()
    print(f"Total Database Logs for {sender}: {len(logs)}")
    for i, log in enumerate(logs):
        print(f"[{i+1}] {log.timestamp} - {log.timestamp.tzinfo}")
    db.close()

if __name__ == "__main__":
    check_logs()
