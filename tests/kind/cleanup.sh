#!/bin/bash
# Cleanup script - delete kind cluster

CLUSTER_NAME="sre-agent-test"

echo "Deleting Kind cluster: ${CLUSTER_NAME}"
kind delete cluster --name "${CLUSTER_NAME}"
echo "Cleanup complete"
