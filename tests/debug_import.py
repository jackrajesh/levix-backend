try:
    from app.main import app
    print("Import successful")
except Exception as e:
    import traceback
    print("Import failed")
    traceback.print_exc()
