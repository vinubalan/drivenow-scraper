#!/bin/bash
# Script to test GitHub Actions workflows locally
# This simulates the workflow environment

set -e

echo "=========================================="
echo "Testing GitHub Actions Workflow Locally"
echo "=========================================="

# Check if .env file exists
if [ ! -f .env ]; then
    echo "Error: .env file not found. Please create one with your database and R2 credentials."
    exit 1
fi

# Load environment variables from .env
export $(cat .env | grep -v '^#' | xargs)

# Set CI environment variables (simulating GitHub Actions)
export CI='true'
export GITHUB_ACTIONS='true'

# For manual workflow testing, uncomment and set pickup date:
# export PICKUP_DATE='2025-11-19'

echo "Environment variables loaded"
echo "CI mode: $CI"
if [ ! -z "$PICKUP_DATE" ]; then
    echo "Manual pickup date: $PICKUP_DATE"
fi

echo ""
echo "Installing Python dependencies..."
python3 -m pip install --upgrade pip
pip3 install -r requirements.txt

echo ""
echo "Installing Playwright browsers..."
playwright install chromium

echo ""
echo "Running scraper..."
python3 scrape.py

echo ""
echo "=========================================="
echo "Workflow test completed!"
echo "=========================================="

