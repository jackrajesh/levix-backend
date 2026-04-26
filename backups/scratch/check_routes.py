from app.main import app
from fastapi.routing import APIRoute
for route in app.routes:
    if isinstance(route, APIRoute):
        print(f"{route.methods} {route.path}")
    else:
        print(f"MOUNT {route.path}")
