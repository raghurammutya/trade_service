# app/core/alert_manager.py

from shared_architecture.connections import get_rabbitmq_connection
import json

class AlertManager:
    def __init__(self, context):
        self.context = context
        self.exchange_name = "alerts"
        self.routing_key = "strategy.alerts"

    async def send_alert(self, title: str, message: str):
        alert_message = {
            "account_id": self.context.account_id,
            "strategy_id": self.context.strategy_id,
            "title": title,
            "message": message
        }
        connection = await get_rabbitmq_connection()
        channel = await connection.channel()
        await channel.default_exchange.publish(
            message=json.dumps(alert_message).encode(),
            routing_key=self.routing_key
        )
