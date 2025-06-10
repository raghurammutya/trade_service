#!/usr/bin/env python3
import re

# Read the trade_endpoints.py file
with open('app/api/endpoints/trade_endpoints.py', 'r') as f:
    content = f.read()

# Fix function signatures where background_tasks comes after default arguments
# Pattern: finds functions with db = Depends(...), background_tasks: BackgroundTasks
pattern = r'(\w+:\s*\w+\s*=\s*Depends\([^)]+\)),\s*(background_tasks:\s*BackgroundTasks)'
replacement = r'\2, \1'

content = re.sub(pattern, replacement, content)

# Write back the fixed content
with open('app/api/endpoints/trade_endpoints.py', 'w') as f:
    f.write(content)

print("✅ Fixed function signatures")
