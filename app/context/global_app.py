# ticker_service/app/context/global_app.py
from fastapi import FastAPI, Depends, HTTPException
from typing import Optional

_app_instance: Optional[FastAPI] = None

def set_app(app: FastAPI):
    global _app_instance
    _app_instance = app

def get_app() -> FastAPI:
    if _app_instance is None:
        raise RuntimeError("Global app instance has not been set yet.")
    return _app_instance
# ✅ Broker instance from app.state
def get_broker_instance(app: FastAPI):
    if hasattr(app.state, "broker_instance"):
        return app.state.broker_instance
    raise HTTPException(status_code=500, detail="Broker instance not initialized in app.state")

