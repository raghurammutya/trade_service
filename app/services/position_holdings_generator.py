"""
Position and Holdings Generator Service

This service regenerates position and holdings data from order history.
It's essential for:
1. Historical data reconstruction when AutoTrader data is not available
2. Reducing API calls to AutoTrader by computing positions internally
3. End-of-day conversion of equity/bond positions to holdings
4. Handling holding exits that become intraday positions

Business Logic:
- Equity/Bond positions convert to holdings at end of day
- Holdings exits become intraday positions until end of day
- Derivatives (F&O) don't convert to holdings
- FIFO-based PnL calculation for realized profits/losses
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, time, date
from collections import defaultdict
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from shared_architecture.db.models.order_model import OrderModel
from shared_architecture.db.models.position_model import PositionModel
from shared_architecture.db.models.holding_model import HoldingModel
from shared_architecture.db.models.symbol import Symbol
from shared_architecture.enums import TradeType, ProductType

logger = logging.getLogger(__name__)

class PositionHoldingsGenerator:
    """Generate positions and holdings from order data"""
    
    def __init__(self, db: Session):
        self.db = db
        
    def regenerate_positions_and_holdings(
        self, 
        pseudo_account: str, 
        target_date: Optional[date] = None,
        include_intraday: bool = True
    ) -> Dict[str, Any]:
        """
        Main entry point to regenerate positions and holdings for an account
        
        Args:
            pseudo_account: Account to process
            target_date: Date to calculate positions for (default: today)
            include_intraday: Whether to include intraday positions
            
        Returns:
            Dict containing generated positions, holdings, and statistics
        """
        if target_date is None:
            target_date = date.today()
            
        logger.info(f"Regenerating positions/holdings for {pseudo_account} on {target_date}")
        
        try:
            # Get all orders up to target date
            orders = self._get_orders_for_account(pseudo_account, target_date)
            logger.info(f"Found {len(orders)} orders for processing")
            
            # Generate positions from orders
            positions_data = self._calculate_positions_from_orders(orders, target_date, include_intraday)
            
            # Generate holdings from orders (for equities/bonds)
            holdings_data = self._calculate_holdings_from_orders(orders, target_date)
            
            # Update database with generated data
            positions_updated = self._update_positions_in_db(positions_data, pseudo_account)
            holdings_updated = self._update_holdings_in_db(holdings_data, pseudo_account)
            
            result = {
                "pseudo_account": pseudo_account,
                "target_date": target_date.isoformat(),
                "orders_processed": len(orders),
                "positions_generated": len(positions_data),
                "holdings_generated": len(holdings_data),
                "positions_updated": positions_updated,
                "holdings_updated": holdings_updated,
                "summary": {
                    "total_position_value": sum(p.get('net_value', 0) for p in positions_data.values()),
                    "total_holdings_value": sum(h.get('current_value', 0) for h in holdings_data.values()),
                    "active_positions": len([p for p in positions_data.values() if p.get('net_quantity', 0) != 0]),
                    "total_holdings": len(holdings_data)
                }
            }
            
            logger.info(f"Regeneration complete: {result['summary']}")
            return result
            
        except Exception as e:
            logger.error(f"Error regenerating positions/holdings: {str(e)}")
            raise
    
    def _get_orders_for_account(self, pseudo_account: str, target_date: date) -> List[OrderModel]:
        """Get all completed orders for account up to target date"""
        
        # Convert target_date to datetime for comparison
        target_datetime = datetime.combine(target_date, time.max)
        
        orders = self.db.query(OrderModel).filter(
            and_(
                OrderModel.pseudo_account == pseudo_account,
                OrderModel.status == 'COMPLETE',
                OrderModel.timestamp <= target_datetime
            )
        ).order_by(OrderModel.timestamp.asc()).all()
        
        return orders
    
    def _calculate_positions_from_orders(
        self, 
        orders: List[OrderModel], 
        target_date: date,
        include_intraday: bool
    ) -> Dict[str, Dict]:
        """
        Calculate net positions from order history using FIFO logic
        
        Returns:
            Dict[symbol, position_data]
        """
        positions = defaultdict(lambda: {
            'symbol': '',
            'exchange': '',
            'instrument_key': '',
            'buy_quantity': 0,
            'sell_quantity': 0,
            'buy_value': 0.0,
            'sell_value': 0.0,
            'buy_avg_price': 0.0,
            'sell_avg_price': 0.0,
            'net_quantity': 0,
            'net_value': 0.0,
            'realized_pnl': 0.0,
            'unrealized_pnl': 0.0,
            'ltp': 0.0,
            'type': 'NRML',
            'direction': 'NONE',
            'trade_history': []  # For FIFO calculation
        })
        
        # Group orders by symbol
        symbol_orders = defaultdict(list)
        for order in orders:
            # Skip if it's an equity/bond and we're looking at holdings conversion
            if not include_intraday and self._is_equity_or_bond(order.symbol):
                continue
                
            symbol_orders[order.symbol].append(order)
        
        # Process each symbol's orders chronologically
        for symbol, symbol_order_list in symbol_orders.items():
            position_data = positions[symbol]
            position_data['symbol'] = symbol
            
            if symbol_order_list:
                position_data['exchange'] = symbol_order_list[0].exchange
                position_data['instrument_key'] = symbol_order_list[0].instrument_key
                position_data['type'] = symbol_order_list[0].product_type or 'NRML'
            
            # Process orders chronologically with FIFO logic
            self._process_orders_fifo(position_data, symbol_order_list)
            
            # Calculate averages
            if position_data['buy_quantity'] > 0:
                position_data['buy_avg_price'] = position_data['buy_value'] / position_data['buy_quantity']
            if position_data['sell_quantity'] > 0:
                position_data['sell_avg_price'] = position_data['sell_value'] / position_data['sell_quantity']
            
            # Set direction based on net quantity
            if position_data['net_quantity'] > 0:
                position_data['direction'] = 'BUY'
            elif position_data['net_quantity'] < 0:
                position_data['direction'] = 'SELL'
            else:
                position_data['direction'] = 'NONE'
        
        # Filter out zero positions if needed
        active_positions = {k: v for k, v in positions.items() if v['net_quantity'] != 0}
        
        logger.info(f"Calculated {len(active_positions)} active positions from {len(orders)} orders")
        return dict(active_positions)
    
    def _process_orders_fifo(self, position_data: Dict, orders: List[OrderModel]):
        """Process orders with FIFO logic for PnL calculation"""
        
        for order in orders:
            quantity = order.quantity
            price = order.average_price or order.price
            trade_value = quantity * price
            
            if order.trade_type == 'BUY':
                # Add to position
                position_data['buy_quantity'] += quantity
                position_data['buy_value'] += trade_value
                position_data['net_quantity'] += quantity
                position_data['net_value'] += trade_value
                
                # Add to trade history for FIFO
                position_data['trade_history'].append({
                    'type': 'BUY',
                    'quantity': quantity,
                    'price': price,
                    'value': trade_value,
                    'timestamp': order.timestamp
                })
                
            elif order.trade_type == 'SELL':
                # Add to sell metrics
                position_data['sell_quantity'] += quantity
                position_data['sell_value'] += trade_value
                position_data['net_quantity'] -= quantity
                position_data['net_value'] -= trade_value
                
                # Calculate realized PnL using FIFO
                realized_pnl = self._calculate_fifo_pnl(
                    position_data['trade_history'], 
                    quantity, 
                    price
                )
                position_data['realized_pnl'] += realized_pnl
    
    def _calculate_fifo_pnl(self, trade_history: List[Dict], sell_qty: int, sell_price: float) -> float:
        """Calculate realized PnL using FIFO (First In, First Out) logic"""
        
        remaining_sell_qty = sell_qty
        realized_pnl = 0.0
        
        # Process buy trades in FIFO order
        for trade in trade_history:
            if trade['type'] == 'BUY' and remaining_sell_qty > 0:
                # How much of this buy trade can we match?
                qty_to_match = min(trade['quantity'], remaining_sell_qty)
                
                if qty_to_match > 0:
                    # Calculate PnL for this portion
                    buy_price = trade['price']
                    pnl = (sell_price - buy_price) * qty_to_match
                    realized_pnl += pnl
                    
                    # Reduce quantities
                    trade['quantity'] -= qty_to_match
                    remaining_sell_qty -= qty_to_match
        
        return realized_pnl
    
    def _calculate_holdings_from_orders(self, orders: List[OrderModel], target_date: date) -> Dict[str, Dict]:
        """
        Calculate holdings from equity/bond orders
        Holdings are equity/bond positions held overnight
        """
        holdings = defaultdict(lambda: {
            'symbol': '',
            'exchange': '',
            'instrument_key': '',
            'quantity': 0,
            'avg_price': 0.0,
            'total_value': 0.0,
            'current_value': 0.0,
            'ltp': 0.0,
            'pnl': 0.0,
            'product': 'CNC'
        })
        
        # Filter equity/bond orders only
        equity_bond_orders = [
            order for order in orders 
            if self._is_equity_or_bond(order.symbol)
        ]
        
        # Group by symbol
        symbol_orders = defaultdict(list)
        for order in equity_bond_orders:
            symbol_orders[order.symbol].append(order)
        
        # Calculate net holdings for each symbol
        for symbol, symbol_order_list in symbol_orders.items():
            holding_data = holdings[symbol]
            holding_data['symbol'] = symbol
            
            if symbol_order_list:
                holding_data['exchange'] = symbol_order_list[0].exchange
                holding_data['instrument_key'] = symbol_order_list[0].instrument_key
            
            total_buy_qty = 0
            total_buy_value = 0.0
            total_sell_qty = 0
            
            # Calculate net position
            for order in symbol_order_list:
                quantity = order.quantity
                price = order.average_price or order.price
                
                if order.trade_type == 'BUY':
                    total_buy_qty += quantity
                    total_buy_value += quantity * price
                elif order.trade_type == 'SELL':
                    total_sell_qty += quantity
            
            # Net holding quantity
            net_quantity = total_buy_qty - total_sell_qty
            
            if net_quantity > 0:
                holding_data['quantity'] = net_quantity
                # Average price weighted by remaining quantity
                if total_buy_qty > 0:
                    holding_data['avg_price'] = total_buy_value / total_buy_qty
                    holding_data['total_value'] = net_quantity * holding_data['avg_price']
                    holding_data['current_value'] = holding_data['total_value']  # Would be updated with LTP
        
        # Filter out zero holdings
        active_holdings = {k: v for k, v in holdings.items() if v['quantity'] > 0}
        
        logger.info(f"Calculated {len(active_holdings)} holdings from equity/bond orders")
        return dict(active_holdings)
    
    def _is_equity_or_bond(self, symbol: str) -> bool:
        """Check if symbol is equity or bond (should convert to holdings)"""
        
        # Get symbol details from database
        symbol_info = self.db.query(Symbol).filter_by(stock_code=symbol).first()
        
        if symbol_info:
            instrument_key = symbol_info.instrument_key
            # Check if it's equity or bond based on instrument_key format
            if '@equities@' in instrument_key or '@bonds@' in instrument_key:
                return True
        
        # Fallback: simple heuristics for symbol analysis
        # Derivatives usually have numbers and special characters
        if any(char.isdigit() for char in symbol) and len(symbol) > 10:
            return False  # Likely derivative
        
        # Most equity symbols are simple alphabetic
        return symbol.replace('-', '').isalpha()
    
    def _update_positions_in_db(self, positions_data: Dict[str, Dict], pseudo_account: str) -> int:
        """Update positions in database"""
        
        updated_count = 0
        
        for symbol, position_data in positions_data.items():
            try:
                # Check if position already exists
                existing_position = self.db.query(PositionModel).filter(
                    and_(
                        PositionModel.pseudo_account == pseudo_account,
                        PositionModel.symbol == symbol
                    )
                ).first()
                
                if existing_position:
                    # Update existing position
                    self._update_position_fields(existing_position, position_data)
                else:
                    # Create new position
                    new_position = self._create_position_from_data(position_data, pseudo_account)
                    self.db.add(new_position)
                
                updated_count += 1
                
            except Exception as e:
                logger.error(f"Error updating position for {symbol}: {str(e)}")
                continue
        
        try:
            self.db.commit()
            logger.info(f"Updated {updated_count} positions in database")
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error committing position updates: {str(e)}")
            raise
        
        return updated_count
    
    def _update_holdings_in_db(self, holdings_data: Dict[str, Dict], pseudo_account: str) -> int:
        """Update holdings in database"""
        
        updated_count = 0
        
        for symbol, holding_data in holdings_data.items():
            try:
                # Check if holding already exists
                existing_holding = self.db.query(HoldingModel).filter(
                    and_(
                        HoldingModel.pseudo_account == pseudo_account,
                        HoldingModel.symbol == symbol
                    )
                ).first()
                
                if existing_holding:
                    # Update existing holding
                    self._update_holding_fields(existing_holding, holding_data)
                else:
                    # Create new holding
                    new_holding = self._create_holding_from_data(holding_data, pseudo_account)
                    self.db.add(new_holding)
                
                updated_count += 1
                
            except Exception as e:
                logger.error(f"Error updating holding for {symbol}: {str(e)}")
                continue
        
        try:
            self.db.commit()
            logger.info(f"Updated {updated_count} holdings in database")
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error committing holding updates: {str(e)}")
            raise
        
        return updated_count
    
    def _update_position_fields(self, position: PositionModel, data: Dict):
        """Update position model fields from data"""
        position.buy_quantity = data.get('buy_quantity', 0)
        position.sell_quantity = data.get('sell_quantity', 0)
        position.buy_value = data.get('buy_value', 0.0)
        position.sell_value = data.get('sell_value', 0.0)
        position.buy_avg_price = data.get('buy_avg_price', 0.0)
        position.sell_avg_price = data.get('sell_avg_price', 0.0)
        position.net_quantity = data.get('net_quantity', 0)
        position.net_value = data.get('net_value', 0.0)
        position.realised_pnl = data.get('realized_pnl', 0.0)
        position.unrealised_pnl = data.get('unrealized_pnl', 0.0)
        position.direction = data.get('direction', 'NONE')
        position.type = data.get('type', 'NRML')
        position.timestamp = datetime.utcnow()
    
    def _create_position_from_data(self, data: Dict, pseudo_account: str) -> PositionModel:
        """Create new position model from data"""
        return PositionModel(
            pseudo_account=pseudo_account,
            symbol=data.get('symbol'),
            exchange=data.get('exchange'),
            instrument_key=data.get('instrument_key'),
            buy_quantity=data.get('buy_quantity', 0),
            sell_quantity=data.get('sell_quantity', 0),
            buy_value=data.get('buy_value', 0.0),
            sell_value=data.get('sell_value', 0.0),
            buy_avg_price=data.get('buy_avg_price', 0.0),
            sell_avg_price=data.get('sell_avg_price', 0.0),
            net_quantity=data.get('net_quantity', 0),
            net_value=data.get('net_value', 0.0),
            realised_pnl=data.get('realized_pnl', 0.0),
            unrealised_pnl=data.get('unrealized_pnl', 0.0),
            direction=data.get('direction', 'NONE'),
            type=data.get('type', 'NRML'),
            ltp=data.get('ltp', 0.0),
            timestamp=datetime.utcnow()
        )
    
    def _update_holding_fields(self, holding: HoldingModel, data: Dict):
        """Update holding model fields from data"""
        holding.quantity = data.get('quantity', 0)
        holding.avg_price = data.get('avg_price', 0.0)
        holding.current_value = data.get('current_value', 0.0)
        holding.ltp = data.get('ltp', 0.0)
        holding.pnl = data.get('pnl', 0.0)
        holding.product = data.get('product', 'CNC')
        holding.timestamp = datetime.utcnow()
    
    def _create_holding_from_data(self, data: Dict, pseudo_account: str) -> HoldingModel:
        """Create new holding model from data"""
        return HoldingModel(
            pseudo_account=pseudo_account,
            symbol=data.get('symbol'),
            exchange=data.get('exchange'),
            instrument_key=data.get('instrument_key'),
            quantity=data.get('quantity', 0),
            avg_price=data.get('avg_price', 0.0),
            current_value=data.get('current_value', 0.0),
            ltp=data.get('ltp', 0.0),
            pnl=data.get('pnl', 0.0),
            product=data.get('product', 'CNC'),
            timestamp=datetime.utcnow()
        )
    
    def regenerate_for_date_range(
        self, 
        pseudo_account: str, 
        start_date: date, 
        end_date: date
    ) -> Dict[str, Any]:
        """Regenerate positions/holdings for a date range"""
        
        results = {}
        current_date = start_date
        
        while current_date <= end_date:
            try:
                result = self.regenerate_positions_and_holdings(pseudo_account, current_date)
                results[current_date.isoformat()] = result
                logger.info(f"Completed regeneration for {current_date}")
            except Exception as e:
                logger.error(f"Error processing {current_date}: {str(e)}")
                results[current_date.isoformat()] = {"error": str(e)}
            
            # Move to next date
            current_date = date.fromordinal(current_date.toordinal() + 1)
        
        return {
            "date_range": f"{start_date} to {end_date}",
            "total_dates": len(results),
            "results": results
        }