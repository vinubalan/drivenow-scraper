# Testing GitHub Actions Workflows Locally

This document explains how to test the GitHub Actions workflows locally before pushing to GitHub.

## Quick Start

The simplest way to test workflows is to simulate the environment variables:

```bash
# Activate virtual environment
source .venv/bin/activate

# Load your .env file
export $(cat .env | grep -v '^#' | xargs)

# Test auto workflow (same-day pickup date)
export CI='true'
python3 scrape.py

# Test manual workflow (specific pickup date)
export CI='true'
export PICKUP_DATE='2025-11-19'
python3 scrape.py

# Test local mode (next-day pickup date - default)
unset CI
unset PICKUP_DATE
python3 scrape.py
```

## Workflow Behavior Summary

| Mode | CI Env | PICKUP_DATE | Pickup Date Logic |
|------|--------|-------------|-------------------|
| **Auto Workflow** | `true` | Not set | Same day at 10 AM AEST |
| **Manual Workflow** | `true` | Set (YYYY-MM-DD) | Specified date at 10 AM AEST |
| **Local Testing** | Not set | Not set | Next day at 10 AM AEST |

## Option 1: Manual Testing Script (Recommended)

Use the provided script to simulate the GitHub Actions environment:

```bash
# Test auto workflow (same-day pickup date)
./test-workflow-local.sh

# Test manual workflow with specific pickup date
PICKUP_DATE='2025-11-19' ./test-workflow-local.sh
```

The script will:
1. Load environment variables from `.env`
2. Set CI mode flags
3. Install dependencies (if needed)
4. Run the scraper

## Option 2: Using `act` (GitHub Actions Runner)

**Note**: `act` can have compatibility issues, especially on M-series Macs. The manual testing method (Option 1) is recommended.

### Installation

```bash
# macOS
brew install act

# Linux
curl https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash

# Or download from: https://github.com/nektos/act/releases
```

### Test Auto Workflow

```bash
# Run the scheduled workflow (will use current date)
act schedule -W .github/workflows/scrape.yml --container-architecture linux/amd64

# Or run it directly
act -W .github/workflows/scrape.yml --container-architecture linux/amd64
```

### Test Manual Workflow

```bash
# Run manual workflow with pickup date input
# Note: Use --container-architecture for M-series Macs
act workflow_dispatch \
  -W .github/workflows/scrape-manual.yml \
  --input pickup_date=2025-11-19 \
  --container-architecture linux/amd64 \
  --secret-file .env
```

### Important Notes for `act`

1. **M-series Macs**: Use `--container-architecture linux/amd64` flag to avoid compatibility issues.

2. **Secrets**: Use `--secret-file .env` to load secrets from your `.env` file:
   ```bash
   act workflow_dispatch \
     -W .github/workflows/scrape-manual.yml \
     --input pickup_date=2025-11-19 \
     --container-architecture linux/amd64 \
     --secret-file .env
   ```

3. **Docker**: `act` uses Docker, so make sure Docker is running.

4. **Platform Differences**: Some steps might behave differently in Docker vs GitHub Actions. The workflows have been updated for Ubuntu 24.04 compatibility.

## Option 3: Direct Testing (Simplest)

Just run the scraper with environment variables:

```bash
# Activate virtual environment
source .venv/bin/activate

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

# Test auto workflow (same-day pickup)
export CI='true'
python3 scrape.py

# Test manual workflow (specific pickup date)
export CI='true'
export PICKUP_DATE='2025-11-19'
python3 scrape.py

# Test local mode (next-day pickup)
unset CI
unset PICKUP_DATE
python3 scrape.py
```

## Workflow Details

### Auto Workflow (`.github/workflows/scrape.yml`)

- **Trigger**: Scheduled daily at 8:00 AM AEST (22:00 UTC previous day)
- **Pickup Date**: Same day at 10:00 AM AEST
- **Environment**: Sets `CI='true'` automatically

### Manual Workflow (`.github/workflows/scrape-manual.yml`)

- **Trigger**: Manual via GitHub Actions UI
- **Pickup Date**: User-specified (YYYY-MM-DD format) at 10:00 AM AEST
- **Environment**: Sets `CI='true'` and `PICKUP_DATE` from input

## Troubleshooting

### Missing Dependencies

Make sure all Python packages are installed:
```bash
pip3 install -r requirements.txt
playwright install chromium
```

### Environment Variables

Ensure `.env` file exists with all required variables:
- Database credentials (Supabase)
- R2 credentials (Cloudflare)

### Database Connection

Verify your database credentials in `.env` are correct and your Supabase project is active.

### Timezone Issues

The scraper uses AEST timezone. Make sure your system timezone is correct or the scraper will handle it automatically.

### Date Format

When testing manual workflow, use `YYYY-MM-DD` format:
- ✅ Correct: `2025-11-19`
- ❌ Incorrect: `11/19/2025`, `19-11-2025`, etc.

## GitHub Actions Secrets

For workflows to run in GitHub Actions, ensure these secrets are configured:

- `DB_HOST`
- `DB_PORT`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET_NAME`
- `R2_PUBLIC_URL` (optional)

See the main `README.md` for more details on setting up GitHub secrets.
