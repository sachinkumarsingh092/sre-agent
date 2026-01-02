"""Prometheus and AlertManager client for metrics and alerts."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import requests
from prometheus_api_client import PrometheusConnect

from ..config import PrometheusConfig
from ..models import Alert

logger = logging.getLogger("sre_agent.prometheus")


@dataclass
class MetricResult:
    """Result of a Prometheus query."""
    success: bool
    query: str
    data: list[dict]
    error: Optional[str] = None


class PrometheusClient:
    """
    Client for Prometheus metrics and AlertManager alerts.
    
    Provides:
    - PromQL query execution
    - Active alert retrieval from AlertManager
    - Alert parsing into structured format
    """

    def __init__(self, config: PrometheusConfig):
        """
        Initialize Prometheus client.
        
        Args:
            config: Prometheus configuration with URLs.
        """
        self.config = config
        self.prometheus_url = config.url
        self.alertmanager_url = config.alertmanager_url
        
        # Initialize prometheus-api-client
        self.prom = PrometheusConnect(url=self.prometheus_url, disable_ssl=True)

    def query(self, promql: str) -> MetricResult:
        """
        Execute a PromQL instant query.
        
        Args:
            promql: The PromQL query string.
            
        Returns:
            MetricResult with query results.
        """
        logger.info(f"Executing PromQL: {promql}")
        
        try:
            result = self.prom.custom_query(query=promql)
            
            logger.debug(f"Query returned {len(result)} results")
            
            return MetricResult(
                success=True,
                query=promql,
                data=result,
            )
        except Exception as e:
            logger.error(f"PromQL query failed: {e}")
            return MetricResult(
                success=False,
                query=promql,
                data=[],
                error=str(e),
            )

    def query_range(
        self,
        promql: str,
        start_time: datetime,
        end_time: datetime,
        step: str = "1m",
    ) -> MetricResult:
        """
        Execute a PromQL range query.
        
        Args:
            promql: The PromQL query string.
            start_time: Start of the time range.
            end_time: End of the time range.
            step: Query resolution step.
            
        Returns:
            MetricResult with query results.
        """
        logger.info(f"Executing PromQL range: {promql}")
        
        try:
            result = self.prom.custom_query_range(
                query=promql,
                start_time=start_time,
                end_time=end_time,
                step=step,
            )
            
            return MetricResult(
                success=True,
                query=promql,
                data=result,
            )
        except Exception as e:
            logger.error(f"PromQL range query failed: {e}")
            return MetricResult(
                success=False,
                query=promql,
                data=[],
                error=str(e),
            )

    def get_alerts(self, state: Optional[str] = None) -> list[Alert]:
        """
        Get active alerts from AlertManager.
        
        Args:
            state: Filter by alert state ('active', 'suppressed', 'unprocessed').
                   If None, returns all alerts.
            
        Returns:
            List of Alert objects.
        """
        logger.info("Fetching alerts from AlertManager")
        
        try:
            # AlertManager API v2
            url = f"{self.alertmanager_url}/api/v2/alerts"
            params = {}
            if state:
                params["state"] = state
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            alerts_data = response.json()
            
            alerts = [Alert.from_alertmanager(alert) for alert in alerts_data]
            
            logger.info(f"Retrieved {len(alerts)} alerts")
            
            return alerts
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch alerts: {e}")
            return []

    def get_firing_alerts(self) -> list[Alert]:
        """
        Get only firing (active) alerts.
        
        Returns:
            List of active Alert objects.
        """
        return self.get_alerts(state="active")

    def check_alert_cleared(self, alert_name: str, namespace: Optional[str] = None) -> bool:
        """
        Check if a specific alert has been cleared.
        
        Args:
            alert_name: Name of the alert to check.
            namespace: Optional namespace filter.
            
        Returns:
            True if alert is no longer firing, False if still active.
        """
        alerts = self.get_firing_alerts()
        
        for alert in alerts:
            if alert.name == alert_name:
                if namespace is None or alert.namespace == namespace:
                    return False
        
        return True

    def get_pod_metrics(self, pod_name: str, namespace: str) -> dict[str, Any]:
        """
        Get common metrics for a pod.
        
        Args:
            pod_name: Name of the pod.
            namespace: Namespace of the pod.
            
        Returns:
            Dict with CPU, memory, and restart metrics.
        """
        metrics = {}
        
        # CPU usage
        cpu_query = f'sum(rate(container_cpu_usage_seconds_total{{pod="{pod_name}", namespace="{namespace}"}}[5m]))'
        cpu_result = self.query(cpu_query)
        if cpu_result.success and cpu_result.data:
            metrics["cpu_usage"] = cpu_result.data[0].get("value", [None, None])[1]
        
        # Memory usage
        memory_query = f'sum(container_memory_usage_bytes{{pod="{pod_name}", namespace="{namespace}", container!=""}})'
        memory_result = self.query(memory_query)
        if memory_result.success and memory_result.data:
            metrics["memory_usage_bytes"] = memory_result.data[0].get("value", [None, None])[1]
        
        # Restart count
        restart_query = f'sum(kube_pod_container_status_restarts_total{{pod="{pod_name}", namespace="{namespace}"}})'
        restart_result = self.query(restart_query)
        if restart_result.success and restart_result.data:
            metrics["restart_count"] = restart_result.data[0].get("value", [None, None])[1]
        
        return metrics

    def get_deployment_metrics(self, deployment_name: str, namespace: str) -> dict[str, Any]:
        """
        Get common metrics for a deployment.
        
        Args:
            deployment_name: Name of the deployment.
            namespace: Namespace of the deployment.
            
        Returns:
            Dict with replica and availability metrics.
        """
        metrics = {}
        
        # Desired replicas
        desired_query = f'kube_deployment_spec_replicas{{deployment="{deployment_name}", namespace="{namespace}"}}'
        desired_result = self.query(desired_query)
        if desired_result.success and desired_result.data:
            metrics["desired_replicas"] = desired_result.data[0].get("value", [None, None])[1]
        
        # Available replicas
        available_query = f'kube_deployment_status_replicas_available{{deployment="{deployment_name}", namespace="{namespace}"}}'
        available_result = self.query(available_query)
        if available_result.success and available_result.data:
            metrics["available_replicas"] = available_result.data[0].get("value", [None, None])[1]
        
        # Unavailable replicas
        unavailable_query = f'kube_deployment_status_replicas_unavailable{{deployment="{deployment_name}", namespace="{namespace}"}}'
        unavailable_result = self.query(unavailable_query)
        if unavailable_result.success and unavailable_result.data:
            metrics["unavailable_replicas"] = unavailable_result.data[0].get("value", [None, None])[1]
        
        return metrics

    def format_metrics_for_llm(self, metrics: dict[str, Any]) -> str:
        """
        Format metrics dict into human-readable string for LLM.
        
        Args:
            metrics: Dict of metric name to value.
            
        Returns:
            Formatted string.
        """
        if not metrics:
            return "No metrics available."
        
        lines = []
        for name, value in metrics.items():
            if value is not None:
                # Format large numbers
                if name.endswith("_bytes") and value:
                    try:
                        bytes_val = float(value)
                        if bytes_val > 1e9:
                            formatted = f"{bytes_val / 1e9:.2f} GB"
                        elif bytes_val > 1e6:
                            formatted = f"{bytes_val / 1e6:.2f} MB"
                        else:
                            formatted = f"{bytes_val:.0f} bytes"
                        lines.append(f"- {name}: {formatted}")
                    except (ValueError, TypeError):
                        lines.append(f"- {name}: {value}")
                else:
                    lines.append(f"- {name}: {value}")
        
        return "\n".join(lines) if lines else "No metrics available."
