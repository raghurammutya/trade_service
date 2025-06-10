#!/usr/bin/env python3
"""
Script to discover the actual structure of your trade_service
"""
import os
import sys
from pathlib import Path

def discover_trade_service_structure():
    """Discover the actual file structure of trade_service."""
    
    print("🔍 Discovering Trade Service Structure")
    print("=" * 50)
    
    # Find the base directory
    current_dir = Path.cwd()
    print(f"📁 Current directory: {current_dir}")
    
    # Look for trade_service directory
    trade_service_dirs = list(current_dir.glob("**/trade_service"))
    if trade_service_dirs:
        trade_service_dir = trade_service_dirs[0]
        print(f"📁 Found trade_service at: {trade_service_dir}")
    else:
        trade_service_dir = current_dir
        print(f"📁 Using current directory as trade_service: {trade_service_dir}")
    
    print("\n📋 Directory Structure:")
    print("-" * 30)
    
    # Show directory tree
    for root, dirs, files in os.walk(trade_service_dir):
        # Skip __pycache__ and .git directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        
        level = root.replace(str(trade_service_dir), '').count(os.sep)
        indent = ' ' * 2 * level
        print(f"{indent}{os.path.basename(root)}/")
        
        subindent = ' ' * 2 * (level + 1)
        for file in files:
            if file.endswith(('.py', '.yaml', '.yml', '.txt', '.md')):
                print(f"{subindent}{file}")
    
    print("\n🎯 Key Files Found:")
    print("-" * 30)
    
    # Look for main.py files
    main_files = list(trade_service_dir.glob("**/main.py"))
    for main_file in main_files:
        rel_path = main_file.relative_to(trade_service_dir)
        print(f"🎯 main.py: {rel_path}")
        
        # Show imports from main.py
        try:
            with open(main_file, 'r') as f:
                lines = f.readlines()[:20]  # First 20 lines
                print("   📥 Imports:")
                for line in lines:
                    if line.strip().startswith(('import ', 'from ')):
                        print(f"      {line.strip()}")
        except Exception as e:
            print(f"   ❌ Could not read file: {e}")
    
    # Look for service files
    service_files = list(trade_service_dir.glob("**/*service*.py"))
    print(f"\n⚙️  Service Files:")
    for service_file in service_files[:5]:  # Show first 5
        rel_path = service_file.relative_to(trade_service_dir)
        print(f"   ⚙️  {rel_path}")
    
    # Look for API/endpoint files
    api_files = list(trade_service_dir.glob("**/*api*.py")) + list(trade_service_dir.glob("**/*endpoint*.py")) + list(trade_service_dir.glob("**/*route*.py"))
    print(f"\n🌐 API/Endpoint Files:")
    for api_file in api_files[:5]:
        rel_path = api_file.relative_to(trade_service_dir)
        print(f"   🌐 {rel_path}")
    
    # Look for model files
    model_files = list(trade_service_dir.glob("**/*model*.py"))
    print(f"\n📊 Model Files:")
    for model_file in model_files[:5]:
        rel_path = model_file.relative_to(trade_service_dir)
        print(f"   📊 {rel_path}")
    
    # Look for config files
    config_files = list(trade_service_dir.glob("**/config.py")) + list(trade_service_dir.glob("**/settings.py"))
    print(f"\n⚙️  Config Files:")
    for config_file in config_files:
        rel_path = config_file.relative_to(trade_service_dir)
        print(f"   ⚙️  {rel_path}")
    
    # Look for requirements.txt
    req_files = list(trade_service_dir.glob("**/requirements.txt"))
    print(f"\n📦 Requirements Files:")
    for req_file in req_files:
        rel_path = req_file.relative_to(trade_service_dir)
        print(f"   📦 {rel_path}")
        
        # Show AutoTrader line
        try:
            with open(req_file, 'r') as f:
                lines = f.readlines()
                for line in lines:
                    if 'AutoTrader' in line or 'stocksdeveloper' in line.lower():
                        print(f"      📌 {line.strip()}")
        except Exception:
            pass
    
    print("\n🔍 Searching for StocksDeveloper/AutoTrader Integration:")
    print("-" * 50)
    
    # Search for StocksDeveloper/AutoTrader usage
    py_files = list(trade_service_dir.glob("**/*.py"))
    for py_file in py_files:
        try:
            with open(py_file, 'r') as f:
                content = f.read()
                if 'AutoTrader' in content or 'stocksdeveloper' in content.lower():
                    rel_path = py_file.relative_to(trade_service_dir)
                    print(f"📍 Found in: {rel_path}")
                    
                    # Show relevant lines
                    lines = content.split('\n')
                    for i, line in enumerate(lines):
                        if 'AutoTrader' in line or 'stocksdeveloper' in line.lower():
                            print(f"   Line {i+1}: {line.strip()}")
        except Exception:
            continue
    
    print("\n✅ Discovery Complete!")
    print("=" * 50)
    
    return True

if __name__ == "__main__":
    discover_trade_service_structure()