.PHONY: scrape all clean help check install test

# Default target
help:
	@echo "DriveNow Scraper - Makefile Commands"
	@echo ""
	@echo "Available targets:"
	@echo "  make install   - Install dependencies and Playwright browsers"
	@echo "  make scrape    - Run scraper: Collect vehicle data and capture results page screenshots"
	@echo "  make test      - Test workflow locally (auto mode)"
	@echo "  make check     - Check database and screenshot status"
	@echo "  make clean     - Clean local screenshots and logs"
	@echo "  make help      - Show this help message"
	@echo ""

# Install dependencies
install:
	@echo "=========================================="
	@echo "Installing Dependencies"
	@echo "=========================================="
	pip3 install -r requirements.txt
	playwright install chromium
	@echo "✓ Installation complete"
	@echo "=========================================="

# Run scraper: Collect vehicle data and capture screenshots
scrape:
	@echo "=========================================="
	@echo "Running Scraper: Data Collection + Screenshots"
	@echo "=========================================="
	python3 scrape.py

# Alias for scrape
all: scrape

# Test workflow locally (auto mode)
test:
	@echo "=========================================="
	@echo "Testing Workflow Locally (Auto Mode)"
	@echo "=========================================="
	@export CI='true' && python3 scrape.py

# Check status
check:
	@echo "=========================================="
	@echo "Checking Database and Screenshots"
	@echo "=========================================="
	@python3 -c "from database import Database; \
		from datetime import datetime; \
		import pytz; \
		aest = pytz.timezone('Australia/Sydney'); \
		today = datetime.now(aest).strftime('%Y-%m-%d'); \
		db = Database(); \
		vehicles = db.get_vehicles_by_date(today); \
		print(f'Total vehicles in DB (today): {len(vehicles)}'); \
		with_urls = sum(1 for v in vehicles if v.get('detail_url')); \
		with_screenshots = sum(1 for v in vehicles if v.get('screenshot_path')); \
		print(f'Vehicles with detail URLs: {with_urls}'); \
		print(f'Vehicles with screenshots: {with_screenshots}'); \
		db.close()"
	@echo ""
	@echo "Local screenshots:"
	@find screenshots -name "*.jpg" -o -name "*.png" 2>/dev/null | wc -l | xargs echo "  Count:"
	@echo "=========================================="

# Clean local files (does not touch database or R2)
clean:
	@echo "=========================================="
	@echo "Cleaning local screenshots and logs"
	@echo "=========================================="
	@rm -rf screenshots/*.png screenshots/*.jpg 2>/dev/null || true
	@rm -f *.log scraper.log 2>/dev/null || true
	@rm -rf __pycache__ *.pyc 2>/dev/null || true
	@echo "✓ Cleanup complete"
	@echo "=========================================="

