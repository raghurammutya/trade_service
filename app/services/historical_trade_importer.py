import logging
import uuid
import json
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import pandas as pd

from app.utils.kite_symbol_parser import KiteSymbolParser, InstrumentDetails
from app.utils.historical_order_reconstructor import (
    HistoricalOrderReconstructor, ReconstructedOrder, 
    PositionSnapshot, HoldingSnapshot
)
from app.utils.tradebook_parser import TradebookParser

from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.db.models.order_event_model import OrderEventModel
from shared_architecture.db.models.position_model import PositionModel
from shared_architecture.db.models.holding_model import HoldingModel
from shared_architecture.db.models.symbol import Symbol
from shared_architecture.db.models.strategy_model import StrategyModel

from shared_architecture.enums import OrderStatus, OrderEvent, StrategyType, StrategyStatus
from shared_architecture.errors.custom_exceptions import ValidationError

logger = logging.getLogger(__name__)

class ImportResult:
    """Result of historical import operation"""
    def __init__(self, orders_imported: int, trades_imported: int, 
                 positions_calculated: int, holdings_created: int,
                 strategy_created: Optional[str], date_range: Tuple[str, str],
                 symbols_created: int = 0):
        self.orders_imported = orders_imported
        self.trades_imported = trades_imported
        self.positions_calculated = positions_calculated
        self.holdings_created = holdings_created
        self.strategy_created = strategy_created
        self.date_range = date_range
        self.symbols_created = symbols_created
        
    def to_dict(self):
        return {
            'orders_imported': self.orders_imported,
            'trades_imported': self.trades_imported,
            'positions_calculated': self.positions_calculated,
            'holdings_created': self.holdings_created,
            'strategy_created': self.strategy_created,
            'date_range': {
                'start': self.date_range[0],
                'end': self.date_range[1]
            },
            'symbols_created': self.symbols_created
        }


class HistoricalTradeImporter:
    """Service for importing historical trades from tradebook files"""
    
    def __init__(self, db: Session):
        self.db = db
        self.symbol_parser = KiteSymbolParser()
        self.order_reconstructor = HistoricalOrderReconstructor()
        self.tradebook_parser = TradebookParser()
        self._symbol_cache = {}  # Cache for symbol lookups
        
    async def import_tradebook_file(self, file_path: str, pseudo_account: str, 
                                   organization_id: str, create_strategy: bool = True,
                                   strategy_name: Optional[str] = None) -> ImportResult:
        """
        Import historical trades from tradebook Excel file
        
        Args:
            file_path: Path to tradebook Excel file
            pseudo_account: Account identifier
            organization_id: Organization identifier
            create_strategy: Whether to create a historical strategy
            strategy_name: Optional custom strategy name
            
        Returns:
            ImportResult with summary of import
        """
        try:
            logger.info(f"Starting historical import for {pseudo_account} from {file_path}")
            
            # Step 1: Parse tradebook file
            trades_df = self.tradebook_parser.parse_tradebook_file(file_path)
            
            # Validate tradebook integrity
            is_valid, issues = self.tradebook_parser.validate_tradebook_integrity(trades_df)
            if not is_valid:
                logger.warning(f"Tradebook validation issues: {issues}")
            
            # Step 2: Parse symbols and add instrument keys
            trades_df = await self._parse_and_enrich_symbols(trades_df)
            
            # Step 3: Ensure all instruments exist in database
            symbols_created = await self._ensure_instruments_exist(trades_df)
            
            # Step 4: Reconstruct orders from trades
            reconstructed_orders = self.order_reconstructor.reconstruct_orders(trades_df)
            
            # Step 5: Calculate positions and holdings
            final_positions = self.order_reconstructor.calculate_final_positions(trades_df)
            holdings = self.order_reconstructor.calculate_holdings(trades_df)
            
            # Step 6: Create historical strategy if requested
            strategy_id = None
            if create_strategy:
                strategy = await self._create_historical_strategy(
                    pseudo_account, organization_id, trades_df, strategy_name
                )
                strategy_id = strategy.strategy_id
            
            # Step 7: Store all data in database
            await self._store_historical_data(
                reconstructed_orders, final_positions, holdings, 
                pseudo_account, organization_id, strategy_id
            )
            
            # Get date range
            date_range = (
                trades_df['Trade Date'].min().strftime('%Y-%m-%d'),
                trades_df['Trade Date'].max().strftime('%Y-%m-%d')
            )
            
            return ImportResult(
                orders_imported=len(reconstructed_orders),
                trades_imported=len(trades_df),
                positions_calculated=len(final_positions),
                holdings_created=len(holdings),
                strategy_created=strategy_id,
                date_range=date_range,
                symbols_created=symbols_created
            )
            
        except Exception as e:
            logger.error(f"Error importing historical trades: {str(e)}")
            self.db.rollback()
            raise
    
    async def import_multiple_tradebooks(self, file_paths: List[str], pseudo_account: str,
                                       organization_id: str, create_strategy: bool = True,
                                       strategy_name: Optional[str] = None) -> ImportResult:
        """Import multiple tradebook files for the same account"""
        try:
            # Parse all files and combine
            combined_df = self.tradebook_parser.parse_multiple_files(file_paths)
            
            # Process combined data
            combined_df = await self._parse_and_enrich_symbols(combined_df)
            symbols_created = await self._ensure_instruments_exist(combined_df)
            
            reconstructed_orders = self.order_reconstructor.reconstruct_orders(combined_df)
            final_positions = self.order_reconstructor.calculate_final_positions(combined_df)
            holdings = self.order_reconstructor.calculate_holdings(combined_df)
            
            strategy_id = None
            if create_strategy:
                strategy = await self._create_historical_strategy(
                    pseudo_account, organization_id, combined_df, strategy_name
                )
                strategy_id = strategy.strategy_id
            
            await self._store_historical_data(
                reconstructed_orders, final_positions, holdings,
                pseudo_account, organization_id, strategy_id
            )
            
            date_range = (
                combined_df['Trade Date'].min().strftime('%Y-%m-%d'),
                combined_df['Trade Date'].max().strftime('%Y-%m-%d')
            )
            
            return ImportResult(
                orders_imported=len(reconstructed_orders),
                trades_imported=len(combined_df),
                positions_calculated=len(final_positions),
                holdings_created=len(holdings),
                strategy_created=strategy_id,
                date_range=date_range,
                symbols_created=symbols_created
            )
            
        except Exception as e:
            logger.error(f"Error importing multiple tradebooks: {str(e)}")
            self.db.rollback()
            raise
    
    async def _parse_and_enrich_symbols(self, trades_df: pd.DataFrame) -> pd.DataFrame:
        """Parse Kite symbols and add instrument_key column"""
        instrument_keys = []
        
        for _, trade in trades_df.iterrows():
            try:
                # Parse symbol
                instrument_details = self.symbol_parser.parse_symbol(
                    trade['Symbol'],
                    trade['Exchange'],
                    trade['Segment'],
                    trade.get('Expiry Date')
                )
                instrument_keys.append(instrument_details.instrument_key)
            except Exception as e:
                logger.error(f"Error parsing symbol {trade['Symbol']}: {str(e)}")
                # Use a fallback instrument key
                instrument_keys.append(f"{trade['Exchange']}@{trade['Symbol']}@unknown")
        
        trades_df['instrument_key'] = instrument_keys
        return trades_df
    
    async def _ensure_instruments_exist(self, trades_df: pd.DataFrame) -> int:
        """Ensure all instruments exist in the database"""
        symbols_created = 0
        
        # Get unique instruments
        unique_instruments = trades_df.groupby(['Symbol', 'Exchange', 'Segment']).first()
        
        for (symbol, exchange, segment), row in unique_instruments.iterrows():
            instrument_key = row['instrument_key']
            
            # Check cache first
            if instrument_key in self._symbol_cache:
                continue
            
            # Check database
            existing = self.db.query(Symbol).filter_by(
                instrument_key=instrument_key
            ).first()
            
            if existing:
                self._symbol_cache[instrument_key] = existing
                continue
            
            # Parse and create new symbol
            try:
                instrument_details = self.symbol_parser.parse_symbol(
                    symbol, exchange, segment, row.get('Expiry Date')
                )
                
                # Extract details from instrument key
                key_parts = self.symbol_parser.extract_details_from_instrument_key(instrument_key)
                
                new_symbol = Symbol(
                    instrument_key=instrument_key,
                    symbol=symbol,  # Use 'symbol' not 'trading_symbol'
                    exchange_code=exchange,  # Use 'exchange_code' not 'exchange'
                    product_type=segment,  # Use 'product_type' for segment
                    instrument_type=instrument_details.instrument_type,
                    isin_code=row.get('ISIN') if pd.notna(row.get('ISIN')) else None,  # Use 'isin_code'
                    first_added_datetime=datetime.now().date(),
                    refresh_flag=True
                )
                
                # Add derivative-specific fields
                if instrument_details.instrument_type in ['OPTION', 'FUTURE']:
                    new_symbol.expiry_date = datetime.strptime(
                        instrument_details.expiry_date, '%d-%b-%Y'
                    ).date() if instrument_details.expiry_date else None
                    
                    if instrument_details.instrument_type == 'OPTION':
                        new_symbol.strike_price = instrument_details.strike_price
                        new_symbol.option_type = instrument_details.option_type
                
                self.db.add(new_symbol)
                symbols_created += 1
                self._symbol_cache[instrument_key] = new_symbol
                
            except Exception as e:
                logger.error(f"Error creating symbol {symbol}: {str(e)}")
                continue
        
        self.db.commit()
        logger.info(f"Created {symbols_created} new symbols")
        return symbols_created
    
    async def _create_historical_strategy(self, pseudo_account: str, organization_id: str,
                                        trades_df: pd.DataFrame, 
                                        strategy_name: Optional[str] = None) -> StrategyModel:
        """Create a historical strategy for imported trades"""
        if not strategy_name:
            date_range = f"{trades_df['Trade Date'].min().strftime('%Y%m%d')}-{trades_df['Trade Date'].max().strftime('%Y%m%d')}"
            strategy_name = f"Historical Import {date_range}"
        
        strategy_id = f"HIST_{uuid.uuid4().hex[:8].upper()}"
        
        # Calculate strategy metrics
        summary = self.tradebook_parser.get_tradebook_summary(trades_df)
        
        strategy = StrategyModel(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            pseudo_account=pseudo_account,
            organization_id=organization_id,
            strategy_type=StrategyType.MANUAL.value,
            status=StrategyStatus.COMPLETED.value,
            description=f"Historical trades imported from {summary['date_range']['start']} to {summary['date_range']['end']}",
            tags=['historical', 'import', f"symbols_{summary['unique_symbols']}"],
            configuration={
                'import_summary': summary,
                'source_files': trades_df['source_file'].unique().tolist()
            },
            created_by='HISTORICAL_IMPORT',
            started_at=pd.to_datetime(trades_df['Trade Date'].min()),
            ended_at=pd.to_datetime(trades_df['Trade Date'].max())
        )
        
        self.db.add(strategy)
        self.db.commit()
        
        logger.info(f"Created historical strategy: {strategy_id}")
        return strategy
    
    async def _store_historical_data(self, orders: List[ReconstructedOrder],
                                   positions: Dict[str, PositionSnapshot],
                                   holdings: List[HoldingSnapshot],
                                   pseudo_account: str, organization_id: str,
                                   strategy_id: Optional[str] = None):
        """Store all historical data in TimescaleDB"""
        try:
            # Store orders
            for order in orders:
                # Check if order already exists (using exchange_order_id for Option 1)
                existing_order = self.db.query(OrderModel).filter_by(
                    exchange_order_id=order.original_order_id,
                    pseudo_account=pseudo_account
                ).first()
                
                if existing_order:
                    logger.warning(f"Order {order.original_order_id} already exists, skipping")
                    continue
                
                # Map to existing OrderModel fields (Option 1 approach)
                order_model = OrderModel(
                    # Use exchange_order_id instead of order_id
                    exchange_order_id=order.original_order_id,
                    pseudo_account=pseudo_account,
                    # Use symbol instead of trading_symbol  
                    symbol=order.trading_symbol,
                    instrument_key=order.instrument_key,
                    exchange=order.exchange,
                    order_type=order.order_type,
                    trade_type=order.trade_type,
                    quantity=order.quantity,
                    price=order.price,
                    trigger_price=0.0,
                    status=order.status,
                    filled_quantity=order.filled_quantity,
                    average_price=order.avg_fill_price,
                    strategy_id=strategy_id,
                    product_type=order.product_type,
                    validity="DAY",
                    variety="regular",
                    # Use timestamp instead of created_at
                    timestamp=order.created_at,
                    modified_time=order.updated_at,
                    # Map additional required fields with defaults
                    amo=False,
                    client_id=pseudo_account,
                    disclosed_quantity=0,
                    pending_quantity=0,
                    platform="ZERODHA",
                    platform_time=order.created_at,
                    exchange_time=order.created_at,
                    stock_broker="ZERODHA",
                    trading_account=pseudo_account,
                    # Store metadata in comments
                    comments=f"Trade ID: {order.original_order_id}, Historical Import: {order.source_type}"
                )
                self.db.add(order_model)
                
                # Flush to get the order ID for events
                self.db.flush()
                
                # Create order events
                events = self.order_reconstructor.create_order_events([order])
                for event in events:
                    order_event = OrderEventModel(
                        order_id=order_model.id,  # Use the database ID, not external order_id
                        event_type=event['event_type'],
                        timestamp=event['event_time'],  # Use 'timestamp' not 'event_timestamp'
                        details=json.dumps(event['details']) if event['details'] else None  # Convert dict to JSON string
                        # Note: pseudo_account and organization_id are not fields in OrderEventModel
                    )
                    self.db.add(order_event)
            
            # Store current positions (final state)
            for symbol, position in positions.items():
                if position.quantity == 0:
                    continue  # Skip closed positions
                
                position_model = PositionModel(
                    pseudo_account=pseudo_account,
                    # No organization_id field in PositionModel
                    symbol=position.trading_symbol,  # Use 'symbol' not 'trading_symbol'
                    instrument_key=position.instrument_key,
                    exchange=position.exchange,
                    # No segment field in PositionModel
                    net_quantity=position.quantity,  # Use 'net_quantity' for main quantity
                    buy_quantity=position.buy_quantity,
                    sell_quantity=position.sell_quantity,
                    buy_value=position.buy_value,
                    sell_value=position.sell_value,
                    realised_pnl=position.realized_pnl,  # Use 'realised_pnl' not 'realized_pnl'
                    unrealised_pnl=0.0,  # Use 'unrealised_pnl' not 'unrealized_pnl'  
                    strategy_id=strategy_id,
                    # No product_type field in PositionModel, using type instead
                    type=position.product_type,
                    # No source_type field in PositionModel
                    # No created_at field, using timestamp 
                    timestamp=position.snapshot_time,
                    # Additional required fields for PositionModel
                    platform="ZERODHA",
                    stock_broker="ZERODHA",
                    trading_account=pseudo_account,
                    state="ACTIVE"
                )
                self.db.add(position_model)
            
            # Store holdings (settled equity positions)
            for holding in holdings:
                holding_model = HoldingModel(
                    pseudo_account=pseudo_account,
                    # No organization_id field in HoldingModel
                    symbol=holding.trading_symbol,  # Use 'symbol' not 'trading_symbol'
                    instrument_key=holding.instrument_key,
                    exchange=holding.exchange,
                    isin=holding.isin,
                    quantity=holding.quantity,
                    avg_price=holding.average_price,  # Use 'avg_price' not 'average_price'
                    ltp=holding.last_price,  # Use 'ltp' for current price
                    current_value=holding.quantity * holding.last_price,
                    pnl=holding.pnl,
                    strategy_id=strategy_id,
                    # No source_type field in HoldingModel
                    # Use timestamp instead of created_at/updated_at
                    timestamp=holding.settlement_date,
                    # Additional required fields
                    trading_account=pseudo_account,
                    platform="ZERODHA",
                    stock_broker="ZERODHA",
                    product="CNC"  # For equity holdings
                )
                self.db.add(holding_model)
            
            self.db.commit()
            logger.info(f"Stored {len(orders)} orders, {len(positions)} positions, {len(holdings)} holdings")
            
        except Exception as e:
            logger.error(f"Error storing historical data: {str(e)}")
            self.db.rollback()
            raise
    
    def get_import_preview(self, file_path: str) -> Dict:
        """Get preview of what will be imported without actually importing"""
        try:
            # Parse file
            trades_df = self.tradebook_parser.parse_tradebook_file(file_path)
            
            # Get summary
            summary = self.tradebook_parser.get_tradebook_summary(trades_df)
            
            # Sample symbol parsing
            sample_symbols = []
            for _, trade in trades_df.head(10).iterrows():
                try:
                    details = self.symbol_parser.parse_symbol(
                        trade['Symbol'], trade['Exchange'], 
                        trade['Segment'], trade.get('Expiry Date')
                    )
                    sample_symbols.append({
                        'original': trade['Symbol'],
                        'instrument_key': details.instrument_key,
                        'type': details.instrument_type
                    })
                except Exception as e:
                    sample_symbols.append({
                        'original': trade['Symbol'],
                        'error': str(e)
                    })
            
            return {
                'summary': summary,
                'sample_symbols': sample_symbols,
                'validation': self.tradebook_parser.validate_tradebook_integrity(trades_df)
            }
            
        except Exception as e:
            logger.error(f"Error generating import preview: {str(e)}")
            raise