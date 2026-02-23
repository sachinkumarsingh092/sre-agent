"""Mitigation agent - extends SREAgent with mitigation capabilities."""

import logging
import re
import time
from typing import Optional

from .diagnosis import SREAgent, AgentContext
from ..clients import LLMClient, KubeClient, PrometheusClient, CommandSafety, DryRunStatus
from ..config import Config
from ..models import (
    Alert,
    IncidentState,
    IncidentStatus,
    TimelineEntry,
    ActionType,
    Action,
    Diagnosis,
)
from ..mitigation import (
    ActionStack,
    ActionRecord,
    RollbackInfo,
    AlertsClearedOracle,
    ClusterHealthOracle,
    CompositeOracle,
    ValidationResult,
    SeverityCalculator,
)
from ..examples import get_kubectl_examples
from ..logging_config import log_step, log_reasoning, log_action, log_success, log_error, log_warning

logger = logging.getLogger("sre_agent.mitigation_agent")


MITIGATION_SYSTEM_PROMPT = """You are an expert SRE mitigation agent. You remediate problems in Kubernetes environments.

Your goal is to fix the identified issue by executing remediation actions.

TOOL CALLS - respond with EXACTLY ONE of these per message:
- KUBECTL: <action to take> - e.g., "KUBECTL: delete pod X to restart it"
- WAIT: <seconds> - to wait for changes to propagate (max 60)
- CHECK: - to verify if alerts have cleared
- DONE: <summary> - when mitigation is complete or if you cannot fix the issue

CRITICAL RULES:
1. Output ONLY ONE tool call per response - never multiple
2. Wait for the result before making another tool call
3. Do NOT repeat the same action - if a command succeeded, move to CHECK or DONE
4. Typical flow: KUBECTL (action) -> WAIT: 10 -> CHECK: -> DONE

Common remediation actions:
- Delete a crashing pod to trigger restart: "KUBECTL: delete pod <name> in namespace <ns>"
- Scale a deployment: "KUBECTL: scale deployment <name> to <N> replicas"
- Rollout restart: "KUBECTL: rollout restart deployment <name>"

{kubectl_examples}
"""


class MitigationAgent(SREAgent):
    """
    SRE Agent with mitigation capabilities.
    
    Extends SREAgent to:
    1. Execute remediation actions based on diagnosis
    2. Track actions for rollback
    3. Validate remediation success
    4. Retry with reflection on failure
    """

    def __init__(self, config: Config):
        """Initialize the Mitigation Agent."""
        super().__init__(config)
        
        # Action stack for rollback
        self.action_stack = ActionStack()
        
        # Severity calculator for TNR (regression detection)
        self.severity_calculator = SeverityCalculator(self.prometheus, self.kube)
    
    def process_alert(self, alert: Alert) -> IncidentState:
        """
        Process alert through diagnosis AND mitigation.
        
        Args:
            alert: The alert to process.
            
        Returns:
            IncidentState with diagnosis and mitigation results.
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
        
        # Run diagnosis first
        try:
            diagnosis = self._run_diagnosis(alert)
            
            if not diagnosis:
                self.incident.set_status(IncidentStatus.FAILED)
                log_error(logger, "Diagnosis failed - cannot proceed to mitigation")
                return self._save_and_return()
            
            self.incident.set_diagnosis(diagnosis)
            log_success(logger, f"Diagnosis complete: {diagnosis.root_cause}")
            
        except Exception as e:
            logger.error(f"Error during diagnosis: {e}")
            self.incident.set_status(IncidentStatus.FAILED)
            return self._save_and_return()
        
        # Run mitigation with retry
        self.incident.set_status(IncidentStatus.MITIGATING)
        
        # Determine target namespace for severity calculation
        target_namespace = alert.namespace or self.config.kubernetes.namespace
        
        for attempt in range(self.config.agent.max_retries):
            log_step(logger, f"Mitigation Attempt {attempt + 1}/{self.config.agent.max_retries}")
            
            try:
                # Capture pre-mitigation severity
                pre_severity = self.severity_calculator.calculate(target_namespace)
                logger.info(f"Pre-mitigation severity: {pre_severity}")
                self.incident.add_timeline_entry(TimelineEntry.create(
                    action_type=ActionType.VALIDATION,
                    description=f"Pre-mitigation severity: {pre_severity}",
                    output_data=pre_severity.to_dict(),
                ))
                
                success = self._run_mitigation(alert, diagnosis)
                
                # Capture post-mitigation severity
                post_severity = self.severity_calculator.calculate(target_namespace)
                logger.info(f"Post-mitigation severity: {post_severity}")
                
                # Check for regression
                severity_comparison = self.severity_calculator.compare(pre_severity, post_severity)
                self.incident.add_timeline_entry(TimelineEntry.create(
                    action_type=ActionType.VALIDATION,
                    description=f"Post-mitigation severity: {post_severity} ({severity_comparison['status']})",
                    output_data=severity_comparison,
                ))
                
                if post_severity.is_worse_than(pre_severity):
                    log_warning(logger, f"REGRESSION DETECTED: {severity_comparison['message']}")
                    # Rollback due to regression
                    self._rollback_all_actions()
                    if attempt < self.config.agent.max_retries - 1:
                        reflection = f"Mitigation caused regression. {severity_comparison['message']}"
                        self.incident.add_reflection(reflection)
                        log_warning(logger, f"Attempt {attempt + 1} caused regression, will retry...")
                        time.sleep(self.config.agent.retry_sleep_seconds)
                    continue
                
                if success:
                    # Validate the fix
                    self.incident.set_status(IncidentStatus.VALIDATING)
                    log_step(logger, "Validating Mitigation")
                    
                    time.sleep(self.config.agent.validation_wait_seconds)
                    
                    validation_result = self._validate_mitigation(alert)
                    
                    if validation_result.success:
                        self.incident.set_status(IncidentStatus.RESOLVED)
                        log_success(logger, f"Mitigation successful - alerts cleared (severity: {pre_severity.score} -> {post_severity.score})")
                        return self._save_and_return()
                    else:
                        log_warning(logger, f"Validation failed: {validation_result.message}")
                        # Rollback actions from this attempt
                        self._rollback_all_actions()
                
                # Mitigation failed - add reflection
                if attempt < self.config.agent.max_retries - 1:
                    reflection = self.incident.get_naive_reflection()
                    self.incident.add_reflection(reflection)
                    
                    log_warning(logger, f"Attempt {attempt + 1} failed, will retry...")
                    time.sleep(self.config.agent.retry_sleep_seconds)
                    
            except Exception as e:
                logger.error(f"Error during mitigation attempt {attempt + 1}: {e}")
                self.incident.add_timeline_entry(TimelineEntry.create(
                    action_type=ActionType.VALIDATION,
                    description=f"Mitigation attempt {attempt + 1} failed",
                    success=False,
                    error=str(e),
                ))
        
        # All retries exhausted - rollback any remaining actions
        self._rollback_all_actions()
        self.incident.set_status(IncidentStatus.FAILED)
        log_error(logger, "Mitigation failed after all retries")
        
        return self._save_and_return()

    def _rollback_all_actions(self) -> None:
        """Rollback all actions from the stack."""
        rollback_count = 0
        while not self.action_stack.is_empty():
            if self.rollback_last_action():
                rollback_count += 1
        if rollback_count > 0:
            log_warning(logger, f"Rolled back {rollback_count} action(s)")

    def _run_mitigation(self, alert: Alert, diagnosis: Diagnosis) -> bool:
        """
        Run the mitigation loop.
        
        Args:
            alert: The alert being processed.
            diagnosis: The diagnosis result.
            
        Returns:
            True if mitigation actions were executed successfully.
        """
        context = AgentContext(max_tool_calls=10)
        
        # Build mitigation prompt with namespace context
        alert_info = self._format_alert(alert)
        target_namespace = alert.namespace or self.config.kubernetes.namespace
        reflection = ""
        if self.incident.reflection_history:
            reflection = f"\n\nPREVIOUS ATTEMPTS:\n{self.incident.reflection_history[-1]}"
        
        # Include observations from diagnosis (has actual pod names)
        diagnosis_observations = ""
        if hasattr(self, '_diagnosis_observations') and self._diagnosis_observations:
            # Get the last few observations which should have pod info
            recent_obs = self._diagnosis_observations[-3:]
            # Truncate each observation to avoid huge prompts
            truncated_obs = [str(obs)[:1000] for obs in recent_obs]
            diagnosis_observations = "\n\nRESOURCES FOUND DURING DIAGNOSIS:\n" + "\n---\n".join(truncated_obs)
        
        # Include affected resources from diagnosis
        affected = ""
        if diagnosis.affected_resources:
            affected = f"\n\nAFFECTED RESOURCES (use these exact names):\n" + "\n".join(f"- {r}" for r in diagnosis.affected_resources)
        
        initial_prompt = f"""Please mitigate the following incident.

ALERT:
{alert_info}

DIAGNOSIS:
Root Cause: {diagnosis.root_cause}{affected}{diagnosis_observations}{reflection}

IMPORTANT RULES:
1. The affected resources are in namespace '{target_namespace}'
2. Use the EXACT pod/resource names from the diagnosis - DO NOT make up names
3. If you need to find the current pod names, use KUBECTL: get pods first

Based on the diagnosis, formulate and execute a remediation plan.
Start by executing the most likely fix using the actual resource names above."""

        # Initialize conversation
        system_prompt = MITIGATION_SYSTEM_PROMPT.format(kubectl_examples=self.kubectl_examples)
        context.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": initial_prompt},
        ]
        
        # Mitigation loop
        actions_executed = 0
        command_history = []  # Track commands to detect loops
        repeat_count = 0
        
        while context.tool_calls < context.max_tool_calls:
            log_reasoning(logger, f"Mitigation step {context.tool_calls + 1}/{context.max_tool_calls}")
            
            # Get LLM response
            response = self.llm.chat(context.messages)
            context.messages.append({"role": "assistant", "content": response})
            
            logger.debug(f"LLM Response: {response[:500]}...")
            
            # Parse and execute tool call
            result, is_done, command_key = self._parse_mitigation_response(response, alert)
            
            if is_done:
                return actions_executed > 0
            
            if result is None:
                context.messages.append({
                    "role": "user",
                    "content": "Please make a tool call (KUBECTL, WAIT, CHECK) or say DONE if finished."
                })
            else:
                # Check for loop
                if command_key and command_key in command_history:
                    repeat_count += 1
                    logger.warning(f"Repeated command in mitigation: {command_key}")
                    if repeat_count >= 2:
                        context.messages.append({
                            "role": "user",
                            "content": "STOP - You are repeating commands. The action was already executed. Please CHECK: to verify if alerts cleared, or say DONE: if mitigation is complete."
                        })
                        repeat_count = 0
                        context.tool_calls += 1
                        continue
                else:
                    repeat_count = 0
                    if command_key:
                        command_history.append(command_key)
                
                if "executed" in result.lower() or "success" in result.lower():
                    actions_executed += 1
                context.messages.append({"role": "user", "content": f"Result:\n{result}"})
            
            context.tool_calls += 1
        
        return actions_executed > 0

    def _parse_mitigation_response(self, response: str, alert: Alert) -> tuple[Optional[str], bool, Optional[str]]:
        """
        Parse mitigation response and execute tool call.
        
        Returns:
            Tuple of (result_string, is_done, command_key).
        """
        # Check for DONE
        if re.search(r'\bDONE\b', response, re.IGNORECASE):
            return None, True, None
        
        # Check for KUBECTL FIRST - this is the primary action
        # Match KUBECTL at the start of a line or beginning of response
        kubectl_match = re.search(r'(?:^|\n)\s*KUBECTL:\s*(.+?)(?:\n|$)', response, re.IGNORECASE)
        if kubectl_match:
            query = kubectl_match.group(1).strip()
            # Strip any comments from the query
            if '#' in query:
                query = query.split('#')[0].strip()
            command_key = f"kubectl:{query.lower()[:100]}"
            return self._execute_mitigation_kubectl(query, alert), False, command_key
        
        # Check for CHECK (only if no KUBECTL found)
        if re.search(r'\bCHECK\b:', response, re.IGNORECASE):
            return self._check_alerts(alert), False, "check_alerts"
        
        # Check for WAIT
        wait_match = re.search(r'WAIT:\s*(\d+)', response, re.IGNORECASE)
        if wait_match:
            seconds = int(wait_match.group(1))
            return self._wait(seconds), False, f"wait:{seconds}"
        
        return None, False, None

    def _execute_mitigation_kubectl(self, nl_query: str, alert: Alert) -> str:
        """
        Execute a kubectl command for mitigation (with rollback tracking).
        """

        log_action(logger, f"KUBECTL (mitigation): {nl_query}")
        
        # Determine target namespace from alert or config
        target_namespace = alert.namespace or self.config.kubernetes.namespace
        namespace_context = f"IMPORTANT: Target namespace is '{target_namespace}'. Always include '-n {target_namespace}' in your commands."
        
        # Get kubeconfig path
        kubeconfig_path = self.config.kubernetes.kubeconfig
        kubeconfig_context = f"IMPORTANT: Always include '--kubeconfig {kubeconfig_path}' in your commands."
        
        # Generate kubectl command
        from . import KUBECTL_GENERATION_PROMPT
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
        print("!!!!!!!!!! Generated kubectl command:", command)
        
        # Strip any comments from the command
        if '#' in command:
            command = command.split('#')[0].strip()
        
        # Ensure namespace is included if not present
        command = self._ensure_namespace_in_command(command, target_namespace)
        # Ensure kubeconfig is included if not present
        command = self._ensure_kubeconfig_in_command(command, kubeconfig_path)
        logger.info(f"Generated command: {command}")

        print("!!!!!!!!!! Final kubectl command to execute:", command)
        
        # Validate command
        is_valid, error = self.kube.validate_command(command)
        print(f"!!!!!!!!!! Validation result: is_valid={is_valid}, error={error}")
        if not is_valid:
            error_msg = f"Invalid command: {error}"
            logger.error(f"Command validation failed: {error}")
            return error_msg
        
        # Check if command is unsafe (mutating)
        safety = self.kube.classify_command(command)

        print(f"!!!!!!!!!! Command classified as: {safety.value}")
        
        # Capture state before execution for rollback
        rollback_info = None
        original_state = None
        
        if safety == CommandSafety.UNSAFE:
            # Dry-run before executing unsafe commands
            dry_result = self.kube.dry_run(command)
            if dry_result.status == DryRunStatus.ERROR:
                logger.warning(f"Dry-run failed: {dry_result.description}")
                self.incident.add_timeline_entry(TimelineEntry.create(
                    action_type=ActionType.VALIDATION,
                    description=f"Command rejected by dry-run: {command}",
                    input_data={"command": command},
                    output_data={"dry_run_error": dry_result.description},
                    success=False,
                    error=dry_result.description,
                ))
                return f"Command rejected (dry-run failed): {dry_result.description}"
            elif dry_result.status == DryRunStatus.NOT_SUPPORTED:
                logger.info(f"Dry-run not supported for command, proceeding: {command}")
            else:
                logger.info(f"Dry-run passed: {dry_result.description}")
            
            original_state = self._capture_state_before_action(command)
            rollback_info = self._generate_rollback_info(command)
        
        # Execute command
        print("!!!!!!!!! This command will be executed against the cluster !!!!!!!!!!")
        result = self.kube.exec_command(command)
        print(result.stdout)
        
        # Track action if unsafe
        if safety == CommandSafety.UNSAFE:
            action_record = ActionRecord(
                action=command,
                action_type=self._get_action_type(command),
                rollback_info=rollback_info,
                original_state=original_state,
                success=result.success,
            )
            self.action_stack.push(action_record)
            
            # Also add to incident actions
            self.incident.add_action(Action(
                action_type=self._get_action_type(command),
                command=command,
                rollback_command=rollback_info.content if rollback_info else None,
                original_state=original_state,
                success=result.success,
            ))
        
        # Log to timeline
        self.incident.add_timeline_entry(TimelineEntry.create(
            action_type=ActionType.KUBECTL_DELETE if "delete" in command else ActionType.KUBECTL_SCALE,
            description=f"Executed mitigation: {command}",
            input_data={"query": nl_query, "command": command},
            output_data=result.stdout[:1000] if result.success else result.stderr,
            success=result.success,
            error=result.stderr if not result.success else None,
        ))
        
        if result.success:
            return f"Command executed successfully:\n{result.stdout[:500]}"
        else:
            return f"Command failed: {result.stderr}"

    def _check_alerts(self, alert: Alert) -> str:
        """Check if alerts have cleared."""
        log_action(logger, "Checking if alerts cleared")
        
        alerts = self.prometheus.get_firing_alerts()
        
        # Filter for relevant alerts
        relevant = [a for a in alerts if a.name == alert.name]
        
        if not relevant:
            return "✓ Alert has cleared!"
        else:
            return f"✗ Alert still firing: {alert.name}"

    def _wait(self, seconds: int) -> str:
        """Wait for specified seconds."""
        # Cap at reasonable maximum
        seconds = min(seconds, 120)
        log_action(logger, f"Waiting {seconds} seconds")
        time.sleep(seconds)
        return f"Waited {seconds} seconds."

    def _validate_mitigation(self, alert: Alert) -> ValidationResult:
        """
        Validate that mitigation was successful.
        """
        # Create composite oracle
        oracle = CompositeOracle([
            AlertsClearedOracle(
                self.prometheus,
                alert_name=alert.name,
                namespace=alert.namespace,
                check_count=2,
                check_interval=5,
            ),
            ClusterHealthOracle(
                self.kube,
                namespace=alert.namespace or self.config.kubernetes.namespace,
            ),
        ])
        
        result = oracle.validate()
        
        # Log validation
        self.incident.add_timeline_entry(TimelineEntry.create(
            action_type=ActionType.VALIDATION,
            description="Validated mitigation result",
            output_data={"success": result.success, "message": result.message},
            success=result.success,
        ))
        
        return result

    def _capture_state_before_action(self, command: str) -> Optional[dict]:
        """Capture resource state before mutating action."""
        # Extract resource info from command
        # This is simplified - could be more robust
        parts = command.split()
        
        if len(parts) < 3:
            return None
        
        try:
            # Try to get resource before modification
            if "delete" in command and "pod" in command:
                # Find pod name and namespace
                pod_name = None
                namespace = self.config.kubernetes.namespace
                
                for i, part in enumerate(parts):
                    if part == "pod" and i + 1 < len(parts):
                        pod_name = parts[i + 1]
                    if part in ["-n", "--namespace"] and i + 1 < len(parts):
                        namespace = parts[i + 1]
                
                if pod_name:
                    pod = self.kube.get_pod(pod_name, namespace)
                    return pod
        except Exception as e:
            logger.warning(f"Failed to capture state: {e}")
        
        return None

    def _generate_rollback_info(self, command: str) -> Optional[RollbackInfo]:
        """Generate rollback information for a command."""
        # Simplified rollback generation
        # In production, this would be more sophisticated
        
        if "delete" in command and "pod" in command:
            # Pod deletion - rollback is to let deployment recreate
            return RollbackInfo(
                rollback_type="info",
                content="Pod will be recreated by deployment controller"
            )
        
        if "scale" in command:
            # Try to extract original replica count
            # This is a placeholder - real implementation would capture state
            return RollbackInfo(
                rollback_type="command",
                content="kubectl scale deployment <name> --replicas=<original>"
            )
        
        return None

    def _get_action_type(self, command: str) -> str:
        """Determine action type from command."""
        if "delete" in command:
            return "delete"
        if "scale" in command:
            return "scale"
        if "patch" in command:
            return "patch"
        if "rollout" in command:
            return "rollout"
        return "unknown"

    def _save_and_return(self) -> IncidentState:
        """Save incident and return."""
        filepath = self.incident.save(self.config.agent.output_directory)
        logger.info(f"Incident saved to: {filepath}")
        return self.incident

    def rollback_last_action(self) -> bool:
        """
        Rollback the last action from the stack.
        
        Returns:
            True if rollback was successful.
        """
        record = self.action_stack.pop()
        
        if not record:
            logger.warning("No actions to rollback")
            return False
        
        log_action(logger, f"Rolling back: {record.action}")
        
        if record.rollback_info:
            if record.rollback_info.rollback_type == "command":
                result = self.kube.exec_command(record.rollback_info.content)
                
                self.incident.add_timeline_entry(TimelineEntry.create(
                    action_type=ActionType.ROLLBACK,
                    description=f"Rolled back: {record.action}",
                    input_data={"original": record.action, "rollback": record.rollback_info.content},
                    success=result.success,
                ))
                
                return result.success
        
        return False
