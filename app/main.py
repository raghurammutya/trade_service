# trade_service/app/main.py
from fastapi import FastAPI, Depends
from app.api.endpoints import trade_endpoints
from app.core.config import settings
from shared_architecture.utils.service_helpers import connection_manager
from app.services.trade_service import TradeService
from sqlalchemy.orm import Session
from shared_architecture.db import get_db, Base

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    connection_manager.initialize()
    engine = connection_manager.get_timescaledb_engine()
    Base.metadata.create_all(bind=engine)

app.include_router(trade_endpoints.router, prefix="/trades", tags=["trades"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)