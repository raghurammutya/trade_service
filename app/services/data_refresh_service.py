import logging
from typing import Dict, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.services.external_order_detector import ExternalOrderDetector
from app.services.trade_service import TradeService
from shared_architecture.utils.redis_data_manager import RedisDataManager

logger = logging.getLogger(__name__)

class DataRefreshService:
    """
    Service that handles periodic data refresh from brokers
    This is where external order detection would be integrated
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.external_detector = ExternalOrderDetector(db)
        self.trade_service = TradeService(db)
        self.redis_manager = RedisDataManager()
        
    async def refresh_account_data(self, pseudo_account: str, 
                                 organization_id: str,
                                 broker_client) -> Dict:
        """
        Main data refresh method called periodically
        
        This method:
        1. Fetches fresh data from broker
        2. Detects external orders
        3. Updates positions and holdings
        4. Syncs to Redis
        5. Updates strategy metrics
        """
        
        logger.info(f"Starting data refresh for {pseudo_account}")
        
        try:
            # Step 1: Fetch fresh data from broker
            fresh_data = await self._fetch_broker_data(broker_client, pseudo_account)
            
            # Step 2: Detect and process external orders
            external_results = await self.external_detector.detect_and_process_external_orders(
                fresh_data['orders'],
                pseudo_account,
                organization_id
            )
            
            # Step 3: Update positions from fresh broker data
            position_updates = await self._update_positions_from_broker(
                fresh_data['positions'], pseudo_account
            )
            
            # Step 4: Update holdings from fresh broker data
            holding_updates = await self._update_holdings_from_broker(
                fresh_data['holdings'], pseudo_account
            )
            
            # Step 5: Sync updated data to Redis
            redis_sync_result = await self._sync_to_redis(pseudo_account, organization_id)
            
            # Step 6: Update strategy metrics
            strategy_updates = await self._update_strategy_metrics(pseudo_account)
            
            refresh_summary = {
                'refresh_timestamp': datetime.utcnow().isoformat(),
                'account': pseudo_account,
                'external_orders': external_results,
                'position_updates': position_updates,
                'holding_updates': holding_updates,
                'redis_sync': redis_sync_result,
                'strategy_updates': strategy_updates,
                'status': 'success'
            }
            
            logger.info(f"Data refresh completed for {pseudo_account}: {external_results['external_orders_detected']} external orders detected")
            return refresh_summary
            
        except Exception as e:
            logger.error(f"Error during data refresh for {pseudo_account}: {str(e)}")
            return {
                'refresh_timestamp': datetime.utcnow().isoformat(),
                'account': pseudo_account,
                'status': 'error',
                'error': str(e)
            }
    
    async def _fetch_broker_data(self, broker_client, pseudo_account: str) -> Dict:
        """Fetch fresh data from broker APIs"""
        
        # This would call actual broker APIs
        # For now, showing the structure
        
        try:
            # Example broker API calls
            orders = await broker_client.get_orders()
            positions = await broker_client.get_positions()
            holdings = await broker_client.get_holdings()
            margins = await broker_client.get_margins()
            
            return {
                'orders': orders,
                'positions': positions,
                'holdings': holdings,
                'margins': margins,
                'fetch_timestamp': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error fetching broker data: {str(e)}")
            raise
    
    async def _update_positions_from_broker(self, broker_positions: List[Dict], 
                                          pseudo_account: str) -> Dict:
        """Update internal positions from broker data"""
        
        from shared_architecture.db.models.position_model import PositionModel
        
        updated_count = 0
        new_count = 0
        
        for broker_pos in broker_positions:
            # Find existing position
            existing_pos = self.db.query(PositionModel).filter(
                PositionModel.pseudo_account == pseudo_account,
                PositionModel.trading_symbol == broker_pos.get('tradingsymbol')
            ).first()
            
            if existing_pos:
                # Update existing position with broker data
                existing_pos.quantity = broker_pos.get('quantity', 0)
                existing_pos.average_price = broker_pos.get('average_price', 0)
                existing_pos.current_price = broker_pos.get('last_price', 0)
                existing_pos.unrealized_pnl = broker_pos.get('pnl', 0)
                existing_pos.updated_at = datetime.utcnow()
                updated_count += 1
            else:
                # Create new position (from external activity)
                new_position = PositionModel(
                    pseudo_account=pseudo_account,
                    trading_symbol=broker_pos.get('tradingsymbol'),
                    instrument_key=broker_pos.get('instrument_key', ''),
                    exchange=broker_pos.get('exchange'),
                    quantity=broker_pos.get('quantity', 0),
                    average_price=broker_pos.get('average_price', 0),
                    current_price=broker_pos.get('last_price', 0),
                    unrealized_pnl=broker_pos.get('pnl', 0),
                    source_type='EXTERNAL_DISCOVERY',
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                self.db.add(new_position)
                new_count += 1
        
        self.db.commit()
        
        return {
            'positions_updated': updated_count,
            'positions_created': new_count,
            'total_positions': len(broker_positions)
        }
    
    async def _update_holdings_from_broker(self, broker_holdings: List[Dict],
                                         pseudo_account: str) -> Dict:
        """Update internal holdings from broker data"""
        
        from shared_architecture.db.models.holding_model import HoldingModel
        
        updated_count = 0
        new_count = 0
        
        for broker_holding in broker_holdings:
            existing_holding = self.db.query(HoldingModel).filter(
                HoldingModel.pseudo_account == pseudo_account,
                HoldingModel.trading_symbol == broker_holding.get('tradingsymbol')
            ).first()
            
            if existing_holding:
                # Update existing holding
                existing_holding.quantity = broker_holding.get('quantity', 0)
                existing_holding.current_price = broker_holding.get('last_price', 0)
                existing_holding.current_value = (
                    broker_holding.get('quantity', 0) * broker_holding.get('last_price', 0)
                )
                existing_holding.pnl = broker_holding.get('pnl', 0)
                existing_holding.updated_at = datetime.utcnow()
                updated_count += 1
            else:
                # Create new holding
                new_holding = HoldingModel(
                    pseudo_account=pseudo_account,
                    trading_symbol=broker_holding.get('tradingsymbol'),
                    instrument_key=broker_holding.get('instrument_key', ''),
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
                self.db.add(new_holding)
                new_count += 1
        
        self.db.commit()
        
        return {
            'holdings_updated': updated_count,
            'holdings_created': new_count,
            'total_holdings': len(broker_holdings)
        }
    
    async def _sync_to_redis(self, pseudo_account: str, organization_id: str) -> Dict:
        """Sync updated data to Redis for fast access"""
        
        try:
            # This would sync all updated data to Redis
            # Using the RedisDataManager
            
            # Get all strategies for the account
            from shared_architecture.db.models.strategy_model import StrategyModel
            strategies = self.db.query(StrategyModel).filter(
                StrategyModel.pseudo_account == pseudo_account,
                StrategyModel.organization_id == organization_id
            ).all()
            
            synced_strategies = 0
            for strategy in strategies:
                # Sync strategy data to Redis
                await self._sync_strategy_to_redis(strategy)
                synced_strategies += 1
            
            return {
                'strategies_synced': synced_strategies,
                'sync_timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error syncing to Redis: {str(e)}")
            return {'error': str(e)}
    
    async def _sync_strategy_to_redis(self, strategy):
        """Sync individual strategy data to Redis"""
        
        # Get strategy positions, orders, holdings
        from shared_architecture.db.models.position_model import PositionModel
        from shared_architecture.db.models.order_model import OrderModel
        from shared_architecture.db.models.holding_model import HoldingModel
        
        positions = self.db.query(PositionModel).filter_by(
            strategy_id=strategy.strategy_id
        ).all()
        
        orders = self.db.query(OrderModel).filter_by(
            strategy_id=strategy.strategy_id
        ).all()
        
        holdings = self.db.query(HoldingModel).filter_by(
            strategy_id=strategy.strategy_id
        ).all()
        
        # Store in Redis using RedisDataManager keys
        redis_key_base = f"strategy:{strategy.organization_id}:{strategy.pseudo_account}:{strategy.strategy_id}"
        
        # Store strategy metadata
        await self.redis_manager.set_data(
            f"{redis_key_base}:meta",
            strategy.to_dict()
        )
        
        # Store positions
        await self.redis_manager.set_data(
            f"{redis_key_base}:positions",
            [pos.to_dict() for pos in positions]
        )
        
        # Store orders  
        await self.redis_manager.set_data(
            f"{redis_key_base}:orders",
            [order.to_dict() for order in orders]
        )
        
        # Store holdings
        await self.redis_manager.set_data(
            f"{redis_key_base}:holdings", 
            [holding.to_dict() for holding in holdings]
        )
        
        # Store real-time metrics
        await self.redis_manager.set_data(
            f"{redis_key_base}:metrics",
            {
                'total_pnl': strategy.total_pnl,
                'unrealized_pnl': strategy.unrealized_pnl,
                'realized_pnl': strategy.realized_pnl,
                'margin_used': strategy.total_margin_used,
                'active_positions': strategy.active_positions_count,
                'active_orders': strategy.active_orders_count,
                'holdings_count': strategy.holdings_count,
                'last_updated': datetime.utcnow().isoformat()
            }
        )
    
    async def _update_strategy_metrics(self, pseudo_account: str) -> Dict:
        """Update metrics for all strategies"""
        
        from app.services.strategy_management_service import StrategyManagementService
        from shared_architecture.db.models.strategy_model import StrategyModel
        
        strategy_service = StrategyManagementService(self.db)
        
        strategies = self.db.query(StrategyModel).filter_by(
            pseudo_account=pseudo_account
        ).all()
        
        updated_count = 0
        for strategy in strategies:
            await strategy_service._update_strategy_metrics(strategy)
            updated_count += 1
        
        return {
            'strategies_updated': updated_count
        }
    
    async def schedule_data_refresh(self, accounts: List[str], interval_minutes: int = 5):
        """
        Schedule periodic data refresh for accounts
        This would be called by a scheduler/cron job
        """
        
        for account in accounts:
            try:
                # This would be called every X minutes
                result = await self.refresh_account_data(account, "stocksblitz", None)
                logger.info(f"Scheduled refresh completed for {account}: {result['status']}")
            except Exception as e:
                logger.error(f"Scheduled refresh failed for {account}: {str(e)}")
                continue