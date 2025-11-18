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
1. Check for and activate virtual environment (or create one if needed)
2. Load environment variables from `.env`
3. Set CI mode flags
4. Check for and install dependencies (if needed)
5. Check for and install Playwright browsers (if needed)
6. Run the scraper with progress bar

**Note**: The script is smart about dependencies - it will skip installation if packages are already available, making subsequent runs faster.

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

5. **Environment Variables**: Note that `act` expects environment variable names to match GitHub secrets. The workflows use `SUPABASE_DB_*` prefix for database variables.

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
- **Caching**: Caches pip dependencies and Playwright browsers for faster runs

### Manual Workflow (`.github/workflows/scrape-manual.yml`)

- **Trigger**: Manual via GitHub Actions UI
- **Pickup Date**: User-specified (YYYY-MM-DD format) at 10:00 AM AEST
- **Environment**: Sets `CI='true'` and `PICKUP_DATE` from input
- **Validation**: Validates pickup date format before running
- **Caching**: Caches pip dependencies and Playwright browsers for faster runs

## Expected Output

When running locally, you should see:

```
============================================================
DriveNow Scraper - Starting Collection
============================================================
Pickup date: 2025-11-19 10:00 AEST (next day)
Return dates: 2025-11-20, 2025-11-26, 2025-12-03
Processing 12 city-date combinations...
⠋ Scraping vehicles... Sydney 2025-11-19→2025-11-20: 30 vehicles ████████░░ 67% (8/12) 0:02:15
✓ Collection complete: 360 vehicles collected in 2m 45s
============================================================
✓ Collection complete! Total time: 2m 45s (165.0 seconds)
============================================================

Collection Summary
Total vehicles collected: 360
  Sydney: 90 vehicles
  Melbourne: 90 vehicles
  Brisbane: 90 vehicles
  Adelaide: 90 vehicles

Vehicles with URLs: 360/360
Vehicles with screenshots: 360/360
```

## Troubleshooting

### Missing Dependencies

Make sure all Python packages are installed:
```bash
pip3 install -r requirements.txt
playwright install chromium
```

The `test-workflow-local.sh` script will check and install dependencies automatically.

### Environment Variables

Ensure `.env` file exists with all required variables:
- Database credentials (Supabase) - use `SUPABASE_DB_*` prefix
- R2 credentials (Cloudflare)

**Important**: The environment variable names use `SUPABASE_DB_*` prefix (not `DB_*`).

### Database Connection

Verify your database credentials in `.env` are correct and your Supabase project is active.

### Timezone Issues

The scraper uses AEST timezone. Make sure your system timezone is correct or the scraper will handle it automatically.

### Date Format

When testing manual workflow, use `YYYY-MM-DD` format:
- ✅ Correct: `2025-11-19`
- ❌ Incorrect: `11/19/2025`, `19-11-2025`, etc.

### Progress Bar Not Showing

- Some terminals may not support progress bars
- Detailed logs are always available in `scraper.log`
- Query the database directly to verify data was collected correctly

### Virtual Environment Issues

If the `test-workflow-local.sh` script has issues with the virtual environment:
- Delete `.venv` and let the script recreate it
- Or manually create: `python3 -m venv .venv && source .venv/bin/activate`

## GitHub Actions Secrets

For workflows to run in GitHub Actions, ensure these secrets are configured:

- `SUPABASE_DB_HOST`
- `SUPABASE_DB_PORT`
- `SUPABASE_DB_NAME`
- `SUPABASE_DB_USER`
- `SUPABASE_DB_PASSWORD`
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET_NAME`
- `R2_PUBLIC_URL` (optional)

**Note**: The secrets use `SUPABASE_DB_*` prefix to match the environment variable names used in the workflows.

See the main `README.md` for more details on setting up GitHub secrets.

## Workflow Caching

Both workflows include caching for:
- **pip dependencies**: Speeds up dependency installation
- **Playwright browsers**: Speeds up browser installation

Caches are automatically invalidated when `requirements.txt` changes, ensuring you always have the latest dependencies.
