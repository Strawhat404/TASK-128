#!/usr/bin/env bash
# ============================================================
# CRHGC — Unified Test Runner
# Usage: ./run_tests.sh
#
# When called from inside the container (/app/main.py exists),
# runs the test suite directly using the container's Python.
#
# When called from outside, starts the stack if needed and
# delegates test execution into the running app container.
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -----------------------------------------------------------
# INSIDE the container — run the suite directly.
# -----------------------------------------------------------
if [ -f /app/main.py ]; then
    PYTHON="python3"
    PASS=0
    FAIL=0

    echo "=========================================="
    echo "  CRHGC Test Suite  (container runtime)"
    echo "=========================================="
    echo ""

    # Set up headless display
    rm -f /tmp/.X99-lock
    Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &
    sleep 1
    export DISPLAY=:99
    export QT_QPA_PLATFORM=offscreen

    # ---- Headless verification (service flows) ----
    echo "=== Headless Verification (verify.py) ==="
    if "$PYTHON" /app/verify.py; then
        PASS=$((PASS + 1))
        echo "PASS: verify.py"
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: verify.py"
    fi
    echo ""

    # ---- pytest suite ----
    echo "=== Unit / API / E2E Tests (pytest) ==="
    if "$PYTHON" -m pytest /app -q --tb=short; then
        PASS=$((PASS + 1))
        echo "PASS: pytest"
    else
        FAIL=$((FAIL + 1))
        echo "FAIL: pytest"
    fi
    echo ""

    # ---- Summary ----
    echo "=========================================="
    echo "  Test Summary"
    echo "=========================================="
    echo "Suites passed: $PASS"
    echo "Suites failed: $FAIL"
    echo "=========================================="

    if [ "$FAIL" -gt 0 ]; then
        echo "RESULT: SOME TESTS FAILED"
        exit 1
    else
        echo "RESULT: ALL TESTS PASSED"
        exit 0
    fi
fi

# -----------------------------------------------------------
# OUTSIDE the container — ensure stack is up, then exec in.
# -----------------------------------------------------------

# Detect docker compose command (V2 plugin vs V1 standalone)
if docker compose version &>/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE="docker-compose"
else
    echo "Error: Neither 'docker compose' nor 'docker-compose' found." >&2
    exit 1
fi

echo "Starting Docker Compose stack..."
$COMPOSE up -d 2>/dev/null || true

# Wait for container to be running (restart if stopped)
for i in $(seq 1 30); do
    STATUS=$(docker inspect --format='{{.State.Status}}' crhgc-app 2>/dev/null || echo "missing")
    if [ "$STATUS" = "running" ]; then
        break
    elif [ "$STATUS" = "exited" ] || [ "$STATUS" = "stopped" ]; then
        echo "Container stopped, restarting..."
        docker start crhgc-app 2>/dev/null || $COMPOSE up -d 2>/dev/null || true
    fi
    sleep 1
done

# Final check
STATUS=$(docker inspect --format='{{.State.Status}}' crhgc-app 2>/dev/null || echo "missing")
if [ "$STATUS" != "running" ]; then
    echo "Error: crhgc-app container is not running (status: $STATUS)." >&2
    exit 1
fi

echo "Delegating test execution into container: crhgc-app"
docker exec -i crhgc-app bash /app/run_tests.sh
exit $?
