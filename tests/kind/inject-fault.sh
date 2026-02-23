#!/bin/bash
# Fault injection script for testing SRE Agent

set -e

FAULT_TYPE="${1:-help}"
NAMESPACE="default"
DEPLOYMENT="nginx-test"

export KUBECONFIG=/Users/sachinsingh/dev/sachinkumarsingh092/sre-agent/sre-agent-mvp/k8s/custom-kubeconfig.yaml

usage() {
    echo "Usage: $0 <fault-type>"
    echo ""
    echo "Available fault types:"
    echo "  pod-crash     - Delete a pod to simulate crash"
    echo "  scale-zero    - Scale deployment to zero replicas"
    echo "  bad-image     - Update deployment with non-existent image"
    echo "  random-crash  - Intermittent CrashLoopBackOff (hard to diagnose)"
    echo "  cascade       - Cascading multi-service failure (stress test)"
    echo "  restore       - Restore deployment to healthy state"
    echo ""
    echo "Examples:"
    echo "  $0 pod-crash"
    echo "  $0 scale-zero"
    echo "  $0 random-crash"
    echo "  $0 cascade"
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

inject_random_crash() {
    echo "Injecting fault: Intermittent CrashLoopBackOff"
    echo "Patching deployment ${DEPLOYMENT} to crash randomly after 0-30 seconds..."
    
    kubectl patch deployment ${DEPLOYMENT} -n ${NAMESPACE} -p '{"spec":{"template":{"spec":{"containers":[{"name":"nginx","command":["/bin/sh","-c","sleep $((RANDOM % 30)); exit 1"]}]}}}}'
    
    echo "Patched ${DEPLOYMENT} with random crash behavior"
    echo ""
    echo "This should trigger: CrashLoopBackOff alerts"
    echo "NOTE: This is hard to diagnose - pod crashes randomly, logs may be empty"
    echo "      LLM will need multiple tool calls to investigate"
}

inject_cascade() {
    echo "Injecting fault: Cascading multi-service failure"
    echo "Deploying backend-app that depends on nginx-test, then breaking nginx..."
    
    # First ensure nginx-test is healthy
    echo "Step 1: Ensuring nginx-test is running..."
    kubectl set image deployment/${DEPLOYMENT} nginx=nginx:1.25 -n ${NAMESPACE} 2>/dev/null || true
    kubectl scale deployment ${DEPLOYMENT} -n ${NAMESPACE} --replicas=2
    kubectl rollout status deployment/${DEPLOYMENT} -n ${NAMESPACE} --timeout=60s || true
    
    # Deploy backend-app that depends on nginx-test
    echo "Step 2: Deploying backend-app (depends on nginx-test)..."
    kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: nginx-test
  namespace: ${NAMESPACE}
spec:
  selector:
    app: nginx-test
  ports:
  - port: 80
    targetPort: 80
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend-app
  namespace: ${NAMESPACE}
  labels:
    app: backend-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: backend-app
  template:
    metadata:
      labels:
        app: backend-app
    spec:
      containers:
      - name: curl
        image: curlimages/curl:latest
        command: ["/bin/sh", "-c"]
        args:
        - |
          while true; do
            if ! curl -sf http://nginx-test:80/ > /dev/null 2>&1; then
              echo "ERROR: Cannot reach nginx-test service"
              exit 1
            fi
            echo "OK: nginx-test is reachable"
            sleep 5
          done
        livenessProbe:
          exec:
            command: ["curl", "-sf", "http://nginx-test:80/"]
          initialDelaySeconds: 10
          periodSeconds: 10
          failureThreshold: 2
EOF
    
    echo "Waiting for backend-app to be ready..."
    kubectl rollout status deployment/backend-app -n ${NAMESPACE} --timeout=60s || true
    sleep 5
    
    # Now break nginx-test - this will cause backend-app to fail too
    echo "Step 3: Breaking nginx-test (scaling to zero)..."
    kubectl scale deployment ${DEPLOYMENT} -n ${NAMESPACE} --replicas=0
    
    echo ""
    echo "Cascading failure injected!"
    echo "  - nginx-test: scaled to 0 replicas"
    echo "  - backend-app: will fail liveness probes and enter CrashLoopBackOff"
    echo ""
    echo "This should trigger multiple alerts and require the LLM to:"
    echo "  1. Investigate backend-app failures"
    echo "  2. Check logs showing 'Cannot reach nginx-test'"
    echo "  3. Investigate nginx-test and find it has 0 replicas"
    echo "  4. Diagnose the cascading dependency"
    echo ""
    echo "This is a STRESS TEST for the memory system - expect many tool calls!"
}

restore_deployment() {
    echo "Restoring deployments to healthy state..."
    
    # Remove any command overrides (for random-crash fault)
    echo "Step 1: Removing command overrides from nginx-test..."
    kubectl patch deployment ${DEPLOYMENT} -n ${NAMESPACE} --type=json \
        -p='[{"op": "remove", "path": "/spec/template/spec/containers/0/command"}]' 2>/dev/null || true
    
    # Reset image to valid version
    echo "Step 2: Resetting nginx-test image..."
    kubectl set image deployment/${DEPLOYMENT} nginx=nginx:1.25 -n ${NAMESPACE}
    
    # Scale back to 2 replicas
    echo "Step 3: Scaling nginx-test to 2 replicas..."
    kubectl scale deployment ${DEPLOYMENT} -n ${NAMESPACE} --replicas=2
    
    echo "Step 4: Waiting for nginx-test to be ready..."
    kubectl rollout status deployment/${DEPLOYMENT} -n ${NAMESPACE} --timeout=120s
    
    # Clean up backend-app if it exists (from cascade fault)
    if kubectl get deployment backend-app -n ${NAMESPACE} >/dev/null 2>&1; then
        echo "Step 5: Cleaning up backend-app from cascade test..."
        kubectl delete deployment backend-app -n ${NAMESPACE} --ignore-not-found
    fi
    
    echo ""
    echo "All deployments restored successfully"
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
    random-crash)
        inject_random_crash
        ;;
    cascade)
        inject_cascade
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
