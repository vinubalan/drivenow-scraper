#!/bin/bash
# Script to test GitHub Actions workflows locally
# This simulates the workflow environment
# Uses existing virtual environment if available, otherwise creates one

set -e

echo "=========================================="
echo "Testing GitHub Actions Workflow Locally"
echo "=========================================="

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Error: .env file not found. Please create one with your database and R2 credentials."
    exit 1
fi

# Handle virtual environment
if [ -d ".venv" ]; then
    echo "✓ Using existing virtual environment (.venv)"
    source .venv/bin/activate
    
    # Check if pip is available in the venv
    if ! python3 -m pip --version >/dev/null 2>&1; then
        echo "⚠ pip not found in venv. Attempting to install pip..."
        if python3 -m ensurepip --upgrade >/dev/null 2>&1; then
            echo "✓ pip installed successfully"
        else
            echo "⚠ Could not install pip. Recreating virtual environment..."
            rm -rf .venv
            python3 -m venv .venv
            source .venv/bin/activate
            echo "✓ Virtual environment recreated and activated"
        fi
    fi
else
    echo "⚠ No virtual environment found. Creating new one..."
    python3 -m venv .venv
    source .venv/bin/activate
    echo "✓ Virtual environment created and activated"
fi

# Verify we're using the venv Python
VENV_PYTHON=$(which python3)
echo "Using Python: $VENV_PYTHON"

# Load environment variables from .env
export $(cat .env | grep -v '^#' | xargs)

# Set CI environment variables (simulating GitHub Actions)
export CI='true'
export GITHUB_ACTIONS='true'

# PICKUP_DATE can be passed as environment variable when calling the script
# e.g., PICKUP_DATE='2025-11-19' ./test-workflow-local.sh

echo ""
echo "Environment variables loaded"
echo "CI mode: $CI"
if [ ! -z "$PICKUP_DATE" ]; then
    echo "Manual pickup date: $PICKUP_DATE"
else
    echo "Auto mode: Using same-day pickup date"
fi

echo ""
# Check if dependencies are already installed
if python3 -c "import playwright, psycopg2, yaml, PIL, pytz, boto3" >/dev/null 2>&1; then
    echo "✓ Dependencies already installed, skipping installation"
else
    echo "Installing/upgrading Python dependencies..."
    python3 -m pip install --upgrade pip --quiet
    pip3 install -r requirements.txt --quiet
fi

echo ""
# Check if Playwright browsers are installed (check cache directory)
PLAYWRIGHT_CACHE="$HOME/.cache/ms-playwright"
if [ -d "$PLAYWRIGHT_CACHE" ] && [ -n "$(find "$PLAYWRIGHT_CACHE" -name 'chromium-*' -type d 2>/dev/null | head -1)" ]; then
    echo "✓ Playwright browsers already installed, skipping installation"
else
    echo "Installing Playwright browsers..."
    playwright install chromium
fi

echo ""
echo "Running scraper..."
python3 scrape.py

echo ""
echo "=========================================="
echo "Workflow test completed!"
echo "=========================================="

