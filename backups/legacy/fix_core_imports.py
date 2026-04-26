import os

def fix_core_imports(core_dir):
    for root, dirs, files in os.walk(core_dir):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Correct .core. back to . in core directory
                new_content = content.replace("from .core.", "from .")
                
                if new_content != content:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(new_content)

if __name__ == "__main__":
    fix_core_imports("app/core")
    print("Core imports fix completed.")
