"""SRE Agent - Core diagnosis and mitigation logic."""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from ..clients import LLMClient, KubeClient, PrometheusClient
from ..config import Config
from ..models import (
    Alert,
    IncidentState,
    IncidentStatus,
    TimelineEntry,
    ActionType,
    Diagnosis,
)
from ..examples import get_kubectl_examples, get_prometheus_examples
from ..logging_config import log_step, log_reasoning, log_action, log_success, log_error

logger = logging.getLogger("sre_agent.agent")


# System prompts
DIAGNOSIS_SYSTEM_PROMPT = """You are an expert SRE diagnosis agent. You diagnose problems in Kubernetes environments.

Your goal is to identify the root cause of IT incidents by:
1. Analyzing the alert information
2. Checking pod status and events  
3. Reviewing metrics and logs
4. Identifying fault propagation chains

TOOL CALLS - respond with EXACTLY ONE of these per message:
- KUBECTL: <what you want to check> - e.g., "KUBECTL: get pods in namespace X"
- METRICS: <what metric to query> - e.g., "METRICS: CPU usage for pod Y"
- DIAGNOSE: <root cause and evidence> - ONLY when you have enough information

CRITICAL RULES:
1. Output ONLY ONE tool call per response - never multiple
2. Wait for the result before making another tool call
3. Do NOT repeat the same query - if you already have information, use it
4. After 2-3 queries, you should have enough info to DIAGNOSE
5. If a pod is in CrashLoopBackOff or Error state, that IS the problem - diagnose it

Typical workflow:
1. KUBECTL: get pods to see status
2. KUBECTL: describe pod X (if a pod has issues)
3. DIAGNOSE: based on the evidence gathered

{kubectl_examples}
"""

KUBECTL_GENERATION_PROMPT = """{kubectl_examples}

You write kubectl commands. Answer with only the correct kubectl command.
{namespace_context}
{kubeconfig_context}
The formatting should always be like this: ```bash
<kubectl command>
```"""

METRICS_GENERATION_PROMPT = """{prometheus_examples}

You write PromQL queries. Answer with only the correct PromQL query.
The formatting should always be like this: ```promql
<promql query>
```"""


@dataclass
class AgentContext:
    """Context maintained during agent execution."""
    
    messages: list[dict] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    tool_calls: int = 0
    max_tool_calls: int = 15
    command_history: list[str] = field(default_factory=list)  # Track executed commands
    repeat_count: int = 0  # Count consecutive repeats


class SREAgent:
    """
    SRE Agent for Kubernetes incident diagnosis and mitigation.
    
    Implements a single-agent loop that:
    1. Receives alerts from AlertManager
    2. Queries Kubernetes and Prometheus for context
    3. Uses LLM to diagnose root cause
    4. (Future) Executes mitigation actions
    """

    def __init__(self, config: Config):
        """
        Initialize the SRE Agent.
        
        Args:
            config: Full configuration object.
        """
        self.config = config
        
        # Initialize clients
        self.llm = LLMClient(config.llm)
        self.kube = KubeClient(config.kubernetes)
        self.prometheus = PrometheusClient(config.prometheus)
        
        # Load examples
        self.kubectl_examples = get_kubectl_examples()
        self.prometheus_examples = get_prometheus_examples()
        
        # Current incident state
        self.incident: Optional[IncidentState] = None

    def run(self) -> Optional[IncidentState]:
        """
        Main agent loop - fetch alerts and process them.
        
        Returns:
            IncidentState if an incident was processed, None otherwise.
        """
        log_step(logger, "Checking for alerts")
        
        # Get active alerts
        alerts = self.prometheus.get_firing_alerts()
        
        if not alerts:
            logger.info("No active alerts found")
            return None
        
        # Process first alert (single incident at a time)
        alert = alerts[0]

        logger.info(f"Processing alert: {alert.name} (severity: {alert.severity})")
        
        return self.process_alert(alert)

    def process_alert(self, alert: Alert) -> IncidentState:
        """
        Process a single alert through diagnosis.
        
        Args:
            alert: The alert to process.
            
        Returns:
            IncidentState with diagnosis results.
        """
        # Create incident
        self.incident = IncidentState.create(alert)
        self.incident.set_status(IncidentStatus.DIAGNOSING)
        
        log_step(logger, f"Processing Incident {self.incident.id}", f"Alert: {alert.name}")
        
        # Add initial timeline entry
        self.incident.add_timeline_entry(TimelineEntry.create(
            action_type=ActionType.VALIDATION,
            description=f"Started processing alert: {alert.name}",
            input_data={"alert": alert.name, "severity": alert.severity},
        ))
        
        # Run diagnosis
        try:
            diagnosis = self._run_diagnosis(alert)
            
            if diagnosis:
                self.incident.set_diagnosis(diagnosis)
                self.incident.set_status(IncidentStatus.RESOLVED)
                log_success(logger, f"Diagnosis complete: {diagnosis.root_cause}")
            else:
                self.incident.set_status(IncidentStatus.FAILED)
                log_error(logger, "Diagnosis failed - no root cause identified")
                
        except Exception as e:
            logger.error(f"Error during diagnosis: {e}")
            self.incident.set_status(IncidentStatus.FAILED)
            self.incident.add_timeline_entry(TimelineEntry.create(
                action_type=ActionType.VALIDATION,
                description="Diagnosis failed with error",
                success=False,
                error=str(e),
            ))
        
        # Save incident
        filepath = self.incident.save(self.config.agent.output_directory)
        logger.info(f"Incident saved to: {filepath}")
        
        return self.incident

    def _run_diagnosis(self, alert: Alert) -> Optional[Diagnosis]:
        """
        Run the diagnosis loop for an alert.
        
        Args:
            alert: The alert to diagnose.
            
        Returns:
            Diagnosis if successful, None otherwise.
        """
        context = AgentContext()
        
        # Build initial prompt with namespace emphasis
        alert_info = self._format_alert(alert)
        target_namespace = alert.namespace or self.config.kubernetes.namespace
        initial_prompt = f"""An alert has been triggered in the Kubernetes cluster. Please diagnose the root cause.

ALERT INFORMATION:
{alert_info}

IMPORTANT: The affected resources are in namespace '{target_namespace}'. Always target this namespace in your kubectl commands.

Start by checking the status of relevant pods and services. Use the tools available to gather information.
Remember to make ONE tool call at a time."""

        # Initialize conversation
        system_prompt = DIAGNOSIS_SYSTEM_PROMPT.format(kubectl_examples=self.kubectl_examples)
        context.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": initial_prompt},
        ]
        
        # Diagnosis loop
        while context.tool_calls < context.max_tool_calls:
            log_reasoning(logger, f"Tool call {context.tool_calls + 1}/{context.max_tool_calls}")
            
            # Get LLM response
            response = self.llm.chat(context.messages)
            context.messages.append({"role": "assistant", "content": response})
            
            logger.debug(f"LLM Response: {response[:500]}...")
            
            # Parse and execute tool call
            tool_result, command_key = self._parse_and_execute(response, alert, context)
            
            if tool_result is None:
                # Check if we got a diagnosis
                diagnosis = self._extract_diagnosis(response)
                if diagnosis:
                    # Save observations for mitigation
                    self._diagnosis_observations = context.observations
                    return diagnosis
                
                # No valid tool call or diagnosis - prompt for action
                context.messages.append({
                    "role": "user",
                    "content": "Please make a tool call (KUBECTL, METRICS) or provide your DIAGNOSE result."
                })
            elif tool_result == "DONE":
                # Diagnosis was extracted
                # Save observations for mitigation
                self._diagnosis_observations = context.observations
                return self._extract_diagnosis(response)
            else:
                # Check for loop (same command repeated)
                if command_key and command_key in context.command_history:
                    context.repeat_count += 1
                    logger.warning(f"Repeated command detected: {command_key} (repeat #{context.repeat_count})")
                    
                    if context.repeat_count >= 2:
                        # Force move forward
                        context.messages.append({
                            "role": "user",
                            "content": f"""STOP - You are repeating the same command. You already have this information from previous queries.

Here is what you've gathered so far:
{chr(10).join(f'- {obs[:200]}...' for obs in context.observations[-3:])}

Based on this information, please provide your DIAGNOSE result now. Do NOT make another KUBECTL or METRICS call."""
                        })
                        context.repeat_count = 0
                        context.tool_calls += 1
                        continue
                else:
                    context.repeat_count = 0
                    if command_key:
                        context.command_history.append(command_key)
                
                # Add tool result to conversation
                context.messages.append({"role": "user", "content": f"Tool result:\n{tool_result}"})
                context.observations.append(tool_result)
            
            context.tool_calls += 1
        
        # Save observations for mitigation to use (contains actual pod names)
        self._diagnosis_observations = context.observations
        
        # Max tool calls reached - try to get final diagnosis
        context.messages.append({
            "role": "user",
            "content": "You've reached the maximum number of tool calls. Please provide your DIAGNOSE result now based on the information gathered."
        })
        
        response = self.llm.chat(context.messages)
        return self._extract_diagnosis(response)

    def _parse_and_execute(self, response: str, alert: Alert, context: AgentContext) -> tuple[Optional[str], Optional[str]]:
        """
        Parse LLM response and execute tool call.
        
        Args:
            response: LLM response text.
            alert: Current alert being processed.
            context: Agent context.
            
        Returns:
            Tuple of (tool result string, command_key for dedup). 
            Returns ("DONE", None) if diagnosis found, or (None, None) if no valid tool call.
        """
        # Check for DIAGNOSE
        if "DIAGNOSE:" in response:
            return "DONE", None
        
        # Check for KUBECTL - only match the FIRST one
        kubectl_match = re.search(r'KUBECTL:\s*(.+?)(?:\n|$)', response, re.IGNORECASE)
        if kubectl_match:
            query = kubectl_match.group(1).strip()
            # Strip any comments from the query
            if '#' in query:
                query = query.split('#')[0].strip()
            # Create a normalized key for dedup
            command_key = f"kubectl:{query.lower()[:100]}"
            result = self._execute_kubectl(query, alert)
            return result, command_key
        
        # Check for METRICS
        metrics_match = re.search(r'METRICS:\s*(.+?)(?:\n|$)', response, re.IGNORECASE)
        if metrics_match:
            query = metrics_match.group(1).strip()
            command_key = f"metrics:{query.lower()[:100]}"
            result = self._execute_metrics(query, alert)
            return result, command_key
        
        return None, None

    def _execute_kubectl(self, nl_query: str, alert: Alert) -> str:
        """
        Execute a kubectl query via natural language.
        
        Args:
            nl_query: Natural language query.
            alert: Current alert (for context).
            
        Returns:
            Query result string.
        """
        log_action(logger, f"KUBECTL: {nl_query}")
        
        # Determine target namespace from alert or config
        target_namespace = alert.namespace or self.config.kubernetes.namespace
        namespace_context = f"IMPORTANT: Target namespace is '{target_namespace}'. Always include '-n {target_namespace}' in your commands."
        
        # Get kubeconfig path
        kubeconfig_path = self.config.kubernetes.kubeconfig
        kubeconfig_context = f"IMPORTANT: Always include '--kubeconfig {kubeconfig_path}' in your commands."
        
        # Generate kubectl command
        prompt = KUBECTL_GENERATION_PROMPT.format(
            kubectl_examples=self.kubectl_examples,
            namespace_context=namespace_context,
            kubeconfig_context=kubeconfig_context
        )
        response = self.llm.inference(prompt, nl_query)
        
        # Extract command
        cmd_match = re.search(r'```bash\n(.+?)\n```', response, re.DOTALL)
        if not cmd_match:
            return f"Failed to generate kubectl command for: {nl_query}"
        
        command = cmd_match.group(1).strip()
        
        # Strip any comments from the command
        if '#' in command:
            command = command.split('#')[0].strip()
        
        # Ensure namespace is included if not present
        command = self._ensure_namespace_in_command(command, target_namespace)
        # Ensure kubeconfig is included if not present
        command = self._ensure_kubeconfig_in_command(command, kubeconfig_path)
        logger.info(f"Generated command: {command}")
        
        # Validate command
        is_valid, error = self.kube.validate_command(command)
        if not is_valid:
            return f"Invalid command: {error}"
        
        # Execute command
        result = self.kube.exec_command(command)
        
        # Log to timeline
        self.incident.add_timeline_entry(TimelineEntry.create(
            action_type=ActionType.KUBECTL_GET if "get" in command else ActionType.KUBECTL_DESCRIBE,
            description=f"Executed: {command}",
            input_data={"query": nl_query, "command": command},
            output_data=result.stdout[:1000] if result.success else result.stderr,
            success=result.success,
            error=result.stderr if not result.success else None,
        ))
        
        if result.success:
            # Truncate large outputs
            output = result.stdout
            if len(output) > 3000:
                output = output[:3000] + "\n... (truncated)"
            return output
        else:
            return f"Command failed: {result.stderr}"

    def _execute_metrics(self, nl_query: str, alert: Alert) -> str:
        """
        Execute a Prometheus metrics query via natural language.
        
        Args:
            nl_query: Natural language query.
            alert: Current alert (for context).
            
        Returns:
            Query result string.
        """
        log_action(logger, f"METRICS: {nl_query}")
        
        # Generate PromQL query
        prompt = METRICS_GENERATION_PROMPT.format(prometheus_examples=self.prometheus_examples)
        response = self.llm.inference(prompt, nl_query)
        
        # Extract query
        query_match = re.search(r'```promql\n(.+?)\n```', response, re.DOTALL)
        if not query_match:
            return f"Failed to generate PromQL for: {nl_query}"
        
        promql = query_match.group(1).strip()
        logger.info(f"Generated PromQL: {promql}")
        
        # Execute query
        result = self.prometheus.query(promql)
        
        # Log to timeline
        self.incident.add_timeline_entry(TimelineEntry.create(
            action_type=ActionType.PROMETHEUS_QUERY,
            description=f"Executed PromQL: {promql}",
            input_data={"query": nl_query, "promql": promql},
            output_data=result.data if result.success else result.error,
            success=result.success,
            error=result.error,
        ))
        
        if result.success:
            if not result.data:
                return "Query returned no data"
            return self._format_metrics_result(result.data)
        else:
            return f"Query failed: {result.error}"

    def _ensure_namespace_in_command(self, command: str, namespace: str) -> str:
        """
        Ensure kubectl command includes the target namespace.
        
        Args:
            command: The kubectl command.
            namespace: Target namespace.
            
        Returns:
            Command with namespace flag if needed.
        """
        # Skip if command already has namespace flag
        if '-n ' in command or '--namespace' in command or '--all-namespaces' in command or '-A' in command:
            return command
        
        # Skip for cluster-scoped resources
        cluster_scoped = ['nodes', 'node', 'no', 'namespaces', 'namespace', 'ns', 
                         'persistentvolumes', 'pv', 'clusterroles', 'clusterrolebindings']
        command_parts = command.split()
        for i, part in enumerate(command_parts):
            if part in ['get', 'describe', 'delete', 'logs']:
                if i + 1 < len(command_parts) and command_parts[i + 1].lower() in cluster_scoped:
                    return command
        
        # Insert namespace after 'kubectl'
        if command.startswith('kubectl '):
            return f"kubectl -n {namespace} {command[8:]}"
        
        return command

    def _ensure_kubeconfig_in_command(self, command: str, kubeconfig: str) -> str:
        """
        Ensure kubectl command includes the kubeconfig flag.
        
        Args:
            command: The kubectl command.
            kubeconfig: Path to kubeconfig file.
            
        Returns:
            Command with kubeconfig flag if needed.
        """
        # Skip if command already has kubeconfig flag
        if '--kubeconfig' in command:
            return command
        
        # Insert kubeconfig after 'kubectl'
        if command.startswith('kubectl '):
            return f"kubectl --kubeconfig {kubeconfig} {command[8:]}"
        
        return command

    def _format_alert(self, alert: Alert) -> str:
        """Format alert for LLM consumption."""
        lines = [
            f"Name: {alert.name}",
            f"Severity: {alert.severity}",
        ]
        if alert.namespace:
            lines.append(f"Namespace: {alert.namespace}")
        if alert.pod:
            lines.append(f"Pod: {alert.pod}")
        if alert.service:
            lines.append(f"Service: {alert.service}")
        if alert.summary:
            lines.append(f"Summary: {alert.summary}")
        if alert.description:
            lines.append(f"Description: {alert.description}")
        
        return "\n".join(lines)

    def _format_metrics_result(self, data: list) -> str:
        """Format Prometheus query result for LLM."""
        if not data:
            return "No data"
        
        lines = []
        for item in data[:10]:  # Limit results
            metric = item.get("metric", {})
            value = item.get("value", [None, None])
            
            metric_str = ", ".join(f"{k}={v}" for k, v in metric.items())
            value_str = value[1] if len(value) > 1 else "N/A"
            
            lines.append(f"{metric_str}: {value_str}")
        
        if len(data) > 10:
            lines.append(f"... and {len(data) - 10} more results")
        
        return "\n".join(lines)

    def _extract_diagnosis(self, response: str) -> Optional[Diagnosis]:
        """
        Extract diagnosis from LLM response.
        
        Args:
            response: LLM response containing DIAGNOSE result.
            
        Returns:
            Diagnosis object or None.
        """
        # Look for DIAGNOSE: pattern
        match = re.search(r'DIAGNOSE:\s*(.+)', response, re.DOTALL | re.IGNORECASE)
        if not match:
            return None
        
        diagnosis_text = match.group(1).strip()
        
        # Create diagnosis object
        # Try to extract structured info, fall back to raw text
        root_cause = diagnosis_text
        
        # Look for root cause mention
        root_match = re.search(r'root\s*cause[:\s]+(.+?)(?:\n|$)', diagnosis_text, re.IGNORECASE)
        if root_match:
            root_cause = root_match.group(1).strip()
        
        # Log to timeline
        self.incident.add_timeline_entry(TimelineEntry.create(
            action_type=ActionType.LLM_CALL,
            description="Generated diagnosis",
            output_data=diagnosis_text,
        ))
        
        return Diagnosis(
            root_cause=root_cause,
            affected_resources=[],  # Could be extracted with more parsing
            evidence=[],
            recommended_actions=[],
            confidence="medium",
        )
