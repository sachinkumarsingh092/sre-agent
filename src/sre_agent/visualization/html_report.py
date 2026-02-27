"""HTML report generation for RCA visualization.

Generates interactive HTML reports with Mermaid.js flowcharts.
Zero Python dependencies - uses CDN-hosted Mermaid.js.
"""

from dataclasses import asdict
from pathlib import Path
from string import Template
from typing import Any, Union


HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RCA Report - Incident $incident_id</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <style>
        :root {
            --bg-primary: #ffffff;
            --bg-secondary: #f8f9fa;
            --text-primary: #212529;
            --text-secondary: #6c757d;
            --border-color: #dee2e6;
            --success-bg: #d4edda;
            --success-border: #28a745;
            --failure-bg: #f8d7da;
            --failure-border: #dc3545;
            --warning-bg: #fff3cd;
            --info-bg: #e3f2fd;
            --purple-bg: #f3e5f5;
        }
        
        * { box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: var(--bg-secondary);
            color: var(--text-primary);
            line-height: 1.6;
        }
        
        .container {
            background: var(--bg-primary);
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        
        h1 {
            margin-top: 0;
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 15px;
        }
        
        h2 {
            color: var(--text-primary);
            margin-top: 30px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .metadata {
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
            padding: 15px;
            background: var(--bg-secondary);
            border-radius: 8px;
            margin-bottom: 20px;
        }
        
        .metadata-item {
            display: flex;
            flex-direction: column;
        }
        
        .metadata-label {
            font-size: 0.8em;
            color: var(--text-secondary);
            text-transform: uppercase;
        }
        
        .metadata-value {
            font-weight: 600;
        }
        
        .status-resolved { color: #28a745; }
        .status-failed { color: #dc3545; }
        .status-diagnosing { color: #ffc107; }
        .status-mitigating { color: #17a2b8; }
        
        .alert-box {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 15px;
            padding: 15px 20px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            background: #f8f9fa;
            align-items: center;
        }
        
        .alert-info {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        
        .alert-name {
            font-size: 1.1em;
            font-weight: 600;
            color: var(--text-primary);
        }
        
        .alert-desc {
            font-size: 0.9em;
            color: var(--text-secondary);
            margin: 0;
        }
        
        .alert-severity {
            display: inline-block;
            padding: 6px 14px;
            border-radius: 4px;
            font-size: 0.75em;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .severity-critical { background: #dc3545; color: white; }
        .severity-warning { background: #ffc107; color: #212529; }
        .severity-info { background: #6c757d; color: white; }
        
        .mermaid-container {
            background: #f8f9fa;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 20px;
            overflow-x: auto;
            text-align: center;
        }
        
        .mermaid-container .mermaid {
            display: inline-block;
        }
        
        .mermaid-container .mermaid svg {
            max-width: 100%;
        }
        
        .diagnosis-box {
            background: #f8f9fa;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 20px;
        }
        
        .diagnosis-box .diagnosis-text {
            font-size: 1em;
            line-height: 1.6;
            color: var(--text-primary);
            margin: 0 0 15px 0;
        }
        
        .diagnosis-meta {
            display: flex;
            gap: 15px;
            align-items: center;
            padding-top: 12px;
            border-top: 1px solid var(--border-color);
        }
        
        .confidence-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            margin-top: 10px;
        }
        
        .confidence-high { background: #28a745; color: white; }
        .confidence-medium { background: #ffc107; color: #212529; }
        .confidence-low { background: #6c757d; color: white; }
        
        .timeline {
            margin-top: 15px;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            overflow: hidden;
            background: #fff;
        }
        
        details {
            border-bottom: 1px solid var(--border-color);
        }
        
        details:last-child {
            border-bottom: none;
        }
        
        summary {
            padding: 12px 15px;
            cursor: pointer;
            user-select: none;
            display: flex;
            align-items: center;
            gap: 15px;
            transition: background 0.15s;
            font-size: 0.85em;
        }
        
        summary:hover {
            background: #f8f9fa;
        }
        
        summary::-webkit-details-marker {
            display: none;
        }
        
        .step-success {
            border-left: 3px solid var(--success-border);
        }
        
        .step-failure {
            border-left: 3px solid var(--failure-border);
        }
        
        .step-status {
            font-weight: 600;
            font-size: 0.75em;
            min-width: 35px;
            text-align: center;
        }
        
        .step-status.ok {
            color: var(--success-border);
        }
        
        .step-status.fail {
            color: var(--failure-border);
        }
        
        .step-timestamp {
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 0.8em;
            color: var(--text-secondary);
            min-width: 65px;
        }
        
        .step-type {
            font-size: 0.7em;
            font-weight: 600;
            padding: 4px 8px;
            border-radius: 3px;
            background: #e9ecef;
            color: #495057;
            text-transform: uppercase;
            white-space: nowrap;
            min-width: fit-content;
        }
        
        
        .step-content {
            padding: 15px 20px;
            background: #f8f9fa;
            border-top: 1px solid var(--border-color);
        }
        
        .step-command {
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 0.8em;
            background: #e9ecef;
            padding: 8px 12px;
            border-radius: 4px;
            margin-bottom: 10px;
            color: #495057;
            word-break: break-all;
        }
        
        .step-command-label {
            font-weight: 600;
            color: #6c757d;
            margin-right: 8px;
        }
        
        .step-output-label {
            font-size: 0.75em;
            font-weight: 600;
            color: #6c757d;
            margin-bottom: 6px;
            text-transform: uppercase;
        }
        
        pre {
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 15px;
            border-radius: 6px;
            overflow-x: auto;
            font-size: 0.8em;
            margin: 0;
            white-space: pre-wrap;
            word-wrap: break-word;
            line-height: 1.5;
            max-height: 300px;
            overflow-y: auto;
        }
        
        .no-data {
            color: var(--text-secondary);
            font-style: italic;
        }
        
        .affected-resources {
            margin-top: 15px;
        }
        
        .affected-resources ul {
            margin: 5px 0;
            padding-left: 20px;
        }
        
        .footer {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid var(--border-color);
            text-align: center;
            color: var(--text-secondary);
            font-size: 0.85em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Root Cause Analysis Report</h1>
        
        <div class="metadata">
            <div class="metadata-item">
                <span class="metadata-label">Incident ID</span>
                <span class="metadata-value">$incident_id</span>
            </div>
            <div class="metadata-item">
                <span class="metadata-label">Status</span>
                <span class="metadata-value status-$status_class">$status</span>
            </div>
            <div class="metadata-item">
                <span class="metadata-label">Created</span>
                <span class="metadata-value">$created_at</span>
            </div>
            <div class="metadata-item">
                <span class="metadata-label">Updated</span>
                <span class="metadata-value">$updated_at</span>
            </div>
        </div>

        <h2>Alert</h2>
        <div class="alert-box">
            <div class="alert-info">
                <div class="alert-name">$alert_name</div>
                <p class="alert-desc">$alert_description</p>
            </div>
            <span class="alert-severity severity-$severity_class">$alert_severity</span>
        </div>

        <h2>Cluster Topology</h2>
        <div class="mermaid-container">
            <pre class="mermaid">
$mermaid_diagram
            </pre>
        </div>

        <h2>Root Cause</h2>
        <div class="diagnosis-box">
            <p class="diagnosis-text">$root_cause</p>
            <div class="diagnosis-meta">
                <span class="confidence-badge confidence-$confidence_class">Confidence: $confidence</span>
                $affected_resources_html
            </div>
        </div>

        <h2>Investigation Timeline</h2>
        <div class="timeline">
$timeline_html
        </div>
        
        <div class="footer">
            Generated by SRE Agent • $generated_at
        </div>
    </div>

    <script>
        mermaid.initialize({
            startOnLoad: true,
            theme: 'neutral',
            flowchart: {
                useMaxWidth: true,
                htmlLabels: true,
                curve: 'basis'
            }
        });
    </script>
</body>
</html>
""")


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _escape_mermaid(text: str) -> str:
    """Escape text for use in Mermaid diagrams."""
    if not text:
        return ""
    # Remove emojis and special unicode characters
    import re
    # Remove emoji and other problematic unicode
    text = re.sub(r'[^\x00-\x7F]+', '', str(text))
    return (
        text
        .replace('"', "'")
        .replace("\n", " ")
        .replace("[", "")
        .replace("]", "")
        .replace("{", "")
        .replace("}", "")
        .replace("#", "")
        .replace(";", " ")
        .replace("(", "")
        .replace(")", "")
        .replace("<", "")
        .replace(">", "")
        .replace("|", "-")
        .replace("&", "and")
        .strip()
    )


def _clean_root_cause(text: str) -> str:
    """Clean up root cause text that may be malformed or start with fragments."""
    if not text:
        return "Not determined"
    
    text = text.strip()
    
    # Common incomplete starts to remove
    incomplete_starts = [
        "of the alert",
        "of the incident",
        "of the issue",
        "of the problem",
        "the root cause is",
        "root cause:",
    ]
    
    lower_text = text.lower()
    for prefix in incomplete_starts:
        if lower_text.startswith(prefix):
            text = text[len(prefix):].strip()
            # Remove leading punctuation
            text = text.lstrip(".,;:- ")
            break
    
    # Capitalize first letter if needed
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    
    # If still empty or too short
    if len(text) < 10:
        return "Root cause analysis incomplete"
    
    return text


def _get_action_icon(action_type: str, for_mermaid: bool = False) -> str:
    """Get icon for action type.
    
    Args:
        action_type: The type of action.
        for_mermaid: If True, return text-based icon safe for Mermaid diagrams.
    """
    if for_mermaid:
        # Text-based icons for Mermaid compatibility
        icons = {
            "kubectl_get": "GET",
            "kubectl_describe": "DESC",
            "kubectl_delete": "DEL",
            "kubectl_scale": "SCALE",
            "kubectl_patch": "PATCH",
            "prometheus_query": "METRICS",
            "llm_call": "LLM",
            "validation": "CHECK",
            "rollback": "ROLLBACK",
        }
        return icons.get(action_type, "STEP")
    else:
        # Text icons for HTML display
        icons = {
            "kubectl_get": "[GET]",
            "kubectl_describe": "[DESC]",
            "kubectl_delete": "[DEL]",
            "kubectl_scale": "[SCALE]",
            "kubectl_patch": "[PATCH]",
            "prometheus_query": "[METRICS]",
            "llm_call": "[LLM]",
            "validation": "[CHECK]",
            "rollback": "[ROLLBACK]",
        }
        return icons.get(action_type, "[STEP]")


def _get_severity_class(severity: str) -> str:
    """Get CSS class for severity level."""
    severity_lower = severity.lower() if severity else ""
    if severity_lower in ("critical", "error", "high"):
        return "critical"
    if severity_lower in ("warning", "medium"):
        return "warning"
    return "info"


def _extract_components(incident_dict: dict) -> dict:
    """
    Extract Kubernetes components from incident data.
    
    Returns dict with:
        - namespace: str
        - deployments: list of deployment names
        - pods: list of {name, status, is_faulty}
        - containers: list of container names
        - services: list of service names
        - faulty_component: name of the faulty component
    """
    import re
    
    components = {
        "namespace": "default",
        "deployments": set(),
        "pods": {},  # name -> {status, is_faulty, deployment}
        "containers": set(),
        "services": set(),
        "faulty_component": None,
        "node": None,
    }
    
    alert = incident_dict.get("alert", {})
    timeline = incident_dict.get("timeline", [])
    diagnosis = incident_dict.get("diagnosis", {}) or {}
    actions = incident_dict.get("actions", [])
    
    # Get namespace from alert
    if alert.get("namespace"):
        components["namespace"] = alert["namespace"]
    
    # Get container from alert labels
    if alert.get("labels", {}).get("container"):
        components["containers"].add(alert["labels"]["container"])
    
    # Parse timeline outputs for component info
    for entry in timeline:
        output = str(entry.get("output_data", ""))
        
        # Parse kubectl get pods output
        # Format: NAME READY STATUS RESTARTS AGE ...
        if "kubectl_get" in entry.get("action_type", ""):
            lines = output.split("\n")
            for line in lines[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 3:
                    pod_name = parts[0]
                    status = parts[2] if len(parts) > 2 else "Unknown"
                    
                    # Skip if not a valid pod name
                    if not pod_name or pod_name == "NAME":
                        continue
                    
                    # Infer deployment from pod name (remove replicaset hash and pod hash)
                    # e.g., backend-app-646764876f-8lhhz -> backend-app
                    deployment_match = re.match(r"^(.+)-[a-f0-9]+-[a-z0-9]+$", pod_name)
                    deployment = deployment_match.group(1) if deployment_match else None
                    
                    is_faulty = status in ("CrashLoopBackOff", "Error", "ImagePullBackOff", "Pending", "Failed")
                    
                    components["pods"][pod_name] = {
                        "status": status,
                        "is_faulty": is_faulty,
                        "deployment": deployment,
                    }
                    
                    if deployment:
                        components["deployments"].add(deployment)
                    
                    if is_faulty and not components["faulty_component"]:
                        components["faulty_component"] = pod_name
        
        # Parse kubectl describe output
        if "kubectl_describe" in entry.get("action_type", ""):
            # Extract container names
            container_match = re.findall(r"Containers:\s*\n\s+(\w+):", output)
            for c in container_match:
                components["containers"].add(c)
            
            # Extract node
            node_match = re.search(r"Node:\s+([^/\n]+)", output)
            if node_match:
                components["node"] = node_match.group(1).strip()
            
            # Extract ReplicaSet/Deployment
            controlled_by = re.search(r"Controlled By:\s+(\w+)/([^\n]+)", output)
            if controlled_by:
                resource_type = controlled_by.group(1)
                resource_name = controlled_by.group(2).strip()
                if resource_type == "ReplicaSet":
                    # Infer deployment from ReplicaSet name
                    dep_match = re.match(r"^(.+)-[a-f0-9]+$", resource_name)
                    if dep_match:
                        components["deployments"].add(dep_match.group(1))
    
    # Check actions for more component info
    for action in actions:
        original = action.get("original_state", {}) or {}
        if original.get("containers"):
            for c in original["containers"]:
                components["containers"].add(c)
    
    # Convert sets to lists
    components["deployments"] = sorted(components["deployments"])
    components["containers"] = sorted(components["containers"])
    components["services"] = sorted(components["services"])
    
    return components


def generate_component_topology(incident_dict: dict) -> str:
    """Generate Mermaid diagram showing component topology with faulty component highlighted."""
    components = _extract_components(incident_dict)
    
    lines = ["graph TB"]
    
    namespace = _escape_mermaid(components["namespace"])
    node_name = _escape_mermaid(components.get("node", "cluster-node"))
    
    # Outer: Node subgraph
    lines.append(f'    subgraph NODE["{node_name}"]')
    lines.append("    direction TB")
    
    # Inner: Namespace subgraph
    lines.append(f'        subgraph NS["{namespace}"]')
    lines.append("        direction LR")
    
    # Add deployments with their pods nested
    deployment_idx = 0
    for deployment in components["deployments"]:
        dep_id = f"D{deployment_idx}"
        dep_name = _escape_mermaid(deployment)
        
        # Deployment subgraph containing its pods
        lines.append(f'            subgraph {dep_id}["{dep_name}"]')
        lines.append("            direction TB")
        
        # Find pods belonging to this deployment
        pod_idx = 0
        for pod_name, pod_info in components["pods"].items():
            if pod_info.get("deployment") == deployment:
                pod_id = f"P{deployment_idx}_{pod_idx}"
                status = pod_info.get("status", "Unknown")
                is_faulty = pod_info.get("is_faulty", False)
                
                # Extract just the unique part of pod name (last segment)
                name_parts = pod_name.split("-")
                if len(name_parts) >= 2:
                    short_name = "-".join(name_parts[-2:])
                else:
                    short_name = pod_name[-15:] if len(pod_name) > 15 else pod_name
                
                short_name = _escape_mermaid(short_name)
                status = _escape_mermaid(status)
                
                # Use different shape for faulty
                if is_faulty:
                    lines.append(f'                {pod_id}["{short_name}"]')
                else:
                    lines.append(f'                {pod_id}["{short_name}"]')
                
                pod_idx += 1
        
        lines.append("            end")
        
        # Style the deployment subgraph
        lines.append(f"            style {dep_id} fill:#f8f9fa,stroke:#dee2e6,stroke-width:1px")
        
        deployment_idx += 1
    
    # Add any orphan pods (no deployment)
    orphan_pods = [
        (name, info) for name, info in components["pods"].items()
        if not info.get("deployment")
    ]
    if orphan_pods:
        lines.append('            subgraph STANDALONE["standalone"]')
        lines.append("            direction TB")
        for idx, (pod_name, pod_info) in enumerate(orphan_pods):
            pod_id = f"ORPH{idx}"
            name_parts = pod_name.split("-")
            short_name = "-".join(name_parts[-2:]) if len(name_parts) >= 2 else pod_name[-15:]
            short_name = _escape_mermaid(short_name)
            lines.append(f'                {pod_id}["{short_name}"]')
        lines.append("            end")
        lines.append("            style STANDALONE fill:#f8f9fa,stroke:#dee2e6,stroke-width:1px")
    
    # Close namespace subgraph
    lines.append("        end")
    
    # Close node subgraph
    lines.append("    end")
    
    # Style the namespace
    lines.append("    style NS fill:#e3f2fd,stroke:#1976d2,stroke-width:2px,rx:8,ry:8")
    
    # Style the node
    lines.append("    style NODE fill:#fff8e1,stroke:#ff8f00,stroke-width:2px,rx:10,ry:10")
    
    # Style individual pods based on health
    deployment_idx = 0
    for deployment in components["deployments"]:
        pod_idx = 0
        for pod_name, pod_info in components["pods"].items():
            if pod_info.get("deployment") == deployment:
                pod_id = f"P{deployment_idx}_{pod_idx}"
                is_faulty = pod_info.get("is_faulty", False)
                
                if is_faulty:
                    lines.append(f"    style {pod_id} fill:#ef5350,stroke:#b71c1c,stroke-width:3px,color:#fff")
                else:
                    lines.append(f"    style {pod_id} fill:#81c784,stroke:#2e7d32,stroke-width:1px")
                
                pod_idx += 1
        deployment_idx += 1
    
    # Style orphan pods
    for idx, (pod_name, pod_info) in enumerate(orphan_pods):
        pod_id = f"ORPH{idx}"
        is_faulty = pod_info.get("is_faulty", False)
        if is_faulty:
            lines.append(f"    style {pod_id} fill:#ef5350,stroke:#b71c1c,stroke-width:3px,color:#fff")
        else:
            lines.append(f"    style {pod_id} fill:#81c784,stroke:#2e7d32,stroke-width:1px")
    
    return "\n".join(lines)


def generate_timeline_html(timeline: list[dict]) -> str:
    """Generate expandable timeline HTML."""
    if not timeline:
        return '<p class="no-data">No timeline entries recorded.</p>'

    html_parts = []

    for entry in timeline:
        action_type = entry.get("action_type", "unknown")
        description = entry.get("description", "Unknown")
        timestamp = entry.get("timestamp", "")
        success = entry.get("success", True)
        output_data = entry.get("output_data")
        error = entry.get("error")
        input_data = entry.get("input_data") or {}

        status_class = "step-success" if success else "step-failure"
        status_text = "OK" if success else "FAIL"
        status_text_class = "ok" if success else "fail"
        
        # Format timestamp to just time (HH:MM:SS)
        if "T" in timestamp:
            time_part = timestamp.split("T")[1][:8]
        else:
            time_part = timestamp[:8]
        
        # Clean up action type for display
        action_display = action_type.replace("_", " ").upper()

        # Extract command if available
        command = input_data.get("command", "") or input_data.get("promql", "")
        
        # Format output for display
        if error:
            output_display = _escape_html(str(error))
        elif output_data:
            if isinstance(output_data, dict):
                import json
                output_display = _escape_html(json.dumps(output_data, indent=2))
            else:
                output_display = _escape_html(str(output_data)[:3000])
                if len(str(output_data)) > 3000:
                    output_display += "\n... (truncated)"
        else:
            output_display = "No output"

        # Build command section if available
        command_html = ""
        if command:
            command_html = f'<div class="step-command"><span class="step-command-label">Command:</span>{_escape_html(command)}</div>'
        
        # Build output section
        output_html = f'<div class="step-output-label">Output</div><pre>{output_display}</pre>'

        html_parts.append(f"""<details>
    <summary class="{status_class}">
        <span class="step-status {status_text_class}">{status_text}</span>
        <span class="step-timestamp">{time_part}</span>
        <span class="step-type">{action_display}</span>
    </summary>
    <div class="step-content">
        {command_html}
        {output_html}
    </div>
</details>""")

    return "\n".join(html_parts)


def generate_affected_resources_html(resources: list[str]) -> str:
    """Generate HTML for affected resources list."""
    if not resources:
        return ""

    items = "\n".join(f"<li>{_escape_html(r)}</li>" for r in resources)
    return f"""
        <div class="affected-resources">
            <strong>Affected Resources:</strong>
            <ul>{items}</ul>
        </div>
    """


def generate_rca_report(incident: Union[dict, Any]) -> str:
    """
    Generate complete HTML report from IncidentState.

    Args:
        incident: IncidentState object or dict representation.

    Returns:
        Complete HTML string for the report.
    """
    # Convert to dict if it's a dataclass
    if hasattr(incident, "__dataclass_fields__"):
        incident_dict = asdict(incident)
    else:
        incident_dict = incident

    # Extract data
    timeline = incident_dict.get("timeline", [])
    diagnosis = incident_dict.get("diagnosis") or {}
    alert = incident_dict.get("alert") or {}
    status = incident_dict.get("status", "unknown")

    # Generate components
    mermaid = generate_component_topology(incident_dict)
    timeline_html = generate_timeline_html(timeline)
    affected_html = generate_affected_resources_html(
        diagnosis.get("affected_resources", [])
    )

    # Get current time for generation timestamp
    from datetime import datetime
    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Confidence styling
    confidence = diagnosis.get("confidence", "medium")
    confidence_class = confidence.lower() if confidence else "medium"

    return HTML_TEMPLATE.substitute(
        incident_id=incident_dict.get("id", "unknown"),
        status=status,
        status_class=status.lower().replace(" ", "-"),
        created_at=incident_dict.get("created_at", "N/A")[:19],
        updated_at=incident_dict.get("updated_at", "N/A")[:19],
        alert_name=_escape_html(alert.get("name", "Unknown Alert")),
        alert_severity=alert.get("severity", "unknown"),
        severity_class=_get_severity_class(alert.get("severity", "")),
        alert_description=_escape_html(
            alert.get("description") or alert.get("summary") or "No description"
        ),
        mermaid_diagram=mermaid,
        root_cause=_escape_html(_clean_root_cause(diagnosis.get("root_cause", ""))),
        confidence=confidence,
        confidence_class=confidence_class,
        affected_resources_html=affected_html,
        timeline_html=timeline_html,
        generated_at=generated_at,
    )


def save_report(incident: Union[dict, Any], output_dir: str = ".") -> str:
    """
    Save HTML report to file.

    Args:
        incident: IncidentState object or dict representation.
        output_dir: Directory to save the report.

    Returns:
        Path to the saved report file.
    """
    html = generate_rca_report(incident)

    # Get incident ID
    if hasattr(incident, "id"):
        incident_id = incident.id
    else:
        incident_id = incident.get("id", "unknown")

    # Save file
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    filepath = output_path / f"rca_report_{incident_id}.html"
    filepath.write_text(html, encoding="utf-8")

    return str(filepath)
