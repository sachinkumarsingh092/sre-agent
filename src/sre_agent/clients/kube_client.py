"""Kubernetes client for pod operations with safety classification."""

import logging
import re
import subprocess
from enum import Enum
from dataclasses import dataclass
from typing import Optional

from kubernetes import client, config as k8s_config

from ..config import KubernetesConfig

logger = logging.getLogger("sre_agent.kube")


# Command safety classification
KUBECTL_SAFE_COMMANDS = [
    "kubectl annotate",
    "kubectl api-resources",
    "kubectl api-version",
    "kubectl attach",
    "kubectl auth",
    "kubectl cluster-info",
    "kubectl completion",
    "kubectl describe",
    "kubectl diff",
    "kubectl drain",
    "kubectl events",
    "kubectl explain",
    "kubectl expose",
    "kubectl get",
    "kubectl logs",
    "kubectl options",
    "kubectl top",
    "kubectl version",
]

KUBECTL_UNSAFE_COMMANDS = [
    "kubectl apply",
    "kubectl autoscale",
    "kubectl certificate",
    "kubectl config",
    "kubectl cordon",
    "kubectl cp",
    "kubectl create",
    "kubectl delete",
    "kubectl exec",
    "kubectl kustomize",
    "kubectl label",
    "kubectl patch",
    "kubectl plugins",
    "kubectl port-forward",
    "kubectl proxy",
    "kubectl replace",
    "kubectl rollout",
    "kubectl run",
    "kubectl scale",
    "kubectl set",
    "kubectl uncordon",
    "kubectl taint",
]

# Interactive commands that don't work with automation
KUBECTL_UNSUPPORTED_COMMANDS = [
    "kubectl debug",
    "kubectl edit",
    "kubectl wait",
    "kubectl proxy",
    "kubectl port-forward",
    "kubectl cp",
]


class CommandSafety(str, Enum):
    """Safety classification for kubectl commands."""
    SAFE = "safe"
    UNSAFE = "unsafe"
    UNSUPPORTED = "unsupported"


class DryRunStatus(str, Enum):
    """Status of dry-run execution."""
    SUCCESS = "success"
    NO_EFFECT = "no_effect"
    ERROR = "error"


@dataclass
class CommandResult:
    """Result of a kubectl command execution."""
    success: bool
    stdout: str
    stderr: str
    return_code: int


@dataclass
class DryRunResult:
    """Result of a dry-run execution."""
    status: DryRunStatus
    description: str
    output: str


class KubeClient:
    """
    Kubernetes client for pod operations.
    
    Provides:
    - Direct kubectl command execution
    - Command safety classification
    - Dry-run support
    - Pod-level operations via Python client
    """

    def __init__(self, config: KubernetesConfig):
        """
        Initialize Kubernetes client.
        
        Args:
            config: Kubernetes configuration with kubeconfig path and namespace.
        """
        self.config = config
        self.namespace = config.namespace
        
        # Load kubeconfig
        k8s_config.load_kube_config(config_file=config.kubeconfig)
        
        # Initialize API clients
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

    def classify_command(self, command: str) -> CommandSafety:
        """
        Classify a kubectl command as safe, unsafe, or unsupported.
        
        Args:
            command: The kubectl command to classify.
            
        Returns:
            CommandSafety enum value.
        """
        command = command.strip()
        
        # Check unsupported first (most restrictive)
        for unsupported in KUBECTL_UNSUPPORTED_COMMANDS:
            if command.startswith(unsupported):
                return CommandSafety.UNSUPPORTED
        
        # Check safe commands
        for safe in KUBECTL_SAFE_COMMANDS:
            if command.startswith(safe):
                return CommandSafety.SAFE
        
        # Check unsafe commands
        for unsafe in KUBECTL_UNSAFE_COMMANDS:
            if command.startswith(unsafe):
                return CommandSafety.UNSAFE
        
        # Default to unsafe for unknown commands
        return CommandSafety.UNSAFE

    def is_command_safe(self, command: str) -> bool:
        """Check if a command is safe (read-only)."""
        return self.classify_command(command) == CommandSafety.SAFE

    def validate_command(self, command: str) -> tuple[bool, Optional[str]]:
        """
        Validate a kubectl command for safety issues.
        
        Args:
            command: The kubectl command to validate.
            
        Returns:
            Tuple of (is_valid, error_message).
        """
        if not command.strip().startswith("kubectl"):
            return False, "Only kubectl commands are allowed"
        
        safety = self.classify_command(command)
        
        if safety == CommandSafety.UNSUPPORTED:
            return False, f"Command type is not supported: {command.split()[1] if len(command.split()) > 1 else 'unknown'}"
        
        # Check for interactive flags - must be standalone words, not part of resource names
        interactive_flags = ["--interactive", "--tty", "-it"]
        command_parts = command.split()
        for flag in interactive_flags:
            if flag in command_parts:
                return False, f"Interactive flag '{flag}' is not supported"
        
        # Check for -i and -t as standalone single-letter flags (not part of words like nginx-test)
        for i, part in enumerate(command_parts):
            # Match exactly "-i" or "-t" as standalone flags, not combined like "-it"
            if part == "-i" or part == "-t":
                return False, f"Interactive flag '{part}' is not supported"
        
        # Check for pipe operations (simplified check)
        if "|" in command:
            return False, "Pipe operations are not supported"
        
        # Check for write redirections
        if ">" in command and ">>" not in command:
            # Allow >> for append but not > for overwrite
            if re.search(r'[^>]>[^>]', command):
                return False, "Write redirection is not supported"
        
        return True, None

    def exec_command(self, command: str) -> CommandResult:
        """
        Execute a kubectl command.
        
        Args:
            command: The kubectl command to execute.
            
        Returns:
            CommandResult with stdout, stderr, and return code.
        """
        logger.info(f"Executing: {command}")
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            cmd_result = CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
            )
            
            if cmd_result.success:
                logger.debug(f"Command succeeded: {result.stdout[:200]}...")
            else:
                logger.warning(f"Command failed: {result.stderr}")
            
            return cmd_result
            
        except subprocess.TimeoutExpired:
            return CommandResult(
                success=False,
                stdout="",
                stderr="Command timed out after 60 seconds",
                return_code=-1,
            )
        except Exception as e:
            return CommandResult(
                success=False,
                stdout="",
                stderr=str(e),
                return_code=-1,
            )

    def dry_run(self, command: str) -> DryRunResult:
        """
        Execute a kubectl command with --dry-run=server flag.
        
        Args:
            command: The kubectl command to dry-run.
            
        Returns:
            DryRunResult with status and output.
        """
        # Add dry-run flag
        dry_run_cmd = self._insert_flag(command, "--dry-run=server")
        
        result = self.exec_command(dry_run_cmd)
        
        if result.return_code != 0:
            return DryRunResult(
                status=DryRunStatus.ERROR,
                description=f"Dry-run failed: {result.stderr}",
                output=result.stderr,
            )
        
        if not result.stdout.strip():
            return DryRunResult(
                status=DryRunStatus.NO_EFFECT,
                description="Command would have no effect",
                output="",
            )
        
        return DryRunResult(
            status=DryRunStatus.SUCCESS,
            description="Dry-run successful",
            output=result.stdout,
        )

    def _insert_flag(self, command: str, flag: str) -> str:
        """Insert a flag into a kubectl command before any -- separator."""
        if " -- " in command:
            parts = command.split(" -- ", 1)
            return f"{parts[0]} {flag} -- {parts[1]}"
        return f"{command} {flag}"

    # ==================== Pod Operations ====================

    def get_pods(self, namespace: Optional[str] = None) -> list[dict]:
        """
        Get all pods in a namespace.
        
        Args:
            namespace: Namespace to query. Uses default if not specified.
            
        Returns:
            List of pod info dicts.
        """
        ns = namespace or self.namespace
        pods = self.core_v1.list_namespaced_pod(namespace=ns)
        
        return [
            {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "status": pod.status.phase,
                "ready": self._is_pod_ready(pod),
                "restarts": self._get_restart_count(pod),
                "age": str(pod.metadata.creation_timestamp),
            }
            for pod in pods.items
        ]

    def get_pod(self, name: str, namespace: Optional[str] = None) -> Optional[dict]:
        """
        Get details for a specific pod.
        
        Args:
            name: Pod name.
            namespace: Namespace. Uses default if not specified.
            
        Returns:
            Pod info dict or None if not found.
        """
        ns = namespace or self.namespace
        try:
            pod = self.core_v1.read_namespaced_pod(name=name, namespace=ns)
            return {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "status": pod.status.phase,
                "ready": self._is_pod_ready(pod),
                "restarts": self._get_restart_count(pod),
                "containers": [c.name for c in pod.spec.containers],
                "node": pod.spec.node_name,
                "ip": pod.status.pod_ip,
                "labels": pod.metadata.labels or {},
            }
        except client.exceptions.ApiException as e:
            if e.status == 404:
                return None
            raise

    def delete_pod(self, name: str, namespace: Optional[str] = None) -> bool:
        """
        Delete a pod (triggers restart if managed by deployment/replicaset).
        
        Args:
            name: Pod name.
            namespace: Namespace. Uses default if not specified.
            
        Returns:
            True if successful, False otherwise.
        """
        ns = namespace or self.namespace
        try:
            self.core_v1.delete_namespaced_pod(name=name, namespace=ns)
            logger.info(f"Deleted pod {name} in namespace {ns}")
            return True
        except client.exceptions.ApiException as e:
            logger.error(f"Failed to delete pod {name}: {e}")
            return False

    def get_pod_logs(
        self,
        name: str,
        namespace: Optional[str] = None,
        container: Optional[str] = None,
        tail_lines: int = 100,
    ) -> str:
        """
        Get logs from a pod.
        
        Args:
            name: Pod name.
            namespace: Namespace. Uses default if not specified.
            container: Container name (required if pod has multiple containers).
            tail_lines: Number of lines to return from the end.
            
        Returns:
            Log text.
        """
        ns = namespace or self.namespace
        try:
            logs = self.core_v1.read_namespaced_pod_log(
                name=name,
                namespace=ns,
                container=container,
                tail_lines=tail_lines,
            )
            return logs
        except client.exceptions.ApiException as e:
            logger.error(f"Failed to get logs for pod {name}: {e}")
            return f"Error: {e}"

    def scale_deployment(
        self,
        name: str,
        replicas: int,
        namespace: Optional[str] = None,
    ) -> bool:
        """
        Scale a deployment to specified replica count.
        
        Args:
            name: Deployment name.
            replicas: Desired replica count.
            namespace: Namespace. Uses default if not specified.
            
        Returns:
            True if successful, False otherwise.
        """
        ns = namespace or self.namespace
        try:
            self.apps_v1.patch_namespaced_deployment_scale(
                name=name,
                namespace=ns,
                body={"spec": {"replicas": replicas}},
            )
            logger.info(f"Scaled deployment {name} to {replicas} replicas")
            return True
        except client.exceptions.ApiException as e:
            logger.error(f"Failed to scale deployment {name}: {e}")
            return False

    def get_deployment(self, name: str, namespace: Optional[str] = None) -> Optional[dict]:
        """
        Get deployment details.
        
        Args:
            name: Deployment name.
            namespace: Namespace. Uses default if not specified.
            
        Returns:
            Deployment info dict or None if not found.
        """
        ns = namespace or self.namespace
        try:
            dep = self.apps_v1.read_namespaced_deployment(name=name, namespace=ns)
            return {
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "replicas": dep.spec.replicas,
                "ready_replicas": dep.status.ready_replicas or 0,
                "available_replicas": dep.status.available_replicas or 0,
                "labels": dep.metadata.labels or {},
            }
        except client.exceptions.ApiException as e:
            if e.status == 404:
                return None
            raise

    def _is_pod_ready(self, pod) -> bool:
        """Check if pod is ready."""
        if pod.status.conditions:
            for condition in pod.status.conditions:
                if condition.type == "Ready":
                    return condition.status == "True"
        return False

    def _get_restart_count(self, pod) -> int:
        """Get total restart count for a pod."""
        if pod.status.container_statuses:
            return sum(cs.restart_count for cs in pod.status.container_statuses)
        return 0
