import ast, sys
files = [
    'app/models.py',
    'app/schemas.py',
    'app/main.py',
    'app/services/ai_assistant.py',
    'app/routes/inbox.py',
    'app/routes/inventory.py',
]
ok = True
for f in files:
    try:
        with open(f, encoding='utf-8') as fh:
            src = fh.read()
        ast.parse(src)
        print(f'  OK   {f}')
    except SyntaxError as e:
        print(f'  FAIL {f}: line {e.lineno} — {e.msg}')
        ok = False
sys.exit(0 if ok else 1)
