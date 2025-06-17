# app/utils/celery_db_helper.py
"""
Deprecated: Use shared_architecture.utils.celery_helpers instead.

This module is kept for backward compatibility.
"""
import warnings
from shared_architecture.utils.celery_helpers import get_celery_db_session as _get_celery_db_session

def get_celery_db_session():
    """
    Creates a synchronous database session specifically for Celery tasks.
    
    DEPRECATED: Use shared_architecture.utils.celery_helpers.get_celery_db_session instead.
    """
    warnings.warn(
        "app.utils.celery_db_helper.get_celery_db_session is deprecated. "
        "Use shared_architecture.utils.celery_helpers.get_celery_db_session instead.",
        DeprecationWarning,
        stacklevel=2
    )
    return _get_celery_db_session()