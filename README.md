# DriveNow Scraper

A Python-based web scraper for collecting hire car vehicle listings from [DriveNow.com.au](https://www.drivenow.com.au/). The scraper runs daily via GitHub Actions, collects vehicle data, captures full-page screenshots of results pages, and stores everything in Supabase (PostgreSQL) with screenshots in Cloudflare R2 for historical analysis.

## Features

- **Configurable Cities**: Sydney, Melbourne, Brisbane, and Adelaide (easily expandable)
- **Automatic Date Calculation**: 
  - **Auto Workflow**: Pickup date is same day at 10:00 AM AEST (runs at 8:00 AM AEST)
  - **Manual Workflow**: Specify custom pickup date
  - **Local Testing**: Pickup date is next day at 10:00 AM AEST
  - Return dates: Configurable (default: +1, +7, +14 days at 10:00 AM AEST)
- **Full-Page Screenshots**: One screenshot per city-date combination with watermarks showing screenshot time
- **Parallel Processing**: Fast scraping with multiple workers (configurable)
- **Rate Limiting**: Built-in delays and randomization to avoid getting blocked
- **Anti-Detection**: User agent rotation, viewport randomization, and stealth features
- **Cloud Database**: Stores all vehicle data in Supabase (PostgreSQL)
- **Cloud Storage**: Screenshots stored in Cloudflare R2 with compression
- **GitHub Actions**: Automated daily runs at 8:00 AM AEST with manual trigger support
- **Robust Error Handling**: Continues scraping even if individual searches fail
- **AEST Timezone**: All timestamps are in Australian Eastern Standard Time
- **Clean Console Output**: Progress bars and minimal logging for better visibility

## Requirements

- Python 3.11 or higher
- Internet connection
- Supabase account (PostgreSQL database)
- Cloudflare R2 account (for screenshot storage)

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd drivenow-scraper
   ```

2. **Create virtual environment (recommended):**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Playwright browsers:**
   ```bash
   playwright install chromium
   ```

5. **Set up environment variables:**
   Create a `.env` file in the project root with the following variables:
   ```bash
   # Database (Supabase PostgreSQL)
   SUPABASE_DB_HOST=your-supabase-host
   SUPABASE_DB_PORT=5432
   SUPABASE_DB_NAME=postgres
   SUPABASE_DB_USER=postgres
   SUPABASE_DB_PASSWORD=your-database-password
   
   # Cloudflare R2
   R2_ACCOUNT_ID=your-r2-account-id
   R2_ACCESS_KEY_ID=your-r2-access-key-id
   R2_SECRET_ACCESS_KEY=your-r2-secret-access-key
   R2_BUCKET_NAME=your-bucket-name
   R2_PUBLIC_URL=https://your-public-url.com  # Optional
   ```

6. **Configure Supabase:**
   - Create a Supabase project
   - Get your database connection details from Supabase dashboard
   - The `vehicles` table will be created automatically on first run

7. **Configure Cloudflare R2:**
   - Create an R2 bucket in Cloudflare dashboard
   - Create API tokens with read/write access
   - Optionally set up a public URL for accessing screenshots

## Configuration

Edit `config.yaml` to customize:

- **Cities**: Add or remove cities to scrape (includes latitude, longitude, location string, and radius)
- **Date ranges**: Modify return days (currently +1, +7, +14 days)
- **Times**: Change pickup/return times (currently 10:00 AM)
- **Screenshot settings**: Enable/disable screenshots, change directory
- **Rate limiting**: Adjust delays between requests, vehicles, and cities
- **Anti-detection**: Configure user agent rotation and viewport randomization
- **Browser settings**: Toggle headless mode, adjust window size
- **Parallel processing**: Configure number of workers for faster scraping

### Example Configuration

```yaml
cities:
  - name: "Sydney"
    code: "SYD"
    latitude: -33.86706149922719
    longitude: 151.2155219586914
    location_string: "Sydney, New South Wales, Australia"
    radius: 3

date_config:
  pickup_time: "10:00"
  return_time: "10:00"
  return_days: [1, 7, 14]

scraper:
  parallel:
    enabled: true
    workers: 5
  rate_limiting:
    delay_between_requests: 3.0
    delay_between_vehicles: 2.0
    delay_between_cities: 5.0
```

## Usage

### Run the Scraper Locally

```bash
# Activate virtual environment
source .venv/bin/activate

# Run scraper (uses next-day pickup date for local testing)
python3 scrape.py
```

The scraper will:
1. Calculate dates based on mode (local = next day, CI = same day, manual = specified date)
2. Display a progress bar showing scraping progress
3. For each city and date combination:
   - Navigate to the results page
   - Wait for page to fully load
   - Extract all vehicle listings
   - Capture a full-page screenshot with watermark
   - Compress and upload screenshot to R2
   - Save vehicle data to database
4. Show completion summary with timing information

### Console Output

The scraper provides clean, minimal console output with:
- Progress bar showing current city, dates, and vehicle count
- Important status messages (pickup dates, completion)
- Errors and warnings only
- Final summary with total vehicles collected and time taken

All detailed logs are saved to `scraper.log` for debugging.

### Utility Scripts

**Clear Database:**
```bash
python3 clear_database.py
```

**Clear R2 Screenshots:**
```bash
python3 clear_r2_screenshots.py
```

**Test Workflow Locally:**
```bash
# Test auto workflow (same-day pickup)
export CI='true'
python3 scrape.py

# Test manual workflow (specific pickup date)
export CI='true'
export PICKUP_DATE='2025-11-19'
python3 scrape.py
```

See `README-WORKFLOWS.md` for more details on testing workflows locally.

### Quick Commands

```bash
# Run scraper
python3 scrape.py

# Check database status (count vehicles scraped today)
python3 -c "from database import Database; from datetime import datetime; import pytz; aest = pytz.timezone('Australia/Sydney'); today = datetime.now(aest).strftime('%Y-%m-%d'); db = Database(); vehicles = db.get_vehicles_by_date(today); print(f'Total vehicles (today): {len(vehicles)}'); db.close()"

# Clean local files
rm -rf screenshots/*.png screenshots/*.jpg *.log scraper.log __pycache__ *.pyc 2>/dev/null || true
```

## Database Schema

The scraper creates a single `vehicles` table automatically:

### `vehicles` table

- `id`: Primary key
- `scrape_datetime`: Timestamp when scraping occurred (TIMESTAMPTZ, stored in AEST)
- `city`: City name
- `pickup_date`: Pickup date and time (TIMESTAMP without timezone, represents AEST time)
- `return_date`: Return date and time (TIMESTAMP without timezone, represents AEST time)
- `vehicle_name`: Name of the vehicle
- `vehicle_type`: Type/category of vehicle
- `seats`: Number of seats
- `doors`: Number of doors
- `transmission`: Transmission type
- `excess`: Excess amount
- `fuel_type`: Fuel type (Electric, Hybrid, etc.)
- `logo_url`: Provider logo URL
- `price_per_day`: Price per day
- `total_price`: Total price for the rental period
- `currency`: Currency (default: AUD)
- `detail_url`: URL to vehicle detail page
- `screenshot_path`: Path/URL to screenshot (shared by all vehicles in same city-date combination)
- `depot_code`: Depot code (extracted from URL)
- `supplier_code`: Supplier code (extracted from logo URL)
- `city_latitude`: City latitude
- `city_longitude`: City longitude

**Note**: Screenshots are stored directly in the `vehicles` table via the `screenshot_path` column. One screenshot is captured per city-date combination, and all vehicles from that combination share the same screenshot path.

## Querying the Database

You can query the Supabase database using any PostgreSQL client or the Supabase dashboard.

### Example Queries

```sql
-- Get all vehicles scraped today
SELECT * FROM vehicles WHERE DATE(scrape_datetime) = CURRENT_DATE;

-- Get vehicles for a specific city and date
SELECT * FROM vehicles 
WHERE city = 'Sydney' AND DATE(scrape_datetime) = '2025-11-19';

-- Count vehicles by city
SELECT city, COUNT(*) as count 
FROM vehicles 
GROUP BY city;

-- Get vehicles with screenshots
SELECT * FROM vehicles 
WHERE screenshot_path IS NOT NULL 
AND screenshot_path != '';

-- Get unique screenshots per city-date combination
SELECT DISTINCT 
    city, 
    pickup_date, 
    return_date, 
    screenshot_path,
    COUNT(*) as vehicle_count
FROM vehicles 
WHERE screenshot_path IS NOT NULL
GROUP BY city, pickup_date, return_date, screenshot_path;

-- Get average prices by city
SELECT city, AVG(CAST(REPLACE(total_price, '$', '') AS NUMERIC)) as avg_price
FROM vehicles
WHERE total_price IS NOT NULL
GROUP BY city;

-- Get vehicles by supplier
SELECT supplier_code, COUNT(*) as count
FROM vehicles
WHERE supplier_code IS NOT NULL
GROUP BY supplier_code
ORDER BY count DESC;
```

## GitHub Actions

The scraper includes two GitHub Actions workflows:

### 1. Auto Workflow (`.github/workflows/scrape.yml`)
- Runs automatically at **8:00 AM AEST** every day
- Uses **same-day pickup date** at 10:00 AM AEST
- Example: If it runs on Nov 19 at 8am, pickup date is Nov 19 at 10:00 AM AEST
- Includes caching for faster runs

### 2. Manual Workflow (`.github/workflows/scrape-manual.yml`)
- Triggered manually via GitHub Actions UI
- Requires a pickup date input (format: `YYYY-MM-DD`, e.g., `2025-11-19`)
- Uses the specified pickup date at 10:00 AM AEST
- Includes caching for faster runs

### Required GitHub Secrets

Add these secrets to your GitHub repository (Settings → Secrets and variables → Actions):

- `SUPABASE_DB_HOST`: Your Supabase database host
- `SUPABASE_DB_PORT`: Database port (usually 5432)
- `SUPABASE_DB_NAME`: Database name (usually "postgres")
- `SUPABASE_DB_USER`: Database user (usually "postgres")
- `SUPABASE_DB_PASSWORD`: Your Supabase database password
- `R2_ACCOUNT_ID`: Your Cloudflare R2 account ID
- `R2_ACCESS_KEY_ID`: R2 access key ID
- `R2_SECRET_ACCESS_KEY`: R2 secret access key
- `R2_BUCKET_NAME`: Your R2 bucket name
- `R2_PUBLIC_URL`: (Optional) Public URL for accessing screenshots

See `README-WORKFLOWS.md` for detailed information on testing workflows locally.

## Project Structure

```
drivenow-scraper/
├── scrape.py                  # Main entry point script
├── scraper.py                 # Core scraping logic
├── database.py                # Database operations (Supabase)
├── cloud_storage.py           # Cloudflare R2 storage operations
├── clear_database.py          # Utility: Clear database tables
├── clear_r2_screenshots.py    # Utility: Clear R2 screenshots
├── config.yaml                # Configuration file
├── requirements.txt           # Python dependencies
├── test-workflow-local.sh     # Script to test workflows locally
├── README.md                  # This file
├── README-WORKFLOWS.md        # Workflow testing documentation
├── LICENSE                    # Apache License 2.0
├── .env                       # Environment variables (not in git)
├── .github/
│   └── workflows/
│       ├── scrape.yml         # Auto workflow (daily at 8am AEST)
│       └── scrape-manual.yml  # Manual workflow (with pickup date input)
└── screenshots/               # Local screenshot directory (temporary)
```

## Troubleshooting

### Playwright Installation Issues
- If Playwright browsers aren't installed, run: `playwright install chromium`
- Ensure you have sufficient disk space (browsers are ~200MB)

### Rate Limiting and Blocking
- If you're getting blocked, increase delays in `config.yaml`:
  - `delay_between_requests`: Increase to 5-10 seconds
  - `delay_between_vehicles`: Increase to 3-5 seconds
  - `delay_between_cities`: Increase to 10-15 seconds
- Reduce `workers` in parallel config to avoid detection
- The scraper includes random delays to avoid detection patterns

### Website Structure Changes
- If scraping fails, the website structure may have changed
- Check `scraper.log` for detailed error messages
- You may need to update CSS selectors in `scraper.py`
- Try running with `headless: false` in `config.yaml` to see what's happening

### No Vehicles Found
- The website may require different selectors
- Check if the website has changed its HTML structure
- Verify the URL pattern is still correct in `config.yaml`
- Check if the website requires cookies or has anti-bot protection

### Database Connection Issues
- Verify your `.env` file has correct Supabase credentials
- Check if your Supabase project is active
- Ensure your IP is whitelisted in Supabase (if required)
- Note: Environment variable names use `SUPABASE_DB_*` prefix

### R2 Storage Issues
- Verify your `.env` file has correct R2 credentials
- Check if your R2 bucket exists and is accessible
- Verify API tokens have correct permissions

### Screenshot Issues
- Screenshots are compressed and watermarked automatically
- Large screenshots may take time to process (timeout is 120 seconds)
- Check R2 bucket permissions if uploads fail
- Screenshots are shared across all vehicles in the same city-date combination

### Console Output Issues
- Progress bar may not display correctly in some terminals
- Detailed logs are always available in `scraper.log`
- Query the database directly to verify data was collected correctly

## Notes

- **Respect Website Terms**: Ensure your scraping activities comply with DriveNow's terms of service
- **Rate Limiting**: The scraper includes delays between requests to be respectful
- **Data Accuracy**: Vehicle data depends on the website's current structure and may need periodic updates
- **Timezone**: 
  - `scrape_datetime` is stored as TIMESTAMPTZ with AEST timezone
  - `pickup_date` and `return_date` are stored as TIMESTAMP (without timezone) and represent AEST times (e.g., `2025-11-19 10:00:00`)
- **Screenshots**: Full-page screenshots are compressed (JPEG) and include watermarks with screenshot time
- **Database Schema**: Only the `vehicles` table is used. Screenshots are stored via the `screenshot_path` column.

## License

Apache License 2.0
