# app/api/endpoints/metrics_endpoints.py
"""
Metrics endpoints for trade service monitoring.
Provides access to collected metrics in various formats.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from fastapi.responses import PlainTextResponse, JSONResponse
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from shared_architecture.monitoring.metrics_collector import MetricsCollector, MetricType
from shared_architecture.utils.enhanced_logging import get_logger

router = APIRouter(prefix="/metrics", tags=["metrics"])
logger = get_logger(__name__)

def get_metrics_collector() -> MetricsCollector:
    """Get the metrics collector instance."""
    return MetricsCollector.get_instance()

@router.get("/",
    summary="Get all metrics",
    description="Get all collected metrics in JSON format",
    response_model=Dict[str, Any]
)
async def get_metrics(
    collector: MetricsCollector = Depends(get_metrics_collector),
    format: str = Query("json", regex="^(json|prometheus)$", description="Output format"),
    since_minutes: Optional[int] = Query(None, ge=1, le=1440, description="Get metrics from last N minutes")
):
    """
    Get all collected metrics.
    
    Args:
        format: Output format (json or prometheus)
        since_minutes: Only include metrics from last N minutes
        
    Returns:
        Metrics in requested format
    """
    try:
        if format == "prometheus":
            prometheus_data = collector.export_prometheus()
            return PlainTextResponse(
                content=prometheus_data,
                media_type="text/plain; version=0.0.4; charset=utf-8"
            )
        else:
            metrics_data = collector.export_json()
            
            # Filter by time if requested
            if since_minutes:
                cutoff = datetime.utcnow() - timedelta(minutes=since_minutes)
                filtered_metrics = {}
                
                for key, series_data in metrics_data["metrics"].items():
                    filtered_points = [
                        point for point in series_data["points"]
                        if datetime.fromisoformat(point["timestamp"]) >= cutoff
                    ]
                    
                    if filtered_points:
                        series_data_copy = series_data.copy()
                        series_data_copy["points"] = filtered_points
                        series_data_copy["point_count"] = len(filtered_points)
                        filtered_metrics[key] = series_data_copy
                
                metrics_data["metrics"] = filtered_metrics
                metrics_data["filtered_since"] = cutoff.isoformat()
            
            return JSONResponse(content=metrics_data)
            
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve metrics: {str(e)}"
        )

@router.get("/prometheus",
    summary="Prometheus metrics",
    description="Get metrics in Prometheus exposition format",
    response_class=PlainTextResponse
)
async def prometheus_metrics(collector: MetricsCollector = Depends(get_metrics_collector)):
    """
    Get metrics in Prometheus exposition format.
    
    This endpoint is designed to be scraped by Prometheus.
    """
    try:
        prometheus_data = collector.export_prometheus()
        return PlainTextResponse(
            content=prometheus_data,
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )
    except Exception as e:
        logger.error(f"Failed to export Prometheus metrics: {e}", exc_info=True)
        return PlainTextResponse(
            content=f"# Error exporting metrics: {str(e)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.get("/summary",
    summary="Metrics summary",
    description="Get a summary of all collected metrics",
    response_model=Dict[str, Any]
)
async def metrics_summary(collector: MetricsCollector = Depends(get_metrics_collector)):
    """
    Get a summary of all collected metrics.
    
    Returns:
        Summary including metric counts, types, and recent activity
    """
    try:
        summary = collector.get_metrics_summary()
        return JSONResponse(content=summary)
        
    except Exception as e:
        logger.error(f"Failed to get metrics summary: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get metrics summary: {str(e)}"
        )

@router.get("/metric/{metric_name}",
    summary="Get specific metric",
    description="Get data for a specific metric",
    response_model=Dict[str, Any]
)
async def get_metric(
    metric_name: str,
    collector: MetricsCollector = Depends(get_metrics_collector),
    tags: Optional[str] = Query(None, description="Tags filter in JSON format"),
    since_minutes: Optional[int] = Query(None, ge=1, le=1440, description="Get data from last N minutes")
):
    """
    Get data for a specific metric.
    
    Args:
        metric_name: Name of the metric
        tags: Optional tags filter in JSON format
        since_minutes: Only include data from last N minutes
        
    Returns:
        Metric data including all points and statistics
    """
    try:
        # Parse tags if provided
        parsed_tags = None
        if tags:
            import json
            try:
                parsed_tags = json.loads(tags)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid tags JSON format"
                )
        
        # Get the metric
        metric_series = collector.get_metric(metric_name, parsed_tags)
        if not metric_series:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Metric '{metric_name}' not found"
            )
        
        result = metric_series.to_dict()
        
        # Filter by time if requested
        if since_minutes:
            cutoff = datetime.utcnow() - timedelta(minutes=since_minutes)
            filtered_points = [
                point for point in result["points"]
                if datetime.fromisoformat(point["timestamp"]) >= cutoff
            ]
            result["points"] = filtered_points
            result["point_count"] = len(filtered_points)
            result["filtered_since"] = cutoff.isoformat()
        
        # Add statistics for histograms and timers
        if metric_series.metric_type in [MetricType.HISTOGRAM, MetricType.TIMER]:
            if metric_series.points:
                values = [p.value for p in metric_series.points]
                if since_minutes:
                    cutoff = datetime.utcnow() - timedelta(minutes=since_minutes)
                    values = [
                        p.value for p in metric_series.points 
                        if p.timestamp >= cutoff
                    ]
                
                if values:
                    import statistics
                    result["statistics"] = {
                        "count": len(values),
                        "sum": sum(values),
                        "min": min(values),
                        "max": max(values),
                        "mean": statistics.mean(values),
                        "median": statistics.median(values),
                        "p95": _percentile(values, 0.95),
                        "p99": _percentile(values, 0.99),
                        "stddev": statistics.stdev(values) if len(values) > 1 else 0
                    }
        
        return JSONResponse(content=result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get metric {metric_name}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get metric: {str(e)}"
        )

@router.get("/types",
    summary="Get metric types",
    description="Get list of all metric types and their counts",
    response_model=Dict[str, Any]
)
async def get_metric_types(collector: MetricsCollector = Depends(get_metrics_collector)):
    """
    Get list of all metric types and their counts.
    
    Returns:
        Dictionary of metric types and their counts
    """
    try:
        all_metrics = collector.get_all_metrics()
        
        type_counts = {}
        type_examples = {}
        
        for series in all_metrics.values():
            metric_type = series.metric_type.value
            
            if metric_type not in type_counts:
                type_counts[metric_type] = 0
                type_examples[metric_type] = []
            
            type_counts[metric_type] += 1
            
            # Add example metric names (up to 5 per type)
            if len(type_examples[metric_type]) < 5:
                type_examples[metric_type].append(series.name)
        
        return JSONResponse(content={
            "timestamp": datetime.utcnow().isoformat(),
            "total_metrics": len(all_metrics),
            "type_counts": type_counts,
            "type_examples": type_examples,
            "available_types": [t.value for t in MetricType]
        })
        
    except Exception as e:
        logger.error(f"Failed to get metric types: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get metric types: {str(e)}"
        )

@router.get("/names",
    summary="Get metric names",
    description="Get list of all available metric names",
    response_model=List[str]
)
async def get_metric_names(
    collector: MetricsCollector = Depends(get_metrics_collector),
    metric_type: Optional[str] = Query(None, description="Filter by metric type")
):
    """
    Get list of all available metric names.
    
    Args:
        metric_type: Optional filter by metric type
        
    Returns:
        List of metric names
    """
    try:
        all_metrics = collector.get_all_metrics()
        
        metric_names = set()
        for series in all_metrics.values():
            if metric_type is None or series.metric_type.value == metric_type:
                metric_names.add(series.name)
        
        return JSONResponse(content={
            "timestamp": datetime.utcnow().isoformat(),
            "metric_names": sorted(metric_names),
            "count": len(metric_names),
            "filtered_by_type": metric_type
        })
        
    except Exception as e:
        logger.error(f"Failed to get metric names: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get metric names: {str(e)}"
        )

@router.get("/recent",
    summary="Get recent metrics",
    description="Get metrics with recent activity",
    response_model=Dict[str, Any]
)
async def get_recent_metrics(
    collector: MetricsCollector = Depends(get_metrics_collector),
    minutes: int = Query(5, ge=1, le=60, description="Minutes to look back")
):
    """
    Get metrics that have had recent activity.
    
    Args:
        minutes: How many minutes back to look for activity
        
    Returns:
        Metrics with recent data points
    """
    try:
        all_metrics = collector.get_all_metrics()
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        
        recent_metrics = {}
        for key, series in all_metrics.items():
            recent_points = series.get_since(cutoff)
            if recent_points:
                series_dict = series.to_dict()
                series_dict["points"] = [p.to_dict() for p in recent_points]
                series_dict["recent_point_count"] = len(recent_points)
                recent_metrics[key] = series_dict
        
        return JSONResponse(content={
            "timestamp": datetime.utcnow().isoformat(),
            "cutoff": cutoff.isoformat(),
            "minutes_back": minutes,
            "metrics_with_activity": len(recent_metrics),
            "total_metrics": len(all_metrics),
            "metrics": recent_metrics
        })
        
    except Exception as e:
        logger.error(f"Failed to get recent metrics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get recent metrics: {str(e)}"
        )

@router.delete("/clear",
    summary="Clear old metrics",
    description="Clear metrics older than specified time",
    response_model=Dict[str, Any]
)
async def clear_old_metrics(
    collector: MetricsCollector = Depends(get_metrics_collector),
    older_than_hours: int = Query(1, ge=1, le=24, description="Clear metrics older than N hours")
):
    """
    Clear metrics older than specified time.
    
    Args:
        older_than_hours: Clear metrics older than this many hours
        
    Returns:
        Summary of cleanup operation
    """
    try:
        before_count = sum(len(series.points) for series in collector.get_all_metrics().values())
        
        collector.clear_old_metrics(timedelta(hours=older_than_hours))
        
        after_count = sum(len(series.points) for series in collector.get_all_metrics().values())
        
        return JSONResponse(content={
            "timestamp": datetime.utcnow().isoformat(),
            "older_than_hours": older_than_hours,
            "points_before": before_count,
            "points_after": after_count,
            "points_removed": before_count - after_count
        })
        
    except Exception as e:
        logger.error(f"Failed to clear old metrics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear old metrics: {str(e)}"
        )

@router.get("/stats",
    summary="Get performance statistics",
    description="Get performance statistics for specific metrics",
    response_model=Dict[str, Any]
)
async def get_performance_stats(
    collector: MetricsCollector = Depends(get_metrics_collector),
    metric_names: str = Query(..., description="Comma-separated list of metric names"),
    since_minutes: int = Query(60, ge=1, le=1440, description="Calculate stats from last N minutes")
):
    """
    Get performance statistics for specific metrics.
    
    Args:
        metric_names: Comma-separated list of metric names
        since_minutes: Calculate statistics from last N minutes
        
    Returns:
        Performance statistics for requested metrics
    """
    try:
        names = [name.strip() for name in metric_names.split(",")]
        cutoff = datetime.utcnow() - timedelta(minutes=since_minutes)
        
        stats = {}
        for name in names:
            metric_series = collector.get_metric(name)
            if metric_series:
                recent_points = metric_series.get_since(cutoff)
                if recent_points:
                    values = [p.value for p in recent_points]
                    
                    if values:
                        import statistics
                        stats[name] = {
                            "count": len(values),
                            "sum": sum(values),
                            "min": min(values),
                            "max": max(values),
                            "mean": statistics.mean(values),
                            "median": statistics.median(values),
                            "p95": _percentile(values, 0.95),
                            "p99": _percentile(values, 0.99),
                            "stddev": statistics.stdev(values) if len(values) > 1 else 0,
                            "latest_value": values[-1] if values else None,
                            "trend": _calculate_trend(values) if len(values) > 1 else "stable"
                        }
                    else:
                        stats[name] = {"error": "No data points in specified time range"}
                else:
                    stats[name] = {"error": "No recent data points"}
            else:
                stats[name] = {"error": "Metric not found"}
        
        return JSONResponse(content={
            "timestamp": datetime.utcnow().isoformat(),
            "since_minutes": since_minutes,
            "cutoff": cutoff.isoformat(),
            "requested_metrics": names,
            "statistics": stats
        })
        
    except Exception as e:
        logger.error(f"Failed to get performance stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get performance stats: {str(e)}"
        )

def _percentile(values: List[float], percentile: float) -> float:
    """Calculate percentile value."""
    if not values:
        return 0
    
    sorted_values = sorted(values)
    index = int(len(sorted_values) * percentile)
    return sorted_values[min(index, len(sorted_values) - 1)]

def _calculate_trend(values: List[float]) -> str:
    """Calculate trend direction from values."""
    if len(values) < 2:
        return "stable"
    
    # Simple trend calculation - compare first and last quarters
    quarter_size = max(1, len(values) // 4)
    first_quarter = sum(values[:quarter_size]) / quarter_size
    last_quarter = sum(values[-quarter_size:]) / quarter_size
    
    diff_percent = ((last_quarter - first_quarter) / first_quarter) * 100 if first_quarter != 0 else 0
    
    if diff_percent > 10:
        return "increasing"
    elif diff_percent < -10:
        return "decreasing"
    else:
        return "stable"