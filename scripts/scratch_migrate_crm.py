import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.database import engine, Base
import app.models
from sqlalchemy import text, inspect

def migrate_crm():
    print("Migrating CRM tables and columns...")
    
    # Create the new table
    Base.metadata.create_all(bind=engine, tables=[
        app.models.ConversationCategory.__table__
    ])
    print("ConversationCategory table verified/created.")

    with engine.connect() as conn:
        inspector = inspect(engine)
        
        # Check columns of conversation_sessions
        columns = [c["name"] for c in inspector.get_columns("conversation_sessions")]
        
        if "inquiry_number" not in columns:
            print("Adding inquiry_number to conversation_sessions...")
            conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN inquiry_number VARCHAR UNIQUE"))
            conn.commit()
            
        if "category_id" not in columns:
            print("Adding category_id to conversation_sessions...")
            conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN category_id VARCHAR REFERENCES conversation_categories(id) ON DELETE SET NULL"))
            conn.commit()
            
        if "last_message_at" not in columns:
            print("Adding last_message_at to conversation_sessions...")
            conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN last_message_at TIMESTAMP WITH TIME ZONE DEFAULT now()"))
            conn.commit()
            
        if "completed_at" not in columns:
            print("Adding completed_at to conversation_sessions...")
            conn.execute(text("ALTER TABLE conversation_sessions ADD COLUMN completed_at TIMESTAMP WITH TIME ZONE"))
            conn.commit()
            
        # Migrate any existing records with NULL or ACTIVE status to NEW
        try:
            conn.execute(text("UPDATE conversation_sessions SET status = 'NEW' WHERE status = 'ACTIVE' OR status IS NULL"))
            conn.commit()
            print("Status active/null mapped to NEW.")
        except Exception as e:
            conn.rollback()
            print(f"Status update skipped or failed: {e}")
            
    print("CRM migrations completed successfully!")

if __name__ == "__main__":
    migrate_crm()
