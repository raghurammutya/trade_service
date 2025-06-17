#!/usr/bin/env python3
"""
Manual script to create database tables with proper enum handling
"""

import os
import sys
sys.path.append('/home/stocksadmin/stocksblitz/trade_service')
sys.path.append('/home/stocksadmin/stocksblitz')

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import enum

# Database connection
DATABASE_URL = "postgresql://tradmin:tradpass@localhost:5432/tradingdb"

def create_enum_type(engine, enum_name, enum_values):
    """Create PostgreSQL ENUM type if it doesn't exist"""
    with engine.connect() as conn:
        # Check if enum exists
        result = conn.execute(text("""
            SELECT 1 FROM pg_type WHERE typname = :enum_name
        """), {"enum_name": enum_name})
        
        if not result.fetchone():
            # Create enum type
            values_str = "', '".join(enum_values)
            enum_sql = f"CREATE TYPE {enum_name} AS ENUM ('{values_str}')"
            print(f"Creating enum: {enum_sql}")
            conn.execute(text(enum_sql))
            conn.commit()
            print(f"✅ Created enum type: {enum_name}")
        else:
            print(f"ℹ️  Enum type {enum_name} already exists")

def create_tables():
    """Create all necessary database tables"""
    print("🔧 Creating database tables manually...")
    
    engine = create_engine(DATABASE_URL)
    
    # Create required enum types first
    create_enum_type(engine, 'order_transition_type', [
        'NONE', 'HOLDING_TO_POSITION', 'POSITION_TO_HOLDING'
    ])
    
    # Create tables with SQL directly to avoid enum issues
    with engine.connect() as conn:
        # Create orders table
        orders_sql = """
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            amo BOOLEAN,
            average_price DOUBLE PRECISION,
            client_id VARCHAR,
            disclosed_quantity INTEGER,
            exchange VARCHAR,
            exchange_order_id VARCHAR,
            exchange_time TIMESTAMP WITH TIME ZONE,
            filled_quantity INTEGER,
            independent_exchange VARCHAR,
            independent_symbol VARCHAR,
            modified_time TIMESTAMP WITH TIME ZONE,
            nest_request_id VARCHAR,
            order_type VARCHAR,
            parent_order_id INTEGER,
            pending_quantity INTEGER,
            platform VARCHAR,
            platform_time TIMESTAMP WITH TIME ZONE,
            price DOUBLE PRECISION,
            pseudo_account VARCHAR,
            publisher_id VARCHAR,
            status VARCHAR,
            status_message VARCHAR,
            stock_broker VARCHAR,
            symbol VARCHAR,
            trade_type VARCHAR,
            trading_account VARCHAR,
            trigger_price DOUBLE PRECISION,
            validity VARCHAR,
            variety VARCHAR NOT NULL,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            instrument_key VARCHAR,
            strategy_id VARCHAR,
            transition_type order_transition_type DEFAULT 'NONE',
            quantity INTEGER,
            target DOUBLE PRECISION,
            stoploss DOUBLE PRECISION,
            trailing_stoploss DOUBLE PRECISION,
            comments VARCHAR,
            product_type VARCHAR,
            position_category VARCHAR,
            position_type VARCHAR
        )
        """
        
        # Create order_events table
        order_events_sql = """
        CREATE TABLE IF NOT EXISTS order_events (
            id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(id),
            event_type VARCHAR,
            timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            details VARCHAR
        )
        """
        
        print("Creating orders table...")
        conn.execute(text(orders_sql))
        
        print("Creating order_events table...")
        conn.execute(text(order_events_sql))
        
        conn.commit()
        print("✅ Database tables created successfully!")

if __name__ == "__main__":
    try:
        create_tables()
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        sys.exit(1)