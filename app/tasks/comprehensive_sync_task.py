"""
Comprehensive sync task that integrates:
1. Position/holdings generation from orderbook
2. External order detection
3. Redis cluster support  
4. RabbitMQ notifications
5. Configurable sync frequency
"""

import logging
from datetime import datetime, date
from typing import List, Dict, Optional
import json
import os

from app.core.celery_config import celery_app
from app.utils.celery_db_helper import get_celery_db_session
from app.services.position_holdings_generator import PositionHoldingsGenerator
from app.services.external_order_detector import ExternalOrderDetector
from shared_architecture.utils.redis_data_manager import RedisDataManager
from shared_architecture.connections.connection_manager import connection_manager
from shared_architecture.db.models.order_model import OrderModel

logger = logging.getLogger(__name__)

# Configuration parameters
EXTERNAL_ORDER_CHECK_INTERVAL = int(os.getenv('EXTERNAL_ORDER_CHECK_MINUTES', '30'))  # Default 30 minutes
POSITION_GENERATION_ENABLED = os.getenv('POSITION_GENERATION_ENABLED', 'true').lower() == 'true'
RABBITMQ_NOTIFICATIONS_ENABLED = os.getenv('RABBITMQ_NOTIFICATIONS_ENABLED', 'true').lower() == 'true'

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def comprehensive_account_sync(self, organization_id: str, pseudo_account: str, 
                             force_position_regeneration: bool = False,
                             check_external_orders: bool = True):
    """
    Comprehensive sync that includes all functionality:
    1. Position/holdings generation from orderbook 
    2. External order detection
    3. Data sync to Redis (with cluster support)
    4. RabbitMQ notifications
    
    Args:
        organization_id: Organization identifier
        pseudo_account: Account to sync
        force_position_regeneration: Force regeneration even if recent
        check_external_orders: Whether to check for external orders
    """
    db = get_celery_db_session()
    
    try:
        logger.info(f"Starting comprehensive sync for {pseudo_account}")
        
        sync_results = {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "account": pseudo_account,
            "position_generation": {},
            "external_detection": {},
            "redis_sync": {},
            "notifications": {},
            "errors": []
        }
        
        # Step 1: Position/Holdings Generation from Orderbook
        if POSITION_GENERATION_ENABLED:
            try:
                position_results = generate_positions_from_orders(
                    db, pseudo_account, force_position_regeneration
                )
                sync_results["position_generation"] = position_results
                logger.info(f"Position generation completed: {position_results}")
            except Exception as e:
                error_msg = f"Position generation failed: {e}"
                logger.error(error_msg)
                sync_results["errors"].append(error_msg)
        
        # Step 2: External Order Detection
        if check_external_orders:
            try:
                external_results = detect_external_orders(
                    db, pseudo_account, organization_id
                )
                sync_results["external_detection"] = external_results
                
                if external_results.get('external_orders_detected', 0) > 0:
                    logger.warning(
                        f"🚨 Detected {external_results['external_orders_detected']} external orders for {pseudo_account}"
                    )
            except Exception as e:
                error_msg = f"External order detection failed: {e}"
                logger.error(error_msg)
                sync_results["errors"].append(error_msg)
        
        # Step 3: Redis Sync with Cluster Support
        try:
            redis_results = sync_to_redis_cluster(
                db, organization_id, pseudo_account
            )
            sync_results["redis_sync"] = redis_results
            logger.info(f"Redis sync completed: {redis_results}")
        except Exception as e:
            error_msg = f"Redis sync failed: {e}"
            logger.error(error_msg)
            sync_results["errors"].append(error_msg)
        
        # Step 4: RabbitMQ Notifications
        if RABBITMQ_NOTIFICATIONS_ENABLED:
            try:
                notification_results = send_sync_notifications(
                    sync_results, pseudo_account
                )
                sync_results["notifications"] = notification_results
            except Exception as e:
                error_msg = f"Notification failed: {e}"
                logger.error(error_msg)
                sync_results["errors"].append(error_msg)
        
        # Update status based on errors
        if sync_results["errors"]:
            sync_results["status"] = "partial_success" if any([
                sync_results["position_generation"], 
                sync_results["redis_sync"]
            ]) else "failed"
        
        logger.info(f"Comprehensive sync completed for {pseudo_account}: {sync_results}")
        return sync_results
        
    except Exception as e:
        logger.error(f"Comprehensive sync failed for {pseudo_account}: {e}")
        raise self.retry(exc=e)
    finally:
        db.close()

def generate_positions_from_orders(db, pseudo_account: str, force_regeneration: bool = False) -> Dict:
    """
    Generate positions and holdings from order history using FIFO logic
    """
    try:
        generator = PositionHoldingsGenerator(db)
        
        # Check if we need to regenerate
        should_regenerate = force_regeneration
        
        if not should_regenerate:
            # Check last generation time
            last_sync = get_last_position_generation_time(db, pseudo_account)
            if not last_sync or (datetime.utcnow() - last_sync).total_seconds() > 3600:  # 1 hour
                should_regenerate = True
        
        if should_regenerate:
            logger.info(f"Regenerating positions/holdings for {pseudo_account}")
            
            result = generator.regenerate_positions_and_holdings(
                pseudo_account=pseudo_account,
                target_date=None,  # Use current date
                include_intraday=True
            )
            
            # Update last generation time
            update_last_position_generation_time(db, pseudo_account)
            
            return {
                "regenerated": True,
                "positions_updated": result.get("positions_updated", 0),
                "holdings_updated": result.get("holdings_updated", 0),
                "orders_processed": result.get("orders_processed", 0),
                "generation_time": datetime.utcnow().isoformat()
            }
        else:
            return {
                "regenerated": False,
                "reason": "Recent generation found, skipping",
                "last_generation": last_sync.isoformat() if last_sync else None
            }
            
    except Exception as e:
        logger.error(f"Position generation error for {pseudo_account}: {e}")
        raise

def detect_external_orders(db, pseudo_account: str, organization_id: str) -> Dict:
    """
    Detect orders placed outside the system
    """
    try:
        # Get broker client (AutoTrader connection)
        broker_client = get_broker_client(pseudo_account)
        if not broker_client:
            return {
                "external_orders_detected": 0,
                "reason": "No broker client available",
                "status": "skipped"
            }
        
        # Fetch fresh orders from broker
        fresh_orders = fetch_broker_orders(broker_client, pseudo_account)
        
        # Detect external orders
        external_detector = ExternalOrderDetector(db)
        detection_results = external_detector.detect_and_process_external_orders(
            fresh_orders,
            pseudo_account,
            organization_id
        )
        
        return {
            "external_orders_detected": detection_results.get('external_orders_detected', 0),
            "orders_created": detection_results.get('orders_created', 0),
            "events_created": detection_results.get('events_created', 0),
            "total_broker_orders": len(fresh_orders),
            "status": "completed"
        }
        
    except Exception as e:
        logger.error(f"External order detection error for {pseudo_account}: {e}")
        raise

def sync_to_redis_cluster(db, organization_id: str, pseudo_account: str) -> Dict:
    """
    Sync data to Redis with cluster support
    """
    try:
        # Get Redis connection with cluster support
        redis_conn = get_redis_cluster_connection()
        if not redis_conn:
            logger.warning("Redis cluster connection not available, trying single Redis")
            redis_conn = connection_manager.get_redis_connection()
        
        if not redis_conn:
            return {
                "status": "failed",
                "reason": "No Redis connection available"
            }
        
        redis_manager = RedisDataManager(redis_conn)
        
        # Import models
        from shared_architecture.db.models.position_model import PositionModel
        from shared_architecture.db.models.holding_model import HoldingModel
        from shared_architecture.db.models.order_model import OrderModel
        from shared_architecture.db.models.margin_model import MarginModel
        
        # Get all data for account
        positions = db.query(PositionModel).filter_by(pseudo_account=pseudo_account).all()
        holdings = db.query(HoldingModel).filter_by(pseudo_account=pseudo_account).all()
        orders = db.query(OrderModel).filter_by(pseudo_account=pseudo_account).all()
        margins = db.query(MarginModel).filter_by(pseudo_account=pseudo_account).all()
        
        # Store in Redis (handles cluster internally)
        redis_manager.store_positions(organization_id, pseudo_account, positions)
        redis_manager.store_holdings(organization_id, pseudo_account, holdings)
        redis_manager.store_orders(organization_id, pseudo_account, orders)
        redis_manager.store_margins(organization_id, pseudo_account, margins)
        
        # Also store strategy-specific data
        strategies = set()
        for item in positions + holdings + orders:
            if hasattr(item, 'strategy_id') and item.strategy_id:
                strategies.add(item.strategy_id)
        
        for strategy_id in strategies:
            if strategy_id and strategy_id != 'default':
                strat_positions = [p for p in positions if p.strategy_id == strategy_id]
                strat_holdings = [h for h in holdings if h.strategy_id == strategy_id]
                strat_orders = [o for o in orders if o.strategy_id == strategy_id]
                strat_margins = [m for m in margins if getattr(m, 'strategy_id', None) == strategy_id]
                
                redis_manager.store_positions(organization_id, pseudo_account, strat_positions, strategy_id)
                redis_manager.store_holdings(organization_id, pseudo_account, strat_holdings, strategy_id)
                redis_manager.store_orders(organization_id, pseudo_account, strat_orders, strategy_id)
                redis_manager.store_margins(organization_id, pseudo_account, strat_margins, strategy_id)
        
        return {
            "status": "success",
            "positions_stored": len(positions),
            "holdings_stored": len(holdings),
            "orders_stored": len(orders),
            "margins_stored": len(margins),
            "strategies_stored": len(strategies),
            "redis_type": "cluster" if is_redis_cluster() else "single"
        }
        
    except Exception as e:
        logger.error(f"Redis sync error for {pseudo_account}: {e}")
        raise

def send_sync_notifications(sync_results: Dict, pseudo_account: str) -> Dict:
    """
    Send notifications via RabbitMQ instead of Telegram
    """
    try:
        # Get RabbitMQ connection
        rabbitmq_conn = connection_manager.get_rabbitmq_connection()
        if not rabbitmq_conn:
            return {
                "status": "failed",
                "reason": "RabbitMQ connection not available"
            }
        
        # Create notification message
        notification = {
            "type": "sync_completed",
            "account": pseudo_account,
            "timestamp": datetime.utcnow().isoformat(),
            "summary": {
                "status": sync_results["status"],
                "position_generation": sync_results.get("position_generation", {}),
                "external_orders": sync_results.get("external_detection", {}).get("external_orders_detected", 0),
                "redis_status": sync_results.get("redis_sync", {}).get("status", "unknown"),
                "errors": len(sync_results.get("errors", []))
            },
            "full_results": sync_results
        }
        
        # Publish to RabbitMQ
        channel = rabbitmq_conn.channel()
        
        # Declare exchange for sync notifications
        channel.exchange_declare(exchange='sync_notifications', exchange_type='topic')
        
        # Publish message
        routing_key = f"account.{pseudo_account}.sync_completed"
        channel.basic_publish(
            exchange='sync_notifications',
            routing_key=routing_key,
            body=json.dumps(notification),
            properties=pika.BasicProperties(
                delivery_mode=2,  # Make message persistent
                content_type='application/json'
            )
        )
        
        logger.info(f"Sync notification sent for {pseudo_account} via RabbitMQ")
        
        return {
            "status": "success",
            "channel": "rabbitmq",
            "exchange": "sync_notifications",
            "routing_key": routing_key,
            "message_sent": True
        }
        
    except Exception as e:
        logger.error(f"RabbitMQ notification error for {pseudo_account}: {e}")
        return {
            "status": "failed",
            "error": str(e)
        }

def get_redis_cluster_connection():
    """
    Get Redis cluster connection for production environments
    """
    try:
        environment = os.getenv('ENVIRONMENT', 'local').lower()
        
        if environment == 'production':
            # Production Redis cluster configuration
            redis_cluster_hosts = os.getenv('REDIS_CLUSTER_HOSTS', '')
            if redis_cluster_hosts:
                from rediscluster import RedisCluster
                
                # Parse cluster hosts
                hosts = []
                for host_port in redis_cluster_hosts.split(','):
                    if ':' in host_port:
                        host, port = host_port.strip().split(':')
                        hosts.append({'host': host, 'port': int(port)})
                
                if hosts:
                    cluster = RedisCluster(
                        startup_nodes=hosts,
                        decode_responses=True,
                        skip_full_coverage_check=True,
                        health_check_interval=30
                    )
                    logger.info(f"Connected to Redis cluster with {len(hosts)} nodes")
                    return cluster
        
        # Fallback to single Redis
        return None
        
    except Exception as e:
        logger.error(f"Redis cluster connection failed: {e}")
        return None

def is_redis_cluster() -> bool:
    """Check if we're using Redis cluster"""
    environment = os.getenv('ENVIRONMENT', 'local').lower()
    return environment == 'production' and bool(os.getenv('REDIS_CLUSTER_HOSTS'))

def get_broker_client(pseudo_account: str):
    """Get broker client for account"""
    # TODO: Implement actual broker client factory based on account type
    # For now, return None (simulation mode)
    return None

def fetch_broker_orders(broker_client, pseudo_account: str) -> List[Dict]:
    """Fetch orders from broker API"""
    if broker_client is None:
        return []
    
    try:
        # Real broker API call would go here
        orders = broker_client.orders()
        return orders
    except Exception as e:
        logger.error(f"Error fetching broker orders: {e}")
        return []

def get_last_position_generation_time(db, pseudo_account: str) -> Optional[datetime]:
    """Get last position generation timestamp"""
    # This would query a metadata table
    # For now, return None to always regenerate
    return None

def update_last_position_generation_time(db, pseudo_account: str):
    """Update last position generation timestamp"""
    # This would update a metadata table
    pass

@celery_app.task(bind=True)
def sync_all_accounts_comprehensive(self):
    """
    Enhanced periodic task that runs comprehensive sync for all accounts
    
    This task replaces both sync_all_accounts_to_redis and 
    sync_all_accounts_with_external_detection
    
    Frequency: Every 5 minutes for position generation and Redis sync
    External order detection: Configurable (default 30 minutes)
    """
    db = get_celery_db_session()
    
    try:
        # Get unique accounts
        account_data = db.query(
            OrderModel.pseudo_account,
            OrderModel.organization_id
        ).distinct().all()
        
        synced_count = 0
        current_time = datetime.utcnow()
        
        for pseudo_account, organization_id in account_data:
            if pseudo_account and organization_id:
                # Determine if we should check external orders
                check_external = should_check_external_orders(pseudo_account, current_time)
                
                # Queue comprehensive sync task for each account
                comprehensive_account_sync.delay(
                    organization_id, 
                    pseudo_account,
                    force_position_regeneration=False,
                    check_external_orders=check_external
                )
                synced_count += 1
        
        logger.info(f"Queued comprehensive sync tasks for {synced_count} accounts")
        return {
            "status": "success", 
            "accounts_queued": synced_count,
            "external_order_check_interval": EXTERNAL_ORDER_CHECK_INTERVAL
        }
        
    except Exception as e:
        logger.error(f"Failed to queue comprehensive sync tasks: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()

def should_check_external_orders(pseudo_account: str, current_time: datetime) -> bool:
    """
    Determine if we should check external orders based on configurable frequency
    """
    # Simple time-based check - could be enhanced with per-account tracking
    minute = current_time.minute
    return minute % EXTERNAL_ORDER_CHECK_INTERVAL == 0

# Import pika for RabbitMQ
try:
    import pika
except ImportError:
    logger.warning("pika not available, RabbitMQ notifications disabled")
    RABBITMQ_NOTIFICATIONS_ENABLED = False