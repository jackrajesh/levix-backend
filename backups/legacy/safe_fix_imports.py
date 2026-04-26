import os
import re

def fix_imports(root_dir):
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Core module moves
                content = content.replace('from ..database import', 'from ..core.database import')
                content = content.replace('from ..auth import', 'from ..core.auth import')
                content = content.replace('from ..permissions import', 'from ..core.permissions import')
                
                # Handle imports from root of app
                content = content.replace('from .database import', 'from .core.database import')
                content = content.replace('from .auth import', 'from .core.auth import')
                content = content.replace('from .permissions import', 'from .core.permissions import')

                # Handle multi-imports with trailing auth
                content = re.sub(r'from \.\. import (.*), auth', r'from .. import \1\nfrom ..core import auth', content)
                content = re.sub(r'from \. import (.*), auth', r'from . import \1\nfrom .core import auth', content)

                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

if __name__ == "__main__":
    fix_imports("app")
    print("Safe import fix completed.")
