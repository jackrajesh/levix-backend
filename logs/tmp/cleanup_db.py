from app.database import SessionLocal, engine
from sqlalchemy import text

def run_cleanup():
    db = SessionLocal()
    try:
        # User specified junk items to remove
        junk_items = [
            "Priority high",
            "Each word",
            "Changes file appservicesproductservice",
            # Adding some extra ones identified by patterns
            "Instructions",
            "Goal"
        ]
        
        # Use simple SQL for precision
        query = text("DELETE FROM log_entries WHERE product_name IN :junk_list")
        result = db.execute(query, {"junk_list": tuple(junk_items)})
        db.commit()
        
        print(f"[CLEANUP SUCCESS] Removed {result.rowcount} junk entries from log_entries.")
    except Exception as e:
        print(f"[CLEANUP FAILED] Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    run_cleanup()
