.PHONY: phase1 all clean help check

# Default target
help:
	@echo "DriveNow Scraper - Makefile Commands"
	@echo ""
	@echo "Available targets:"
	@echo "  make phase1    - Run scraper: Collect vehicle data and capture results page screenshots"
	@echo "  make all       - Alias for phase1"
	@echo "  make check     - Check database and screenshot status"
	@echo "  make clean     - Clean database, screenshots, and logs"
	@echo "  make help      - Show this help message"
	@echo ""

# Phase 1: Collect vehicle data and capture screenshots
phase1:
	@echo "=========================================="
	@echo "Running Scraper: Data Collection + Screenshots"
	@echo "=========================================="
	python3 phase1_collect.py

# Alias for phase1
all: phase1
	@echo "=========================================="
	@echo "Scraping completed!"
	@echo "=========================================="

# Check status
check:
	@echo "=========================================="
	@echo "Checking Database and Screenshots"
	@echo "=========================================="
	@python3 -c "from database import Database; \
		from datetime import datetime; \
		today = datetime.now().strftime('%Y-%m-%d'); \
		db = Database(); \
		vehicles = db.get_vehicles_by_date(today); \
		print(f'Total vehicles in DB (today): {len(vehicles)}'); \
		with_urls = sum(1 for v in vehicles if v.get('detail_url')); \
		with_screenshots = sum(1 for v in vehicles if v.get('screenshot_path')); \
		print(f'Vehicles with detail URLs: {with_urls}'); \
		print(f'Vehicles with screenshots: {with_screenshots}'); \
		needing_screenshots = db.get_vehicles_without_screenshots(); \
		print(f'Vehicles needing screenshots: {len(needing_screenshots)}'); \
		db.close()"
	@echo ""
	@echo "Screenshots on disk:"
	@find screenshots -name "*.png" 2>/dev/null | wc -l | xargs echo "  Count:"
	@echo "=========================================="

# Clean everything
clean:
	@echo "=========================================="
	@echo "Cleaning database, screenshots, and logs"
	@echo "=========================================="
	@rm -f drivenow_data.db *.db *.sqlite* 2>/dev/null || true
	@rm -rf screenshots/*.png screenshots/*.jpg 2>/dev/null || true
	@rm -f *.log phase1.log phase2.log scraper.log 2>/dev/null || true
	@rm -rf __pycache__ *.pyc 2>/dev/null || true
	@echo "✓ Cleanup complete"
	@echo "=========================================="

