import re

with open('app/templates/dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Find all onclick attributes
onclicks = re.findall(r'onclick=["\'](.*?)["\']', content)

for o in onclicks:
    # Check for unquoted template variables
    # Matches ${var} but not '${var}' or "${var}" or (${var})
    if '${' in o:
        # A simple heuristic: if it's not preceded by a quote and followed by one
        # or if it's just the variable alone
        if re.search(r'(?<![\'"])\$\{[^}]+\}(?![\'"])', o):
            # Exclude numbers like ${i} if i is known to be a number (e.g. pagination)
            if not re.search(r'\$\{[i|p|invPage|salesPage|inboxPage|teamPage|page|n][^}]*\}', o):
                print(f"Potential unquoted ID in onclick: {o}")
