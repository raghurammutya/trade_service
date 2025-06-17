"""
Enhanced sync task that includes automatic external order detection
This replaces the manual endpoint approach with automatic detection during refresh
"""

import logging
from datetime import datetime
from typing import List, Dict

from app.core.celery_config import celery_app
from app.utils.celery_db_helper import get_celery_db_session
from app.services.external_order_detector import ExternalOrderDetector
from shared_architecture.connections.connection_manager import connection_manager
from shared_architecture.db.models.order_model import OrderModel

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def sync_account_with_external_detection(self, organization_id: str, pseudo_account: str):
    """
    Enhanced sync that automatically detects external orders during refresh
    
    This task:
    1. Fetches fresh data from broker APIs
    2. Automatically detects external orders (orders not in our DB)
    3. Creates missing order records with events
    4. Updates positions and holdings
    5. Syncs everything to Redis
    
    Should be called every 5-10 minutes for each account
    """
    db = get_celery_db_session()
    
    try:
        logger.info(f"Starting enhanced sync for {pseudo_account} with external detection")
        
        # Step 1: Get broker client (this would be your actual broker API client)
        broker_client = await get_broker_client(pseudo_account)
        if not broker_client:
            logger.warning(f"No broker client available for {pseudo_account}")
            return {"status": "skipped", "reason": "No broker client"}
        
        # Step 2: Fetch fresh data from broker
        fresh_data = await fetch_broker_data(broker_client, pseudo_account)
        
        # Step 3: Detect and process external orders
        external_detector = ExternalOrderDetector(db)
        external_results = await external_detector.detect_and_process_external_orders(
            fresh_data.get('orders', []),
            pseudo_account,
            organization_id
        )
        
        # Step 4: Update positions from broker data
        position_updates = await update_positions_from_broker(
            db, fresh_data.get('positions', []), pseudo_account
        )
        
        # Step 5: Update holdings from broker data  
        holding_updates = await update_holdings_from_broker(
            db, fresh_data.get('holdings', []), pseudo_account
        )
        
        # Step 6: Sync to Redis (call existing task)
        from app.tasks.sync_to_redis_task import sync_account_to_redis
        redis_result = sync_account_to_redis.delay(organization_id, pseudo_account)
        
        # Step 7: Update strategy metrics if external orders were found
        if external_results['external_orders_detected'] > 0:
            await update_affected_strategy_metrics(db, pseudo_account)
        
        result = {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "account": pseudo_account,
            "external_orders_detected": external_results['external_orders_detected'],
            "position_updates": position_updates,
            "holding_updates": holding_updates,
            "redis_sync_id": redis_result.id,
            "total_broker_orders": len(fresh_data.get('orders', [])),
            "total_broker_positions": len(fresh_data.get('positions', [])),
            "total_broker_holdings": len(fresh_data.get('holdings', []))
        }
        
        if external_results['external_orders_detected'] > 0:
            logger.warning(
                f"🚨 Detected {external_results['external_orders_detected']} external orders for {pseudo_account}"
            )
        
        logger.info(f"Enhanced sync completed for {pseudo_account}: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Enhanced sync failed for {pseudo_account}: {e}")
        raise self.retry(exc=e)
    finally:
        db.close()

async def get_broker_client(pseudo_account: str):
    """
    Get the appropriate broker client for the account
    This would return your Zerodha/Upstox/etc. API client
    """
    # TODO: Implement actual broker client factory
    # For now, return None (simulation mode)
    return None

async def fetch_broker_data(broker_client, pseudo_account: str) -> Dict:
    """
    Fetch fresh data from broker APIs
    
    In production, this would make actual API calls:
    - orders = await broker_client.orders()
    - positions = await broker_client.positions()  
    - holdings = await broker_client.holdings()
    """
    
    if broker_client is None:
        # Simulation mode - return empty data
        logger.info(f"Simulation mode: no broker client for {pseudo_account}")
        return {
            'orders': [],
            'positions': [],
            'holdings': [],
            'margins': [],
            'fetch_timestamp': datetime.utcnow()
        }
    
    try:
        # Real broker API calls would go here
        orders = await broker_client.orders()
        positions = await broker_client.positions()
        holdings = await broker_client.holdings()
        margins = await broker_client.margins()
        
        return {
            'orders': orders,
            'positions': positions,
            'holdings': holdings,
            'margins': margins,
            'fetch_timestamp': datetime.utcnow()
        }
        
    except Exception as e:
        logger.error(f"Error fetching broker data: {e}")
        return {
            'orders': [],
            'positions': [],
            'holdings': [],
            'margins': [],
            'error': str(e)
        }

async def update_positions_from_broker(db, broker_positions: List[Dict], pseudo_account: str) -> Dict:
    """Update internal positions with fresh broker data"""
    
    from shared_architecture.db.models.position_model import PositionModel
    
    updated_count = 0
    new_count = 0
    
    for broker_pos in broker_positions:
        existing_pos = db.query(PositionModel).filter(
            PositionModel.pseudo_account == pseudo_account,
            PositionModel.trading_symbol == broker_pos.get('tradingsymbol')
        ).first()
        
        if existing_pos:
            # Update existing position
            existing_pos.quantity = broker_pos.get('quantity', 0)
            existing_pos.current_price = broker_pos.get('last_price', 0)
            existing_pos.unrealized_pnl = broker_pos.get('pnl', 0)
            existing_pos.updated_at = datetime.utcnow()
            updated_count += 1
        else:
            # New position detected (from external activity)
            if broker_pos.get('quantity', 0) != 0:
                new_position = PositionModel(
                    pseudo_account=pseudo_account,
                    trading_symbol=broker_pos.get('tradingsymbol'),
                    exchange=broker_pos.get('exchange'),
                    quantity=broker_pos.get('quantity', 0),
                    average_price=broker_pos.get('average_price', 0),
                    current_price=broker_pos.get('last_price', 0),
                    unrealized_pnl=broker_pos.get('pnl', 0),
                    source_type='EXTERNAL_DISCOVERY',
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(new_position)
                new_count += 1
    
    db.commit()
    return {"updated": updated_count, "new": new_count}

async def update_holdings_from_broker(db, broker_holdings: List[Dict], pseudo_account: str) -> Dict:
    """Update internal holdings with fresh broker data"""
    
    from shared_architecture.db.models.holding_model import HoldingModel
    
    updated_count = 0
    new_count = 0
    
    for broker_holding in broker_holdings:
        existing_holding = db.query(HoldingModel).filter(
            HoldingModel.pseudo_account == pseudo_account,
            HoldingModel.trading_symbol == broker_holding.get('tradingsymbol')
        ).first()
        
        if existing_holding:
            # Update existing holding
            existing_holding.current_price = broker_holding.get('last_price', 0)
            existing_holding.current_value = (
                broker_holding.get('quantity', 0) * broker_holding.get('last_price', 0)
            )
            existing_holding.pnl = broker_holding.get('pnl', 0)
            existing_holding.updated_at = datetime.utcnow()
            updated_count += 1
        else:
            # New holding detected
            if broker_holding.get('quantity', 0) > 0:
                new_holding = HoldingModel(
                    pseudo_account=pseudo_account,
                    trading_symbol=broker_holding.get('tradingsymbol'),
                    exchange=broker_holding.get('exchange'),
                    quantity=broker_holding.get('quantity', 0),
                    average_price=broker_holding.get('average_price', 0),
                    current_price=broker_holding.get('last_price', 0),
                    current_value=broker_holding.get('quantity', 0) * broker_holding.get('last_price', 0),
                    pnl=broker_holding.get('pnl', 0),
                    source_type='EXTERNAL_DISCOVERY',
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                db.add(new_holding)
                new_count += 1
    
    db.commit()
    return {"updated": updated_count, "new": new_count}

async def update_affected_strategy_metrics(db, pseudo_account: str):
    """Update strategy metrics when external orders are detected"""
    
    from app.services.strategy_management_service import StrategyManagementService
    from shared_architecture.db.models.strategy_model import StrategyModel
    
    # Get all active strategies for the account
    strategies = db.query(StrategyModel).filter(
        StrategyModel.pseudo_account == pseudo_account,
        StrategyModel.status == 'ACTIVE'
    ).all()
    
    strategy_service = StrategyManagementService(db)
    
    for strategy in strategies:
        await strategy_service._update_strategy_metrics(strategy)
    
    logger.info(f"Updated metrics for {len(strategies)} strategies")

@celery_app.task(bind=True)
def sync_all_accounts_with_external_detection(self):
    """
    Enhanced version of sync_all_accounts that includes external detection
    
    This should replace sync_all_accounts_to_redis in your scheduler
    Schedule to run every 5-10 minutes
    """
    db = get_celery_db_session()
    
    try:
        # Get unique accounts
        account_data = db.query(
            OrderModel.pseudo_account,
            OrderModel.organization_id
        ).distinct().all()
        
        synced_count = 0
        
        for pseudo_account, organization_id in account_data:
            if pseudo_account and organization_id:
                # Queue enhanced sync task for each account
                sync_account_with_external_detection.delay(organization_id, pseudo_account)
                synced_count += 1
        
        logger.info(f"Queued enhanced sync tasks for {synced_count} accounts")
        return {"status": "success", "accounts_queued": synced_count}
        
    except Exception as e:
        logger.error(f"Failed to queue enhanced sync tasks: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()