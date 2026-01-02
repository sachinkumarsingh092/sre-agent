#!/bin/bash
# End-to-end test runner for SRE Agent MVP

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CONFIG_FILE="${PROJECT_DIR}/config.yaml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check if cluster is running
    if ! kubectl cluster-info &>/dev/null; then
        log_error "Kubernetes cluster is not accessible"
        exit 1
    fi
    
    # Check if Prometheus is accessible
    if ! curl -s http://localhost:9090/-/healthy &>/dev/null; then
        log_error "Prometheus is not accessible at localhost:9090"
        log_warn "Run: kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090"
        exit 1
    fi
    
    # Check if AlertManager is accessible
    if ! curl -s http://localhost:9093/-/healthy &>/dev/null; then
        log_error "AlertManager is not accessible at localhost:9093"
        log_warn "Run: kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-alertmanager 9093:9093"
        exit 1
    fi
    
    # Check if vLLM is accessible (optional - will fail at runtime if not)
    if curl -s http://localhost:8000/v1/models &>/dev/null; then
        log_info "vLLM server is accessible"
    else
        log_warn "vLLM server is not accessible at localhost:8000"
        log_warn "Make sure vLLM is running before running the agent"
    fi
    
    log_info "Prerequisites check passed"
}

run_test() {
    local fault_type="$1"
    local test_name="$2"
    
    echo ""
    echo "============================================"
    echo "TEST: ${test_name}"
    echo "============================================"
    
    # Ensure clean state
    log_info "Restoring deployment to healthy state..."
    "${SCRIPT_DIR}/inject-fault.sh" restore &>/dev/null || true
    sleep 5
    
    # Verify no alerts
    log_info "Verifying no alerts are firing..."
    alerts=$(curl -s http://localhost:9093/api/v2/alerts | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    if [ "$alerts" != "0" ]; then
        log_warn "There are $alerts alerts still firing, waiting for them to clear..."
        sleep 30
    fi
    
    # Inject fault
    log_info "Injecting fault: ${fault_type}"
    "${SCRIPT_DIR}/inject-fault.sh" "${fault_type}"
    
    # Wait for alert to fire
    log_info "Waiting for alerts to fire..."
    sleep 45
    
    # Check alerts
    alerts=$(curl -s http://localhost:9093/api/v2/alerts)
    alert_count=$(echo "$alerts" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    log_info "Active alerts: ${alert_count}"
    
    if [ "$alert_count" == "0" ]; then
        log_warn "No alerts detected - fault injection may have failed"
    fi
    
    # Run agent
    log_info "Running SRE Agent..."
    cd "${PROJECT_DIR}"
    
    if python -m sre_agent.main -c "${CONFIG_FILE}" --once -v; then
        log_info "Agent completed successfully"
    else
        log_error "Agent failed"
    fi
    
    # Check if alerts cleared
    log_info "Checking if alerts cleared..."
    sleep 10
    
    final_alerts=$(curl -s http://localhost:9093/api/v2/alerts)
    final_count=$(echo "$final_alerts" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    
    if [ "$final_count" == "0" ]; then
        log_info "✅ TEST PASSED: All alerts cleared"
        return 0
    else
        log_warn "⚠️  TEST INCOMPLETE: $final_count alerts still firing"
        return 1
    fi
}

# Main execution
echo "============================================"
echo "SRE Agent MVP - End-to-End Test Runner"
echo "============================================"

check_prerequisites

# Parse arguments
TEST_TYPE="${1:-all}"

case "$TEST_TYPE" in
    pod-crash)
        run_test "pod-crash" "Pod Crash Recovery"
        ;;
    scale-zero)
        run_test "scale-zero" "Scale Zero Recovery"
        ;;
    bad-image)
        run_test "bad-image" "Bad Image Recovery"
        ;;
    all)
        log_info "Running all tests..."
        
        run_test "pod-crash" "Pod Crash Recovery" || true
        sleep 30
        
        run_test "scale-zero" "Scale Zero Recovery" || true
        sleep 30
        
        # Note: bad-image test requires manual intervention to fix
        # as it's harder for the agent to determine correct image
        log_info "Skipping bad-image test (requires manual image knowledge)"
        ;;
    *)
        echo "Usage: $0 [pod-crash|scale-zero|bad-image|all]"
        exit 1
        ;;
esac

echo ""
echo "============================================"
echo "Test run complete"
echo "============================================"
echo ""
echo "Check output/ directory for incident files"
ls -la "${PROJECT_DIR}/output/" 2>/dev/null || echo "No output files yet"
