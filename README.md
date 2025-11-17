# DriveNow Scraper

A Python-based web scraper for collecting hire car vehicle listings from [DriveNow.com.au](https://www.drivenow.com.au/). The scraper runs daily via GitHub Actions, collects vehicle data, takes screenshots, and stores everything in Supabase (PostgreSQL) with screenshots in Cloudflare R2 for historical analysis.

## Features

- **Configurable Cities**: Start with Sydney, Melbourne, and Brisbane (easily expandable)
- **Automatic Date Calculation**: 
  - Pickup date: Next day at 10:00 AM
  - Return dates: +1, +2, +3, +4, +5, +6, +7 days at 10:00 AM
- **Individual Vehicle Screenshots**: Clicks "See Details" for each vehicle and captures a screenshot of the detail page
- **Rate Limiting**: Built-in delays and randomization to avoid getting blocked
- **Anti-Detection**: User agent rotation, viewport randomization, and stealth features
- **Cloud Database**: Stores all vehicle data in Supabase (PostgreSQL)
- **Cloud Storage**: Screenshots stored in Cloudflare R2
- **GitHub Actions**: Automated daily runs at 10 AM with manual trigger support
- **Robust Error Handling**: Continues scraping even if individual searches fail

## Requirements

- Python 3.8 or higher
- Internet connection

## Installation

1. Clone or download this repository

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Install Playwright browsers:
```bash
playwright install chromium
```

4. Set up environment variables:
   - Copy `.env.example` to `.env`
   - Fill in your Supabase database credentials
   - Fill in your Cloudflare R2 credentials

5. Configure Supabase:
   - Create a Supabase project
   - Get your database connection details from Supabase dashboard
   - The tables will be created automatically on first run

6. Configure Cloudflare R2:
   - Create an R2 bucket in Cloudflare dashboard
   - Create API tokens with read/write access
   - Optionally set up a public URL for accessing screenshots

## Configuration

Edit `config.yaml` to customize:

- **Cities**: Add or remove cities to scrape
- **Date ranges**: Modify return days (currently +1 to +7 days)
- **Times**: Change pickup/return times (currently 10:00 AM)
- **Screenshot settings**: Enable/disable screenshots, change directory
- **Rate limiting**: Adjust delays between requests, vehicles, and cities
- **Anti-detection**: Configure user agent rotation and viewport randomization
- **Browser settings**: Toggle headless mode, adjust window size

### Example Configuration

```yaml
cities:
  - name: "Sydney"
    code: "SYD"
  - name: "Melbourne"
    code: "MEL"
  - name: "Brisbane"
    code: "BNE"

date_config:
  pickup_time: "10:00"
  return_time: "10:00"
  return_days: [1, 2, 3, 4, 5, 6, 7]
```

## Usage

### Run the Scraper

```bash
python main.py
```

The scraper will:
1. Calculate dates (next day + return dates)
2. For each city, search for vehicles for each date range
3. For each vehicle found, click "See Details" button
4. Wait for detail page to load and take a screenshot
5. Extract vehicle information (name, price, category, etc.)
6. Save vehicle data and screenshot to database
7. Return to results page and repeat for next vehicle

**Note**: Each vehicle gets its own screenshot. If there are 25 vehicles, you'll get 25 screenshots.

### View Logs

Logs are written to both console and `scraper.log` file.

## Database Schema

The scraper creates two tables:

### `vehicles` table
- `id`: Primary key
- `scrape_date`: Date when scraping occurred (YYYY-MM-DD)
- `scrape_timestamp`: Full timestamp of scrape
- `city`: City name
- `pickup_date`: Pickup date and time (ISO format)
- `return_date`: Return date and time (ISO format)
- `vehicle_name`: Name of the vehicle
- `vehicle_category`: Category/type of vehicle
- `price_per_day`: Price per day (if available)
- `total_price`: Total price for the rental period
- `currency`: Currency (default: AUD)
- `availability`: Availability status
- `vehicle_details`: JSON string with additional details
- `screenshot_path`: Path to screenshot file
- `created_at`: Timestamp when record was created

### `screenshots` table
- `id`: Primary key
- `scrape_date`: Date when scraping occurred
- `scrape_timestamp`: Full timestamp of scrape
- `city`: City name
- `pickup_date`: Pickup date and time
- `return_date`: Return date and time
- `screenshot_path`: Path to screenshot file
- `created_at`: Timestamp when record was created

## Querying the Database

You can query the Supabase database using any PostgreSQL client or the Supabase dashboard.

Example queries:

```sql
-- Get all vehicles scraped today
SELECT * FROM vehicles WHERE DATE(scrape_datetime) = CURRENT_DATE;

-- Get vehicles for a specific city and date
SELECT * FROM vehicles 
WHERE city = 'Sydney' AND DATE(scrape_datetime) = '2024-01-15';

-- Get all screenshots for a city
SELECT * FROM screenshots WHERE city = 'Melbourne';

-- Count vehicles by city
SELECT city, COUNT(*) as count 
FROM vehicles 
GROUP BY city;

-- Get vehicles with screenshots
SELECT * FROM vehicles 
WHERE screenshot_path IS NOT NULL 
AND screenshot_path != '';
```

## Project Structure

```
drivenow-scraper/
├── main.py              # Main script to run scraper
├── scraper.py           # Core scraping logic
├── database.py          # Database operations
├── config.yaml          # Configuration file
├── requirements.txt     # Python dependencies
├── README.md           # This file
├── .env                # Environment variables (not in git)
├── .env.example        # Environment variables template
├── .github/
│   └── workflows/
│       └── scrape.yml  # GitHub Actions workflow
├── screenshots/        # Temporary screenshot directory (local only)
└── *.log               # Log files
```

## GitHub Actions Setup

The scraper is configured to run automatically via GitHub Actions.

### Automatic Daily Run

The workflow runs daily at 10:00 AM UTC (configured in `.github/workflows/scrape.yml`).

### Manual Trigger

You can manually trigger the scraper from GitHub Actions:

1. Go to your repository on GitHub
2. Click on "Actions" tab
3. Select "Scrape DriveNow Data" workflow
4. Click "Run workflow"
5. Optionally specify a date to scrape (YYYY-MM-DD format)
6. Click "Run workflow" button

### Required GitHub Secrets

Add these secrets to your GitHub repository (Settings → Secrets and variables → Actions):

- `SUPABASE_DB_HOST`: Your Supabase database host
- `SUPABASE_DB_PORT`: Database port (usually 5432)
- `SUPABASE_DB_NAME`: Database name (usually "postgres")
- `SUPABASE_DB_USER`: Database user (usually "postgres")
- `SUPABASE_DB_PASSWORD`: Your Supabase database password
- `CLOUDFLARE_ACCOUNT_ID`: Your Cloudflare account ID
- `CLOUDFLARE_R2_ACCESS_KEY_ID`: R2 access key ID
- `CLOUDFLARE_R2_SECRET_ACCESS_KEY`: R2 secret access key
- `CLOUDFLARE_R2_BUCKET_NAME`: Your R2 bucket name
- `CLOUDFLARE_R2_PUBLIC_URL`: (Optional) Public URL for accessing screenshots

### Local Development

For local development, create a `.env` file with the same variables (see `.env.example`).

## Troubleshooting

### Playwright Installation Issues
- If Playwright browsers aren't installed, run: `playwright install chromium`
- Ensure you have sufficient disk space (browsers are ~200MB)

### Rate Limiting and Blocking
- If you're getting blocked, increase delays in `config.yaml`:
  - `delay_between_requests`: Increase to 3-5 seconds
  - `delay_between_vehicles`: Increase to 2-3 seconds
  - `delay_between_cities`: Increase to 5-10 seconds
- The scraper includes random delays to avoid detection patterns
- For large-scale scraping (50+ cities), consider running during off-peak hours

### Website Structure Changes
- If scraping fails, the website structure may have changed
- Check `scraper.log` for error messages
- You may need to update CSS selectors in `scraper.py` for "See Details" buttons
- Try running with `headless: false` in `config.yaml` to see what's happening

### No Vehicles Found
- The website may require different selectors
- Check if the website has changed its HTML structure
- Verify the URL pattern is still correct
- Check if the website requires cookies or has anti-bot protection

### "See Details" Button Not Found
- The button text or selector may have changed
- Check `scraper.log` to see which selectors are being tried
- You may need to update the `detail_selectors` list in `_get_vehicle_listings()` method

## Future Enhancements

- Web application for querying historical data
- Support for more cities
- Email notifications on scraping completion
- Data export functionality (CSV, JSON)
- Price change alerts
- API endpoints for data access

## Notes

- **Respect Website Terms**: Ensure your scraping activities comply with DriveNow's terms of service
- **Rate Limiting**: The scraper includes delays between requests to be respectful
- **Data Accuracy**: Vehicle data depends on the website's current structure and may need periodic updates

## License

Apache License 2.0

