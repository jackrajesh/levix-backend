import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect
import sqlalchemy.types as types

# Add the current directory to sys.path so we can import 'app'
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from app.database import Base, engine
    from app.models import *
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

def analyze_schema():
    load_dotenv("config/.env")
    inspector = inspect(engine)
    
    mismatches = []
    
    # Get all models
    models = []
    for name, obj in globals().items():
        if isinstance(obj, type) and issubclass(obj, Base) and obj != Base:
            models.append(obj)
            
    for model in models:
        table_name = model.__tablename__
        if table_name not in inspector.get_table_names():
            mismatches.append(f"Table '{table_name}' (Model: {model.__name__}) does not exist in DB.")
            continue
            
        db_columns = {c['name']: c for c in inspector.get_columns(table_name)}
        
        for name, column in model.__table__.columns.items():
            if name not in db_columns:
                mismatches.append(f"Column '{name}' in Model '{model.__name__}' does not exist in Table '{table_name}'.")
                continue
            
            db_type = str(db_columns[name]['type']).upper()
            model_type = str(column.type).upper()
            
            # Simple type matching (can be improved)
            is_match = False
            if "INT" in model_type and "INT" in db_type: is_match = True
            elif ("VARCHAR" in model_type or "STRING" in model_type or "TEXT" in model_type) and ("VARCHAR" in db_type or "TEXT" in db_type): is_match = True
            elif "NUMERIC" in model_type and "NUMERIC" in db_type: is_match = True
            elif "DATE" in model_type and "DATE" in db_type: is_match = True
            elif "BOOLEAN" in model_type and "BOOLEAN" in db_type: is_match = True
            elif "JSON" in model_type and "JSON" in db_type: is_match = True
            
            if not is_match:
                mismatches.append(f"Type mismatch for '{table_name}.{name}': Model={model_type}, DB={db_type}")

    return mismatches

if __name__ == "__main__":
    print("Starting Full Analytic Run...")
    errors = analyze_schema()
    if errors:
        print("\nFound the following bugs/mismatches:")
        for err in errors:
            print(f"- {err}")
    else:
        print("\nNo schema mismatches found!")
