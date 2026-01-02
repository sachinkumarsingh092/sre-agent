"""Validation oracles for checking cluster state."""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..clients import KubeClient, PrometheusClient

logger = logging.getLogger("sre_agent.oracle")


@dataclass
class ValidationResult:
    """Result of a validation check."""
    
    success: bool
    message: str
    details: Optional[dict] = None


class OracleBase(ABC):
    """Base class for validation oracles."""
    
    @abstractmethod
    def validate(self) -> ValidationResult:
        """
        Run validation check.
        
        Returns:
            ValidationResult indicating success or failure.
        """
        pass


class AlertsClearedOracle(OracleBase):
    """
    Oracle that validates alerts have been cleared.
    
    Checks AlertManager multiple times to ensure alerts stay cleared.
    """
    
    def __init__(
        self,
        prometheus_client: PrometheusClient,
        alert_name: Optional[str] = None,
        namespace: Optional[str] = None,
        check_count: int = 3,
        check_interval: int = 10,
    ):
        """
        Initialize the oracle.
        
        Args:
            prometheus_client: PrometheusClient instance.
            alert_name: Specific alert to check (None = any alerts).
            namespace: Namespace to filter alerts.
            check_count: Number of times to check alerts are cleared.
            check_interval: Seconds between checks.
        """
        self.prometheus = prometheus_client
        self.alert_name = alert_name
        self.namespace = namespace
        self.check_count = check_count
        self.check_interval = check_interval
    
    def validate(self) -> ValidationResult:
        """
        Check if alerts have been cleared.
        
        Returns:
            ValidationResult - success if alerts cleared, failure if still firing.
        """
        logger.info(f"Checking if alerts cleared (will check {self.check_count} times)")
        
        for i in range(self.check_count):
            alerts = self.prometheus.get_firing_alerts()
            
            # Filter alerts if specific alert name or namespace provided
            if self.alert_name or self.namespace:
                filtered = []
                for alert in alerts:
                    if self.alert_name and alert.name != self.alert_name:
                        continue
                    if self.namespace and alert.namespace != self.namespace:
                        continue
                    filtered.append(alert)
                alerts = filtered
            
            if alerts:
                logger.info(f"Check {i+1}/{self.check_count}: {len(alerts)} alerts still firing")
                return ValidationResult(
                    success=False,
                    message=f"Alerts still firing: {[a.name for a in alerts]}",
                    details={"alerts": [a.name for a in alerts]},
                )
            
            logger.info(f"Check {i+1}/{self.check_count}: No alerts firing")
            
            if i < self.check_count - 1:
                time.sleep(self.check_interval)
        
        return ValidationResult(
            success=True,
            message="All alerts cleared",
        )


class ClusterHealthOracle(OracleBase):
    """
    Oracle that validates basic cluster health.
    
    Checks that pods in the namespace are running and ready.
    """
    
    def __init__(
        self,
        kube_client: KubeClient,
        namespace: str = "default",
    ):
        """
        Initialize the oracle.
        
        Args:
            kube_client: KubeClient instance.
            namespace: Namespace to check.
        """
        self.kube = kube_client
        self.namespace = namespace
    
    def validate(self) -> ValidationResult:
        """
        Check cluster health in the namespace.
        
        Returns:
            ValidationResult - success if all pods healthy.
        """
        logger.info(f"Checking cluster health in namespace: {self.namespace}")
        
        try:
            pods = self.kube.get_pods(namespace=self.namespace)
        except Exception as e:
            return ValidationResult(
                success=False,
                message=f"Failed to get pods: {e}",
            )
        
        unhealthy_pods = []
        for pod in pods:
            if pod["status"] not in ["Running", "Succeeded"]:
                unhealthy_pods.append({
                    "name": pod["name"],
                    "status": pod["status"],
                    "ready": pod["ready"],
                })
            elif not pod["ready"] and pod["status"] == "Running":
                unhealthy_pods.append({
                    "name": pod["name"],
                    "status": pod["status"],
                    "ready": pod["ready"],
                })
        
        if unhealthy_pods:
            return ValidationResult(
                success=False,
                message=f"{len(unhealthy_pods)} unhealthy pods found",
                details={"unhealthy_pods": unhealthy_pods},
            )
        
        return ValidationResult(
            success=True,
            message=f"All {len(pods)} pods healthy",
            details={"total_pods": len(pods)},
        )


class CompositeOracle(OracleBase):
    """
    Oracle that combines multiple oracles.
    
    All oracles must pass for validation to succeed.
    """
    
    def __init__(self, oracles: list[OracleBase]):
        """
        Initialize with list of oracles.
        
        Args:
            oracles: List of OracleBase instances to run.
        """
        self.oracles = oracles
    
    def validate(self) -> ValidationResult:
        """
        Run all oracles and return combined result.
        
        Returns:
            ValidationResult - success only if all oracles pass.
        """
        failed_results = []
        
        for oracle in self.oracles:
            result = oracle.validate()
            if not result.success:
                failed_results.append(result)
        
        if failed_results:
            messages = [r.message for r in failed_results]
            return ValidationResult(
                success=False,
                message=f"Validation failed: {'; '.join(messages)}",
                details={"failed_checks": len(failed_results)},
            )
        
        return ValidationResult(
            success=True,
            message="All validation checks passed",
        )
