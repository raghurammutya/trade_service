#!/usr/bin/env python3
"""
Quick debug script to see what config is being loaded
"""

import sys
import os

# Add path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def debug_config():
    print("🔍 Debugging Trade Service Configuration")
    print("=" * 50)
    
    # Load environment if .env.live exists
    env_file = ".env.live"
    if os.path.exists(env_file):
        print("📄 Loading .env.live...")
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
    
    # Import and load config
    from shared_architecture.config.config_loader import config_loader
    
    print("📋 Loading config for trade_service...")
    config_loader.load("trade_service")
    
    # Test the key connection settings
    connection_vars = [
        'REDIS_HOST', 'REDIS_PORT', 'REDIS_URL',
        'MONGODB_HOST', 'MONGODB_PORT', 'MONGODB_URI',
        'TIMESCALEDB_HOST', 'TIMESCALEDB_PORT', 'TIMESCALEDB_DB', 'TIMESCALEDB_USER',
        'RABBITMQ_HOST', 'RABBITMQ_PORT'
    ]
    
    print("\n🔍 Configuration Values:")
    print("-" * 30)
    
    for var in connection_vars:
        env_val = os.getenv(var, 'NOT_SET')
        config_val = config_loader.get(var, 'NOT_SET', scope='all')
        
        status = "✅" if config_val != 'NOT_SET' else "❌"
        print(f"{status} {var}:")
        print(f"    ENV: {env_val}")
        print(f"    CONFIG: {config_val}")
        
        if config_val in ['redis', 'mongo', 'rabbitmq']:
            print(f"    ⚠️  WARNING: Using Docker hostname instead of localhost!")
        print()
    
    print("📋 Config Sources:")
    print(f"    Common config: {list(config_loader.common_config.keys())}")
    print(f"    Shared config: {list(config_loader.shared_config.keys())}")  
    print(f"    Private config: {list(config_loader.private_config.keys())}")
    
    # Test connection clients
    print("\n🔍 Testing Connection Clients:")
    print("-" * 30)
    
    try:
        from shared_architecture.connections.redis_client import get_redis_client
        redis_client = get_redis_client()
        print(f"✅ Redis client created: {type(redis_client)}")
        # Try to see connection details
        connection_pool = getattr(redis_client, 'connection_pool', None)
        if connection_pool:
            print(f"    Host: {getattr(connection_pool.connection_kwargs, 'host', 'unknown')}")
            print(f"    Port: {getattr(connection_pool.connection_kwargs, 'port', 'unknown')}")
    except Exception as e:
        print(f"❌ Redis client error: {e}")
    
    try:
        from shared_architecture.connections.mongodb_client import get_mongo_client
        mongo_client = get_mongo_client()
        print(f"✅ MongoDB client created: {type(mongo_client)}")
        # Try to see connection details
        print(f"    Address: {getattr(mongo_client, 'address', 'unknown')}")
    except Exception as e:
        print(f"❌ MongoDB client error: {e}")
    
    try:
        from shared_architecture.connections.timescaledb_client import get_sync_timescaledb_session
        timescale_session = get_sync_timescaledb_session()
        print(f"✅ TimescaleDB session created: {type(timescale_session)}")
        # Try to see connection details
        engine = timescale_session.bind # type: ignore
        print(f"    URL: {engine.url}")
    except Exception as e:
        print(f"❌ TimescaleDB session error: {e}")

if __name__ == "__main__":
    debug_config()