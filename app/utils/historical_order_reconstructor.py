import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

@dataclass
class ReconstructedOrder:
    """Represents a reconstructed historical order"""
    order_id: str
    original_order_id: str
    trading_symbol: str
    instrument_key: str
    exchange: str
    segment: str
    order_type: str  # MARKET, LIMIT, etc.
    trade_type: str  # BUY, SELL
    quantity: int
    price: float
    status: str  # COMPLETE
    created_at: datetime
    updated_at: datetime
    filled_quantity: int
    avg_fill_price: float
    trades: List[Dict] = field(default_factory=list)
    source_type: str = "HISTORICAL_IMPORT"
    isin: Optional[str] = None
    product_type: str = "CNC"  # Default for historical trades
    
    def to_dict(self):
        return {
            'order_id': self.order_id,
            'original_order_id': self.original_order_id,
            'trading_symbol': self.trading_symbol,
            'instrument_key': self.instrument_key,
            'exchange': self.exchange,
            'segment': self.segment,
            'order_type': self.order_type,
            'trade_type': self.trade_type,
            'quantity': self.quantity,
            'price': self.price,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'filled_quantity': self.filled_quantity,
            'avg_fill_price': self.avg_fill_price,
            'num_trades': len(self.trades),
            'source_type': self.source_type,
            'isin': self.isin,
            'product_type': self.product_type
        }

@dataclass
class PositionSnapshot:
    """Represents a position at a specific point in time"""
    trading_symbol: str
    instrument_key: str
    exchange: str
    segment: str
    quantity: int
    average_price: float
    snapshot_time: datetime
    buy_quantity: int
    sell_quantity: int
    buy_value: float
    sell_value: float
    realized_pnl: float = 0.0
    product_type: str = "CNC"
    
    def to_dict(self):
        return {
            'trading_symbol': self.trading_symbol,
            'instrument_key': self.instrument_key,
            'exchange': self.exchange,
            'segment': self.segment,
            'quantity': self.quantity,
            'average_price': self.average_price,
            'snapshot_time': self.snapshot_time.isoformat(),
            'buy_quantity': self.buy_quantity,
            'sell_quantity': self.sell_quantity,
            'buy_value': self.buy_value,
            'sell_value': self.sell_value,
            'realized_pnl': self.realized_pnl,
            'product_type': self.product_type
        }

@dataclass
class HoldingSnapshot:
    """Represents holdings (T+1 settled positions)"""
    trading_symbol: str
    instrument_key: str
    exchange: str
    isin: Optional[str]
    quantity: int
    average_price: float
    last_price: float
    pnl: float
    settlement_date: datetime
    
    def to_dict(self):
        return {
            'trading_symbol': self.trading_symbol,
            'instrument_key': self.instrument_key,
            'exchange': self.exchange,
            'isin': self.isin,
            'quantity': self.quantity,
            'average_price': self.average_price,
            'last_price': self.last_price,
            'pnl': self.pnl,
            'settlement_date': self.settlement_date.isoformat()
        }


class HistoricalOrderReconstructor:
    """Reconstructs orders from individual trades"""
    
    def __init__(self):
        self.position_tracker = {}  # Track positions by symbol
        self.holding_tracker = {}   # Track holdings (T+1 settled)
        
    def reconstruct_orders(self, trades_df: pd.DataFrame) -> List[ReconstructedOrder]:
        """
        Reconstruct orders from individual trades
        
        Args:
            trades_df: DataFrame with trade data
            
        Returns:
            List of reconstructed orders
        """
        orders = []
        
        # Group trades by Order ID
        grouped = trades_df.groupby('Order ID')
        
        for order_id, trade_group in grouped:
            # Sort trades by execution time
            trade_group = trade_group.sort_values('Order Execution Time')
            
            # Calculate order-level metrics
            total_quantity = trade_group['Quantity'].sum()
            
            # Weighted average price
            trade_values = trade_group['Quantity'] * trade_group['Price']
            avg_price = trade_values.sum() / total_quantity
            
            # Get first and last trade info
            first_trade = trade_group.iloc[0]
            last_trade = trade_group.iloc[-1]
            
            # Extract created_at and updated_at timestamps
            created_at = pd.to_datetime(first_trade['Order Execution Time'])
            updated_at = pd.to_datetime(last_trade['Order Execution Time'])
            
            # Determine product type based on segment
            product_type = self._determine_product_type(first_trade['Segment'])
            
            # Create reconstructed order with proper type conversion
            order = ReconstructedOrder(
                order_id=f"HIST_{order_id}",
                original_order_id=str(order_id),
                trading_symbol=str(first_trade['Symbol']),
                instrument_key=first_trade.get('instrument_key', ''),  # Will be populated later
                exchange=str(first_trade['Exchange']),
                segment=str(first_trade['Segment']),
                order_type="MARKET",  # Assume market orders for historical
                trade_type=str(first_trade['Trade Type']).upper(),
                quantity=int(total_quantity),  # Convert numpy int64 to Python int
                price=float(avg_price),  # Convert numpy float64 to Python float
                status="COMPLETE",
                created_at=created_at,
                updated_at=updated_at,
                filled_quantity=int(total_quantity),  # Convert numpy int64 to Python int
                avg_fill_price=float(avg_price),  # Convert numpy float64 to Python float
                trades=trade_group.to_dict('records'),
                isin=str(first_trade.get('ISIN')) if pd.notna(first_trade.get('ISIN')) else None,
                product_type=product_type,
                source_type="HISTORICAL_IMPORT"
            )
            
            orders.append(order)
            
        logger.info(f"Reconstructed {len(orders)} orders from {len(trades_df)} trades")
        return orders
    
    def calculate_positions_timeline(self, trades_df: pd.DataFrame) -> List[PositionSnapshot]:
        """
        Calculate position snapshots over time
        
        Args:
            trades_df: DataFrame with trade data
            
        Returns:
            List of position snapshots showing position evolution
        """
        snapshots = []
        
        # Sort trades by execution time
        trades_sorted = trades_df.sort_values('Order Execution Time')
        
        # Initialize position tracker
        positions = {}
        
        for _, trade in trades_sorted.iterrows():
            symbol = trade['Symbol']
            instrument_key = trade.get('instrument_key', '')
            
            # Initialize position if not exists
            if symbol not in positions:
                positions[symbol] = {
                    'quantity': 0,
                    'buy_value': 0.0,
                    'sell_value': 0.0,
                    'buy_quantity': 0,
                    'sell_quantity': 0,
                    'exchange': trade['Exchange'],
                    'segment': trade['Segment'],
                    'instrument_key': instrument_key,
                    'realized_pnl': 0.0
                }
            
            pos = positions[symbol]
            trade_value = trade['Quantity'] * trade['Price']
            
            # Update position based on trade type
            if trade['Trade Type'].lower() == 'buy':
                pos['quantity'] += trade['Quantity']
                pos['buy_value'] += trade_value
                pos['buy_quantity'] += trade['Quantity']
            else:  # sell
                # Calculate realized PnL for sell trades
                if pos['quantity'] > 0:
                    # FIFO basis PnL calculation
                    avg_buy_price = pos['buy_value'] / pos['buy_quantity'] if pos['buy_quantity'] > 0 else 0
                    realized_pnl = (trade['Price'] - avg_buy_price) * min(trade['Quantity'], pos['quantity'])
                    pos['realized_pnl'] += realized_pnl
                
                pos['quantity'] -= trade['Quantity']
                pos['sell_value'] += trade_value
                pos['sell_quantity'] += trade['Quantity']
            
            # Calculate average price
            if pos['quantity'] > 0:
                net_buy_value = pos['buy_value'] - (pos['sell_value'] * (pos['buy_quantity'] - pos['quantity']) / pos['sell_quantity'] if pos['sell_quantity'] > 0 else 0)
                avg_price = net_buy_value / pos['quantity']
            elif pos['quantity'] < 0:
                # Short position
                net_sell_value = pos['sell_value'] - (pos['buy_value'] * (pos['sell_quantity'] + pos['quantity']) / pos['buy_quantity'] if pos['buy_quantity'] > 0 else 0)
                avg_price = net_sell_value / abs(pos['quantity'])
            else:
                avg_price = 0
            
            # Create snapshot with type conversion
            snapshot = PositionSnapshot(
                trading_symbol=str(symbol),
                instrument_key=instrument_key,
                exchange=str(pos['exchange']),
                segment=str(pos['segment']),
                quantity=int(pos['quantity']),  # Convert numpy int64 to Python int
                average_price=float(avg_price),  # Convert numpy float64 to Python float
                snapshot_time=pd.to_datetime(trade['Order Execution Time']),
                buy_quantity=int(pos['buy_quantity']),  # Convert numpy int64 to Python int
                sell_quantity=int(pos['sell_quantity']),  # Convert numpy int64 to Python int
                buy_value=float(pos['buy_value']),  # Convert numpy float64 to Python float
                sell_value=float(pos['sell_value']),  # Convert numpy float64 to Python float
                realized_pnl=float(pos['realized_pnl']),  # Convert numpy float64 to Python float
                product_type=self._determine_product_type(pos['segment'])
            )
            
            snapshots.append(snapshot)
        
        return snapshots
    
    def calculate_final_positions(self, trades_df: pd.DataFrame) -> Dict[str, PositionSnapshot]:
        """
        Calculate final positions after all trades
        
        Returns:
            Dictionary of final positions by symbol
        """
        # Get all snapshots
        all_snapshots = self.calculate_positions_timeline(trades_df)
        
        # Group by symbol and get last snapshot for each
        final_positions = {}
        for snapshot in all_snapshots:
            final_positions[snapshot.trading_symbol] = snapshot
        
        # Filter out closed positions (quantity = 0)
        open_positions = {
            symbol: pos for symbol, pos in final_positions.items() 
            if pos.quantity != 0
        }
        
        return open_positions
    
    def calculate_holdings(self, trades_df: pd.DataFrame, cutoff_date: Optional[datetime] = None) -> List[HoldingSnapshot]:
        """
        Calculate holdings (T+1 settled equity positions)
        
        Args:
            trades_df: DataFrame with trade data
            cutoff_date: Consider trades before this date as settled
            
        Returns:
            List of holding snapshots
        """
        holdings = []
        
        # Filter only equity trades
        equity_trades = trades_df[trades_df['Segment'] == 'EQ'].copy()
        
        if equity_trades.empty:
            return holdings
        
        # If no cutoff date, use T-1 from today
        if cutoff_date is None:
            cutoff_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Filter trades that would have settled (T+1)
        equity_trades['Trade Date'] = pd.to_datetime(equity_trades['Trade Date'])
        settled_trades = equity_trades[equity_trades['Trade Date'] < cutoff_date]
        
        if settled_trades.empty:
            return holdings
        
        # Group by symbol and calculate holdings
        grouped = settled_trades.groupby('Symbol')
        
        for symbol, trades in grouped:
            buy_trades = trades[trades['Trade Type'].str.lower() == 'buy']
            sell_trades = trades[trades['Trade Type'].str.lower() == 'sell']
            
            buy_quantity = buy_trades['Quantity'].sum() if not buy_trades.empty else 0
            sell_quantity = sell_trades['Quantity'].sum() if not sell_trades.empty else 0
            
            net_quantity = buy_quantity - sell_quantity
            
            if net_quantity > 0:
                # Calculate average price for holdings
                buy_value = (buy_trades['Quantity'] * buy_trades['Price']).sum() if not buy_trades.empty else 0
                sell_value = (sell_trades['Quantity'] * sell_trades['Price']).sum() if not sell_trades.empty else 0
                
                # FIFO average price calculation
                if buy_quantity > 0:
                    avg_price = buy_value / buy_quantity
                else:
                    avg_price = 0
                
                # Get latest trade info
                latest_trade = trades.iloc[-1]
                
                holding = HoldingSnapshot(
                    trading_symbol=str(symbol),
                    instrument_key=latest_trade.get('instrument_key', ''),
                    exchange=str(latest_trade['Exchange']),
                    isin=str(latest_trade.get('ISIN')) if pd.notna(latest_trade.get('ISIN')) else None,
                    quantity=int(net_quantity),  # Convert numpy int64 to Python int
                    average_price=float(avg_price),  # Convert numpy float64 to Python float
                    last_price=float(latest_trade['Price']),  # Convert numpy float64 to Python float
                    pnl=float((latest_trade['Price'] - avg_price) * net_quantity),  # Convert to Python float
                    settlement_date=latest_trade['Trade Date'] + pd.Timedelta(days=1)
                )
                
                holdings.append(holding)
        
        return holdings
    
    def create_order_events(self, orders: List[ReconstructedOrder]) -> List[Dict]:
        """
        Create order events for audit trail
        
        Args:
            orders: List of reconstructed orders
            
        Returns:
            List of order events
        """
        events = []
        
        for order in orders:
            # Create ORDER_PLACED event
            events.append({
                'order_id': order.order_id,
                'event_type': 'ORDER_PLACED',
                'event_time': order.created_at,
                'details': {
                    'quantity': order.quantity,
                    'price': order.price,
                    'order_type': order.order_type,
                    'trade_type': order.trade_type
                }
            })
            
            # Create fill events for each trade
            for trade in order.trades:
                events.append({
                    'order_id': order.order_id,
                    'event_type': 'ORDER_FILLED',
                    'event_time': pd.to_datetime(trade['Order Execution Time']),
                    'details': {
                        'trade_id': trade['Trade ID'],
                        'quantity': trade['Quantity'],
                        'price': trade['Price']
                    }
                })
            
            # Create ORDER_COMPLETE event
            events.append({
                'order_id': order.order_id,
                'event_type': 'ORDER_COMPLETE',
                'event_time': order.updated_at,
                'details': {
                    'filled_quantity': order.filled_quantity,
                    'avg_fill_price': order.avg_fill_price
                }
            })
        
        return events
    
    def _determine_product_type(self, segment: str) -> str:
        """Determine product type based on segment"""
        if segment == 'EQ':
            return 'CNC'  # Cash and Carry for equity
        elif segment == 'FO':
            return 'NRML'  # Normal for F&O
        elif segment == 'COM':
            return 'NRML'  # Normal for commodities
        else:
            return 'MIS'  # Default to MIS
    
    def generate_import_summary(self, orders: List[ReconstructedOrder], 
                               positions: Dict[str, PositionSnapshot],
                               holdings: List[HoldingSnapshot]) -> Dict:
        """Generate summary of import process"""
        
        # Aggregate statistics
        total_buy_value = sum(o.quantity * o.avg_fill_price for o in orders if o.trade_type == 'BUY')
        total_sell_value = sum(o.quantity * o.avg_fill_price for o in orders if o.trade_type == 'SELL')
        
        # Position statistics
        long_positions = [p for p in positions.values() if p.quantity > 0]
        short_positions = [p for p in positions.values() if p.quantity < 0]
        
        # Realized PnL
        total_realized_pnl = sum(p.realized_pnl for p in positions.values())
        
        return {
            'orders': {
                'total_count': len(orders),
                'buy_orders': len([o for o in orders if o.trade_type == 'BUY']),
                'sell_orders': len([o for o in orders if o.trade_type == 'SELL']),
                'total_buy_value': total_buy_value,
                'total_sell_value': total_sell_value
            },
            'positions': {
                'open_positions': len(positions),
                'long_positions': len(long_positions),
                'short_positions': len(short_positions),
                'total_realized_pnl': total_realized_pnl
            },
            'holdings': {
                'total_count': len(holdings),
                'total_value': sum(h.quantity * h.last_price for h in holdings),
                'total_pnl': sum(h.pnl for h in holdings)
            },
            'segments': {
                'equity': len([o for o in orders if o.segment == 'EQ']),
                'fo': len([o for o in orders if o.segment == 'FO']),
                'commodity': len([o for o in orders if o.segment == 'COM'])
            }
        }