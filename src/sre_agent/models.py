"""Data models for incident tracking with JSON persistence."""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class IncidentStatus(str, Enum):
    """Status of an incident."""

    OPEN = "open"
    DIAGNOSING = "diagnosing"
    MITIGATING = "mitigating"
    VALIDATING = "validating"
    RESOLVED = "resolved"
    FAILED = "failed"


class ActionType(str, Enum):
    """Type of action taken."""

    KUBECTL_GET = "kubectl_get"
    KUBECTL_DESCRIBE = "kubectl_describe"
    KUBECTL_DELETE = "kubectl_delete"
    KUBECTL_SCALE = "kubectl_scale"
    KUBECTL_PATCH = "kubectl_patch"
    PROMETHEUS_QUERY = "prometheus_query"
    LLM_CALL = "llm_call"
    VALIDATION = "validation"
    ROLLBACK = "rollback"


@dataclass
class TimelineEntry:
    """Single entry in incident timeline."""

    timestamp: str
    action_type: str
    description: str
    input_data: Optional[dict] = None
    output_data: Optional[Any] = None
    success: bool = True
    error: Optional[str] = None

    @classmethod
    def create(
        cls,
        action_type: ActionType,
        description: str,
        input_data: Optional[dict] = None,
        output_data: Optional[Any] = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> "TimelineEntry":
        """Create a new timeline entry with current timestamp."""
        return cls(
            timestamp=datetime.utcnow().isoformat(),
            action_type=action_type.value,
            description=description,
            input_data=input_data,
            output_data=output_data,
            success=success,
            error=error,
        )


@dataclass
class Action:
    """An action taken during mitigation that can be rolled back."""

    action_type: str
    command: str
    rollback_command: Optional[str] = None
    original_state: Optional[dict] = None
    executed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    success: bool = True


@dataclass
class Alert:
    """Representation of a Prometheus/AlertManager alert."""

    name: str
    severity: str
    namespace: Optional[str] = None
    pod: Optional[str] = None
    service: Optional[str] = None
    description: Optional[str] = None
    summary: Optional[str] = None
    labels: dict = field(default_factory=dict)
    annotations: dict = field(default_factory=dict)
    starts_at: Optional[str] = None
    
    @classmethod
    def from_alertmanager(cls, alert_data: dict) -> "Alert":
        """Create Alert from AlertManager API response."""
        labels = alert_data.get("labels", {})
        annotations = alert_data.get("annotations", {})
        
        return cls(
            name=labels.get("alertname", "unknown"),
            severity=labels.get("severity", "unknown"),
            namespace=labels.get("namespace"),
            pod=labels.get("pod"),
            service=labels.get("service"),
            description=annotations.get("description"),
            summary=annotations.get("summary"),
            labels=labels,
            annotations=annotations,
            starts_at=alert_data.get("startsAt"),
        )


@dataclass
class Diagnosis:
    """Diagnosis result from the agent."""

    root_cause: str
    affected_resources: list[str]
    evidence: list[str]
    recommended_actions: list[str]
    confidence: str = "medium"  # low, medium, high


@dataclass
class IncidentState:
    """
    Complete state of an incident.

    Persisted to JSON file for tracking and debugging.
    """

    id: str
    alert: dict
    status: str
    timeline: list[dict] = field(default_factory=list)
    diagnosis: Optional[dict] = None
    actions: list[dict] = field(default_factory=list)
    reflection_history: list[str] = field(default_factory=list)
    retry_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @classmethod
    def create(cls, alert: Alert) -> "IncidentState":
        """Create a new incident from an alert."""
        return cls(
            id=str(uuid.uuid4())[:8],
            alert=asdict(alert),
            status=IncidentStatus.OPEN.value,
        )

    def add_timeline_entry(self, entry: TimelineEntry) -> None:
        """Add an entry to the timeline."""
        self.timeline.append(asdict(entry))
        self.updated_at = datetime.utcnow().isoformat()

    def add_action(self, action: Action) -> None:
        """Add an action to the actions list."""
        self.actions.append(asdict(action))
        self.updated_at = datetime.utcnow().isoformat()

    def set_diagnosis(self, diagnosis: Diagnosis) -> None:
        """Set the diagnosis result."""
        self.diagnosis = asdict(diagnosis)
        self.updated_at = datetime.utcnow().isoformat()

    def set_status(self, status: IncidentStatus) -> None:
        """Update incident status."""
        self.status = status.value
        self.updated_at = datetime.utcnow().isoformat()

    def add_reflection(self, reflection: str) -> None:
        """Add reflection from a failed attempt."""
        self.reflection_history.append(reflection)
        self.retry_count += 1
        self.updated_at = datetime.utcnow().isoformat()

    def save(self, output_dir: str, generate_html: bool = True) -> str:
        """
        Save incident state to JSON file and optionally generate HTML report.
        
        Args:
            output_dir: Directory to save the incident file.
            generate_html: Whether to generate HTML RCA report (default: True).
            
        Returns:
            Path to the saved JSON file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        filename = f"incident_{self.id}.json"
        filepath = output_path / filename
        
        with open(filepath, "w") as f:
            json.dump(asdict(self), f, indent=2, default=str)
        
        # Generate HTML report alongside JSON
        if generate_html:
            try:
                from .visualization import save_report
                save_report(self, output_dir)
            except Exception:
                pass  # Don't fail incident save if report generation fails
        
        return str(filepath)

    @classmethod
    def load(cls, filepath: str) -> "IncidentState":
        """Load incident state from JSON file."""
        with open(filepath, "r") as f:
            data = json.load(f)
        return cls(**data)

    def get_naive_reflection(self) -> str:
        """
        Generate naive reflection summary of previous attempts.
        
        Returns a text summary of what was tried and what failed.
        """
        if not self.timeline:
            return ""

        summary_parts = [
            f"Previous attempt #{self.retry_count} summary:",
            f"- Status: {self.status}",
        ]

        # Summarize actions taken
        if self.actions:
            summary_parts.append("- Actions taken:")
            for action in self.actions:
                status = "succeeded" if action.get("success") else "failed"
                summary_parts.append(f"  * {action.get('command', 'unknown')} - {status}")

        # Summarize diagnosis if present
        if self.diagnosis:
            summary_parts.append(f"- Root cause identified: {self.diagnosis.get('root_cause', 'unknown')}")

        # Add any errors from timeline
        errors = [
            entry.get("error")
            for entry in self.timeline
            if entry.get("error") and not entry.get("success", True)
        ]
        if errors:
            summary_parts.append("- Errors encountered:")
            for error in errors[-3:]:  # Last 3 errors
                summary_parts.append(f"  * {error}")

        summary_parts.append(
            "\nPlease analyze what went wrong and try a different approach."
        )

        return "\n".join(summary_parts)
