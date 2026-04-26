from app.database import SessionLocal
from app.services.ai_router import AIRouter

db = SessionLocal()
try:
    print(AIRouter.process_message(db, 1, "1234567890", "hi"))
finally:
    db.close()
