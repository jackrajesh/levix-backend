import os
import json

def get_file_tree(startpath):
    tree = {}
    for root, dirs, files in os.walk(startpath):
        if '__pycache__' in root or '.git' in root:
            continue
        rel_path = os.path.relpath(root, startpath)
        if rel_path == '.':
            rel_path = ''
        for f in files:
            full_path = os.path.join(root, f)
            rel_file_path = os.path.join(rel_path, f)
            tree[rel_file_path] = {
                'size': os.path.getsize(full_path),
                'path': full_path
            }
    return tree

current_dir = r'c:\Users\shanm\.gemini\antigravity\scratch\Levix'
backup_dir = r'c:\Users\shanm\.gemini\antigravity\scratch\Levix\BACKUP\Levix 1'

# We want to exclude BACKUP folder when scanning CURRENT_DIR
def get_current_tree(startpath):
    tree = {}
    for root, dirs, files in os.walk(startpath):
        if 'BACKUP' in root or '__pycache__' in root or '.git' in root:
            continue
        rel_path = os.path.relpath(root, startpath)
        if rel_path == '.':
            rel_path = ''
        for f in files:
            full_path = os.path.join(root, f)
            rel_file_path = os.path.join(rel_path, f)
            tree[rel_file_path] = {
                'size': os.path.getsize(full_path),
                'path': full_path
            }
    return tree

current_tree = get_current_tree(current_dir)
backup_tree = get_file_tree(backup_dir)

report = {
    'missing_in_current': [],
    'size_mismatch': [],
    'extra_in_current': []
}

for path, info in backup_tree.items():
    if path not in current_tree:
        report['missing_in_current'].append({
            'path': path,
            'backup_size': info['size']
        })
    else:
        if abs(info['size'] - current_tree[path]['size']) > 100:
            report['size_mismatch'].append({
                'path': path,
                'backup_size': info['size'],
                'current_size': current_tree[path]['size']
            })

for path in current_tree:
    if path not in backup_tree:
        report['extra_in_current'].append(path)

with open(r'c:\Users\shanm\.gemini\antigravity\scratch\Levix\audit_report.json', 'w') as f:
    json.dump(report, f, indent=4)

print("Audit report generated at c:\\Users\\shanm\\.gemini\\antigravity\\scratch\\Levix\\audit_report.json")
