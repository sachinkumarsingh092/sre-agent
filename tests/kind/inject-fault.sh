#!/bin/bash
# Fault injection script for testing SRE Agent

set -e

FAULT_TYPE="${1:-help}"
NAMESPACE="default"
DEPLOYMENT="nginx-test"

usage() {
    echo "Usage: $0 <fault-type>"
    echo ""
    echo "Available fault types:"
    echo "  pod-crash     - Delete a pod to simulate crash"
    echo "  scale-zero    - Scale deployment to zero replicas"
    echo "  bad-image     - Update deployment with non-existent image"
    echo "  restore       - Restore deployment to healthy state"
    echo ""
    echo "Examples:"
    echo "  $0 pod-crash"
    echo "  $0 scale-zero"
    echo "  $0 restore"
}

inject_pod_crash() {
    echo "Injecting fault: Pod crash"
    echo "Deleting a pod from deployment ${DEPLOYMENT}..."
    
    POD=$(kubectl get pods -n ${NAMESPACE} -l app=${DEPLOYMENT} -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    
    if [ -z "$POD" ]; then
        echo "Error: No pods found for deployment ${DEPLOYMENT}"
        exit 1
    fi
    
    kubectl delete pod "${POD}" -n ${NAMESPACE} --grace-period=0 --force
    echo "Deleted pod: ${POD}"
    echo ""
    echo "This should trigger: PodNotReady, DeploymentReplicasUnavailable alerts"
}

inject_scale_zero() {
    echo "Injecting fault: Scale to zero"
    echo "Scaling deployment ${DEPLOYMENT} to 0 replicas..."
    
    kubectl scale deployment ${DEPLOYMENT} -n ${NAMESPACE} --replicas=0
    echo "Scaled ${DEPLOYMENT} to 0 replicas"
    echo ""
    echo "This should trigger: DeploymentScaledToZero alert"
}

inject_bad_image() {
    echo "Injecting fault: Bad image"
    echo "Updating deployment ${DEPLOYMENT} with non-existent image..."
    
    kubectl set image deployment/${DEPLOYMENT} nginx=nginx:nonexistent-tag-12345 -n ${NAMESPACE}
    echo "Updated ${DEPLOYMENT} image to nginx:nonexistent-tag-12345"
    echo ""
    echo "This should trigger: ContainerWaiting (ImagePullBackOff) alert"
}

restore_deployment() {
    echo "Restoring deployment to healthy state..."
    
    # Reset image to valid version
    kubectl set image deployment/${DEPLOYMENT} nginx=nginx:1.25 -n ${NAMESPACE}
    
    # Scale back to 2 replicas
    kubectl scale deployment ${DEPLOYMENT} -n ${NAMESPACE} --replicas=2
    
    echo "Waiting for deployment to be ready..."
    kubectl rollout status deployment/${DEPLOYMENT} -n ${NAMESPACE} --timeout=120s
    
    echo "Deployment restored successfully"
}

case "$FAULT_TYPE" in
    pod-crash)
        inject_pod_crash
        ;;
    scale-zero)
        inject_scale_zero
        ;;
    bad-image)
        inject_bad_image
        ;;
    restore)
        restore_deployment
        ;;
    help|--help|-h)
        usage
        ;;
    *)
        echo "Unknown fault type: $FAULT_TYPE"
        echo ""
        usage
        exit 1
        ;;
esac

echo ""
echo "To check alerts, run:"
echo "  curl -s http://localhost:9093/api/v2/alerts | jq"
