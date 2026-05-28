import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.database import engine, Base
import app.models

def migrate_conversations():
    print("Migrating conversations tables...")
    Base.metadata.create_all(bind=engine, tables=[
        app.models.ConversationSession.__table__,
        app.models.ConversationMessage.__table__
    ])
    print("Successfully created ConversationSession and ConversationMessage tables.")

if __name__ == "__main__":
    migrate_conversations()
