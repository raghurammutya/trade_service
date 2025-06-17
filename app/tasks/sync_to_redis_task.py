# app/tasks/sync_to_redis_task.py
import logging
from datetime import datetime
from typing import List, Dict

from app.core.celery_config import celery_app
from app.utils.celery_db_helper import get_celery_db_session
from app.utils.redis_data_manager import RedisDataManager
from shared_architecture.connections.connection_manager import connection_manager
from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.db.models.position_model import PositionModel
from shared_architecture.db.models.holding_model import HoldingModel
from shared_architecture.db.models.margin_model import MarginModel

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def sync_account_to_redis(self, organization_id: str, pseudo_account: str, strategy_id: str = None):
    """
    Sync account data from TimescaleDB to Redis
    Can sync all data or specific strategy data
    """
    db = get_celery_db_session()
    
    try:
        # Get Redis connection
        redis_conn = connection_manager.get_redis_connection()
        if not redis_conn:
            logger.warning("Redis connection not available, skipping sync")
            return {"status": "skipped", "reason": "Redis not available"}
        
        redis_manager = RedisDataManager(redis_conn)
        
        if strategy_id:
            # Sync specific strategy
            logger.info(f"Syncing strategy {strategy_id} for {pseudo_account}")
            
            positions = db.query(PositionModel).filter_by(
                pseudo_account=pseudo_account,
                strategy_id=strategy_id
            ).all()
            
            holdings = db.query(HoldingModel).filter_by(
                pseudo_account=pseudo_account,
                strategy_id=strategy_id
            ).all()
            
            orders = db.query(OrderModel).filter_by(
                pseudo_account=pseudo_account,
                strategy_id=strategy_id
            ).all()
            
            margins = db.query(MarginModel).filter_by(
                pseudo_account=pseudo_account,
                strategy_id=strategy_id
            ).all()
            
            # Store in Redis with strategy context
            redis_manager.store_positions(organization_id, pseudo_account, positions, strategy_id)
            redis_manager.store_holdings(organization_id, pseudo_account, holdings, strategy_id)
            redis_manager.store_orders(organization_id, pseudo_account, orders, strategy_id)
            redis_manager.store_margins(organization_id, pseudo_account, margins, strategy_id)
            
            counts = {
                "positions": len(positions),
                "holdings": len(holdings),
                "orders": len(orders),
                "margins": len(margins)
            }
            
        else:
            # Sync all data
            logger.info(f"Syncing all data for {pseudo_account}")
            
            # Get all data
            all_positions = db.query(PositionModel).filter_by(pseudo_account=pseudo_account).all()
            all_holdings = db.query(HoldingModel).filter_by(pseudo_account=pseudo_account).all()
            all_orders = db.query(OrderModel).filter_by(pseudo_account=pseudo_account).all()
            all_margins = db.query(MarginModel).filter_by(pseudo_account=pseudo_account).all()
            
            # Group by strategy
            strategies = set()
            for item in all_positions + all_holdings + all_orders + all_margins:
                if hasattr(item, 'strategy_id') and item.strategy_id:
                    strategies.add(item.strategy_id)
            
            # Store blanket data (no strategy)
            blanket_positions = [p for p in all_positions if not p.strategy_id or p.strategy_id == 'default']
            blanket_holdings = [h for h in all_holdings if not h.strategy_id or h.strategy_id == 'default']
            blanket_orders = [o for o in all_orders if not o.strategy_id or o.strategy_id == 'default']
            blanket_margins = [m for m in all_margins if not m.strategy_id or m.strategy_id == 'default']
            
            redis_manager.store_positions(organization_id, pseudo_account, blanket_positions)
            redis_manager.store_holdings(organization_id, pseudo_account, blanket_holdings)
            redis_manager.store_orders(organization_id, pseudo_account, blanket_orders)
            redis_manager.store_margins(organization_id, pseudo_account, blanket_margins)
            
            # Store strategy-specific data
            for strat_id in strategies:
                if strat_id and strat_id != 'default':
                    strat_positions = [p for p in all_positions if p.strategy_id == strat_id]
                    strat_holdings = [h for h in all_holdings if h.strategy_id == strat_id]
                    strat_orders = [o for o in all_orders if o.strategy_id == strat_id]
                    strat_margins = [m for m in all_margins if m.strategy_id == strat_id]
                    
                    redis_manager.store_positions(organization_id, pseudo_account, strat_positions, strat_id)
                    redis_manager.store_holdings(organization_id, pseudo_account, strat_holdings, strat_id)
                    redis_manager.store_orders(organization_id, pseudo_account, strat_orders, strat_id)
                    redis_manager.store_margins(organization_id, pseudo_account, strat_margins, strat_id)
            
            counts = {
                "total_positions": len(all_positions),
                "total_holdings": len(all_holdings),
                "total_orders": len(all_orders),
                "total_margins": len(all_margins),
                "strategies": len(strategies)
            }
        
        logger.info(f"Successfully synced data to Redis: {counts}")
        return {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "counts": counts
        }
        
    except Exception as e:
        logger.error(f"Failed to sync to Redis: {e}")
        # Retry the task
        raise self.retry(exc=e)
    finally:
        db.close()

@celery_app.task(bind=True)
def sync_all_accounts_to_redis(self):
    """
    Periodic task to sync all accounts to Redis
    Should be scheduled to run periodically (e.g., every 5 minutes)
    """
    db = get_celery_db_session()
    
    try:
        # Get unique organization/account combinations
        account_data = db.query(
            OrderModel.pseudo_account,
            OrderModel.organization_id
        ).distinct().all()
        
        synced_count = 0
        
        for pseudo_account, organization_id in account_data:
            if pseudo_account and organization_id:
                # Queue sync task for each account
                sync_account_to_redis.delay(organization_id, pseudo_account)
                synced_count += 1
        
        logger.info(f"Queued sync tasks for {synced_count} accounts")
        return {"status": "success", "accounts_queued": synced_count}
        
    except Exception as e:
        logger.error(f"Failed to queue sync tasks: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()

@celery_app.task(bind=True)
def sync_on_data_change(self, organization_id: str, pseudo_account: str, data_type: str, strategy_id: str = None):
    """
    Sync specific data type when it changes
    Called after order execution, position updates, etc.
    
    Args:
        data_type: 'positions', 'holdings', 'orders', or 'margins'
    """
    db = get_celery_db_session()
    
    try:
        redis_conn = connection_manager.get_redis_connection()
        if not redis_conn:
            return {"status": "skipped", "reason": "Redis not available"}
        
        redis_manager = RedisDataManager(redis_conn)
        
        # Query specific data type
        if data_type == 'positions':
            query = db.query(PositionModel).filter_by(pseudo_account=pseudo_account)
            if strategy_id:
                query = query.filter_by(strategy_id=strategy_id)
            data = query.all()
            redis_manager.store_positions(organization_id, pseudo_account, data, strategy_id)
            
        elif data_type == 'holdings':
            query = db.query(HoldingModel).filter_by(pseudo_account=pseudo_account)
            if strategy_id:
                query = query.filter_by(strategy_id=strategy_id)
            data = query.all()
            redis_manager.store_holdings(organization_id, pseudo_account, data, strategy_id)
            
        elif data_type == 'orders':
            query = db.query(OrderModel).filter_by(pseudo_account=pseudo_account)
            if strategy_id:
                query = query.filter_by(strategy_id=strategy_id)
            data = query.all()
            redis_manager.store_orders(organization_id, pseudo_account, data, strategy_id)
            
        elif data_type == 'margins':
            query = db.query(MarginModel).filter_by(pseudo_account=pseudo_account)
            if strategy_id:
                query = query.filter_by(strategy_id=strategy_id)
            data = query.all()
            redis_manager.store_margins(organization_id, pseudo_account, data, strategy_id)
            
        else:
            return {"status": "error", "error": f"Unknown data type: {data_type}"}
        
        logger.info(f"Synced {len(data)} {data_type} to Redis for {pseudo_account}")
        return {
            "status": "success",
            "data_type": data_type,
            "count": len(data),
            "strategy_id": strategy_id
        }
        
    except Exception as e:
        logger.error(f"Failed to sync {data_type}: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()