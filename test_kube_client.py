#!/usr/bin/env python3
"""Test script for KubeClient - run against a real cluster."""

import sys
sys.path.insert(0, "src")

from sre_agent.config import load_config
from sre_agent.clients.kube_client import KubeClient, CommandSafety


def test_kube_client():
    """Test KubeClient functionality."""
    
    # Load config
    config = load_config("config.yaml")
    
    print("=" * 60)
    print("Testing KubeClient")
    print("=" * 60)
    
    # Initialize client
    client = KubeClient(config.kubernetes)
    print(f"✓ KubeClient initialized with namespace: {client.namespace}")
    
    # Test command classification
    print("\n--- Command Safety Classification ---")
    test_commands = [
        ("kubectl get pods", CommandSafety.SAFE),
        ("kubectl describe pod nginx", CommandSafety.SAFE),
        ("kubectl delete pod nginx", CommandSafety.UNSAFE),
        ("kubectl scale deployment nginx --replicas=3", CommandSafety.UNSAFE),
        ("kubectl edit deployment nginx", CommandSafety.UNSUPPORTED),
        ("kubectl logs nginx", CommandSafety.SAFE),
    ]
    
    for cmd, expected in test_commands:
        result = client.classify_command(cmd)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{cmd}' -> {result.value} (expected: {expected.value})")
    
    # Test command validation
    print("\n--- Command Validation ---")
    validation_tests = [
        ("kubectl get pods", True),
        ("kubectl get pods -it", False),  # Interactive flag
        ("kubectl get pods | grep nginx", False),  # Pipe
        ("not-kubectl command", False),  # Not kubectl
        ("kubectl edit pod nginx", False),  # Unsupported
    ]
    
    for cmd, expected_valid in validation_tests:
        is_valid, error = client.validate_command(cmd)
        status = "✓" if is_valid == expected_valid else "✗"
        error_msg = f" ({error})" if error else ""
        print(f"  {status} '{cmd}' -> valid={is_valid}{error_msg}")
    
    # Test actual kubectl command (safe, read-only)
    print("\n--- Execute kubectl get namespaces ---")
    result = client.exec_command("kubectl get namespaces")
    if result.success:
        print(f"✓ Command succeeded")
        print(f"  Output (first 500 chars):\n{result.stdout[:500]}")
    else:
        print(f"✗ Command failed: {result.stderr}")
    
    # Test get pods via Python API
    print(f"\n--- Get pods in namespace '{client.namespace}' ---")
    try:
        pods = client.get_pods()
        print(f"✓ Found {len(pods)} pods")
        for pod in pods[:5]:  # Show first 5
            print(f"  - {pod['name']}: {pod['status']} (restarts: {pod['restarts']})")
    except Exception as e:
        print(f"✗ Failed to get pods: {e}")
    
    print("\n" + "=" * 60)
    print("KubeClient tests completed")
    print("=" * 60)


if __name__ == "__main__":
    test_kube_client()
