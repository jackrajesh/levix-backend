import re
import pathlib

content = pathlib.Path("app/models.py").read_text()

# Revert my blind replace
content = content.replace("id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))", "id = Column(Integer, primary_key=True, index=True)")

# Now, selectively replace the ones that are VARCHAR/TEXT in DB.
string_id_tables = [
    "shops", "password_reset_tokens", "inventory_items", "inventory_aliases",
    "log_entries", "pending_requests", "pending_inquiries", "sales_records",
    "customer_sessions", "customer_profiles", "orders", "order_logs",
    "team_members"
]

# We need to find each class and its __tablename__ and update `id = ...`
class_blocks = content.split("class ")
for i in range(1, len(class_blocks)):
    block = class_blocks[i]
    tablename_match = re.search(r'__tablename__\s*=\s*"([^"]+)"', block)
    if tablename_match:
        tablename = tablename_match.group(1)
        if tablename in string_id_tables:
            # Change id
            block = re.sub(r'id\s*=\s*Column\(Integer,\s*primary_key=True,\s*index=True\)', r'id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))', block)
    class_blocks[i] = block

content = "class ".join(class_blocks)

# Now fix the Foreign Keys
# shop_id is always String because shops is String
content = re.sub(r'shop_id\s*=\s*Column\(Integer,\s*ForeignKey\("shops\.id"\)([^)]*)\)', r'shop_id = Column(String, ForeignKey("shops.id")\1)', content)

# inventory_id / product_id linked to inventory_items.id
content = re.sub(r'inventory_id\s*=\s*Column\(Integer,\s*ForeignKey\("inventory_items\.id"\)([^)]*)\)', r'inventory_id = Column(String, ForeignKey("inventory_items.id")\1)', content)
content = re.sub(r'product_id\s*=\s*Column\(Integer,\s*ForeignKey\("inventory_items\.id"\)([^)]*)\)', r'product_id = Column(String, ForeignKey("inventory_items.id")\1)', content)

# other product_id that are not ForeignKey but Integer
content = re.sub(r'product_id\s*=\s*Column\(Integer([^)]*)\)', r'product_id = Column(String\1)', content)

# matched_product_id in ai sessions
content = re.sub(r'matched_product_id\s*=\s*Column\(Integer([^)]*)\)', r'matched_product_id = Column(String\1)', content)

# Addon id is integer, so addon_id is integer
# Plan id is integer, so plan_id is integer
# Team member id is string, but not used as FK
# Order ID is string
content = re.sub(r'order_id\s*=\s*Column\(String,\s*index=True([^)]*)\)', r'order_id = Column(String, index=True\1)', content) # It's already string

pathlib.Path("app/models.py").write_text(content)
