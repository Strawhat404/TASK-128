#!/usr/bin/env bash
# ============================================================
# CRHGC — Unified Test Runner
# Usage: ./run_tests.sh
#
# When run outside a container, delegates to Docker where all
# runtime dependencies (Python, pytest, cryptography, PyQt6,
# Xvfb) are pre-installed — no local pip install required.
#
# Inside the container, pytest is guaranteed available because
# requirements.txt is installed during the Docker build.
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -----------------------------------------------------------
# Outside container → delegate to Docker (self-contained)
# -----------------------------------------------------------
if [ ! -f /.dockerenv ]; then
    echo "Not inside a container — delegating to Docker..."
    docker compose --profile test run --rm \
        -e DISPLAY=:99 \
        -e QT_QPA_PLATFORM=offscreen \
        test
    exit $?
fi

# -----------------------------------------------------------
# Inside container — all deps are available via Docker image
# -----------------------------------------------------------
PYTHON="${PYTHON:-python3}"
PASS=0
FAIL=0

echo "=========================================="
echo "  CRHGC Test Suite  (container runtime)"
echo "=========================================="
echo ""

# ---- Headless verification (service flows) ----
echo "=== Headless Verification (verify.py) ==="
if "$PYTHON" verify.py; then
    PASS=$((PASS + 1))
    echo "  PASS: verify.py"
else
    FAIL=$((FAIL + 1))
    echo "  FAIL: verify.py"
fi
echo ""

# ---- pytest suite ----
# pytest is always installed inside the container image
# (listed in requirements.txt, installed at build time).
echo "=== Unit / API / E2E Tests (pytest) ==="
if "$PYTHON" -m pytest -q --tb=short; then
    PASS=$((PASS + 1))
    echo "  PASS: pytest"
else
    FAIL=$((FAIL + 1))
    echo "  FAIL: pytest"
fi
echo ""

# ---- Summary ----
echo "=========================================="
echo "  Test Summary"
echo "=========================================="
echo "  Suites passed: $PASS"
echo "  Suites failed: $FAIL"
echo "=========================================="

if [ "$FAIL" -gt 0 ]; then
    echo "RESULT: SOME TESTS FAILED"
    exit 1
else
    echo "RESULT: ALL TESTS PASSED"
    exit 0
fi
