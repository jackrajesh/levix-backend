import os
import re
import glob

def fix_type_hints():
    routes_dir = r"c:\Users\shanm\.gemini\antigravity\scratch\Levix\app\routes"
    files = glob.glob(os.path.join(routes_dir, "*.py"))
    
    # Regex to match patterns like `var_id: int` or `_id: int` in function definitions
    pattern = re.compile(r'([a-zA-Z0-9_]*_?id):\s*int')
    
    for filepath in files:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        new_content = pattern.sub(r'\1: str', content)
        
        # Also fix owner_id: int, member_id: int, etc.
        if new_content != content:
            print(f"Updated {filepath}")
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)

if __name__ == "__main__":
    fix_type_hints()
