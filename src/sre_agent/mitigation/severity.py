"""Severity metrics for measuring system health before/after mitigation."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..clients import PrometheusClient, KubeClient

logger = logging.getLogger("sre_agent.severity")


@dataclass
class SeverityMetric:
    """
    Captures system health at a point in time.
    
    Used to compare pre/post mitigation state and detect regressions.
    """
    alerts: int
    unhealthy_pods: int
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    @property
    def score(self) -> float:
        """
        Calculate severity score.
        
        Higher score = worse health.
        Alerts are weighted more heavily than unhealthy pods.
        """
        return self.alerts * 10 + self.unhealthy_pods * 5
    
    def is_worse_than(self, other: "SeverityMetric") -> bool:
        """Check if this metric represents worse health than another."""
        return self.score > other.score
    
    def is_better_than(self, other: "SeverityMetric") -> bool:
        """Check if this metric represents better health than another."""
        return self.score < other.score
    
    def delta(self, other: "SeverityMetric") -> float:
        """Calculate the difference in scores (positive = improvement)."""
        return other.score - self.score
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "alerts": self.alerts,
            "unhealthy_pods": self.unhealthy_pods,
            "score": self.score,
            "timestamp": self.timestamp,
        }
    
    def __str__(self) -> str:
        return f"Severity(alerts={self.alerts}, unhealthy_pods={self.unhealthy_pods}, score={self.score})"


class SeverityCalculator:
    """
    Calculates system severity metrics from cluster state.
    
    Uses Prometheus alerts and Kubernetes pod health to compute
    an aggregate severity score.
    """
    
    def __init__(self, prometheus: "PrometheusClient", kube: "KubeClient"):
        """
        Initialize the severity calculator.
        
        Args:
            prometheus: Prometheus client for alert data.
            kube: Kubernetes client for pod health data.
        """
        self.prometheus = prometheus
        self.kube = kube
    
    def calculate(self, namespace: str) -> SeverityMetric:
        """
        Calculate current severity for a namespace.
        
        Args:
            namespace: The Kubernetes namespace to check.
            
        Returns:
            SeverityMetric representing current system health.
        """
        # Get firing alerts
        alerts = self.prometheus.get_firing_alerts()
        alert_count = len(alerts)
        
        # Get pod health
        try:
            pods = self.kube.get_pods(namespace)
            unhealthy_count = sum(
                1 for p in pods 
                if p.get("status") not in ["Running", "Succeeded"]
            )
        except Exception as e:
            logger.warning(f"Failed to get pod health: {e}")
            unhealthy_count = 0
        
        metric = SeverityMetric(
            alerts=alert_count,
            unhealthy_pods=unhealthy_count,
        )
        
        logger.debug(f"Calculated severity for {namespace}: {metric}")
        return metric
    
    def compare(self, pre: SeverityMetric, post: SeverityMetric) -> dict:
        """
        Compare pre and post mitigation metrics.
        
        Args:
            pre: Severity before mitigation.
            post: Severity after mitigation.
            
        Returns:
            Dict with comparison results.
        """
        delta = pre.delta(post)
        
        if post.is_worse_than(pre):
            status = "regression"
            message = f"System health degraded: {pre.score} -> {post.score} (delta: {delta})"
        elif post.is_better_than(pre):
            status = "improvement"
            message = f"System health improved: {pre.score} -> {post.score} (delta: {delta})"
        else:
            status = "unchanged"
            message = f"System health unchanged: {pre.score}"
        
        return {
            "status": status,
            "message": message,
            "pre_score": pre.score,
            "post_score": post.score,
            "delta": delta,
            "pre": pre.to_dict(),
            "post": post.to_dict(),
        }
