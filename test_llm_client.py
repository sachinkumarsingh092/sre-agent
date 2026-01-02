#!/usr/bin/env python3
"""Test script for LLMClient - run against vLLM server."""

import sys
sys.path.insert(0, "src")

from sre_agent.config import load_config
from sre_agent.clients.llm_client import LLMClient


def test_llm_client():
    """Test LLMClient functionality."""
    
    # Load config
    config = load_config("config.yaml")
    
    print("=" * 60)
    print("Testing LLMClient")
    print("=" * 60)
    print(f"Endpoint: {config.llm.base_url}")
    print(f"Model: {config.llm.model}")
    
    # Initialize client
    try:
        client = LLMClient(config.llm)
        print("✓ LLMClient initialized")
    except Exception as e:
        print(f"✗ Failed to initialize LLMClient: {e}")
        return
    
    # Test simple inference
    print("\n--- Test Simple Inference ---")
    system_prompt = "You are a helpful assistant. Be brief."
    user_prompt = "What is Kubernetes in one sentence?"
    
    try:
        response = client.inference(system_prompt, user_prompt)
        print(f"✓ Got response:")
        print(f"  {response[:300]}...")
    except Exception as e:
        print(f"✗ Inference failed: {e}")
        return
    
    # Test chat with history
    print("\n--- Test Chat with History ---")
    messages = [
        {"role": "system", "content": "You are a Kubernetes expert. Be concise."},
        {"role": "user", "content": "What command lists all pods?"},
        {"role": "assistant", "content": "kubectl get pods"},
        {"role": "user", "content": "How do I see pods in all namespaces?"},
    ]
    
    try:
        response = client.chat(messages)
        print(f"✓ Got response:")
        print(f"  {response[:300]}...")
    except Exception as e:
        print(f"✗ Chat failed: {e}")
    
    # Test kubectl command generation
    print("\n--- Test kubectl Command Generation ---")
    system_prompt = """You write kubectl commands. Answer with only the correct kubectl command. 
The formatting should always be like this: ```bash
<kubectl command>
```"""
    
    test_queries = [
        "Get all pods in the default namespace",
        "Describe the deployment named nginx",
        "Delete pod named crashed-pod in namespace test",
    ]
    
    for query in test_queries:
        try:
            response = client.inference(system_prompt, query)
            print(f"\n  Query: {query}")
            print(f"  Response: {response.strip()}")
        except Exception as e:
            print(f"  ✗ Failed for '{query}': {e}")
    
    print("\n" + "=" * 60)
    print("LLMClient tests completed")
    print("=" * 60)


if __name__ == "__main__":
    test_llm_client()
