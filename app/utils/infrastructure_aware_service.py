"""
Deprecated: Use shared_architecture.resilience.infrastructure_aware instead.

This module is kept for backward compatibility.
"""

import warnings
from shared_architecture.resilience.infrastructure_aware import (
    InfrastructureAwareService,
    OperationMode,
    OperationResult,
    infrastructure_service
)

# Re-export for backward compatibility
__all__ = [
    'InfrastructureAwareService',
    'OperationMode', 
    'OperationResult',
    'infrastructure_service'
]

warnings.warn(
    "app.utils.infrastructure_aware_service is deprecated. "
    "Use shared_architecture.resilience.infrastructure_aware instead.",
    DeprecationWarning,
    stacklevel=2
)