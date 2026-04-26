import os

def fix_routes_auth(routes_dir):
    for root, dirs, files in os.walk(routes_dir):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Correct .core.auth back to .auth in routes
                new_content = content.replace("from .core.auth import", "from .auth import")
                
                if new_content != content:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(new_content)

if __name__ == "__main__":
    fix_routes_auth("app/routes")
    print("Routes auth fix completed.")
