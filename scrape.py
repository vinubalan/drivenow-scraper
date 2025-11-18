#!/usr/bin/env python3
"""
Collect vehicle data and capture results page screenshots.
This single phase collects all vehicle data and takes one screenshot per city-date combination.
"""
import sys
import logging
import time
from pathlib import Path
from database import Database
from scraper import DriveNowScraper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def main():
    """Run scraper: Collect vehicle data and capture results page screenshots."""
    # Start timing
    start_time = time.time()
    
    try:
        # Load configuration
        config_path = "config.yaml"
        if not Path(config_path).exists():
            logger.error(f"Configuration file not found: {config_path}")
            sys.exit(1)
        
        # Initialize database
        logger.info("Initializing database...")
        db = Database()
        
        # Initialize scraper
        logger.info("Initializing scraper...")
        scraper = DriveNowScraper(config_path)
        
        try:
            # Run collection (includes screenshots)
            logger.info("="*60)
            logger.info("Collecting vehicle data and capturing results page screenshots...")
            logger.info("="*60)
            logger.info(f"⏱️  Scraping started at {time.strftime('%H:%M:%S')}")
            
            # Run collection in separate thread with event loop
            import threading
            import asyncio
            
            def run_collection():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    new_loop.run_until_complete(scraper._collect_all_vehicles_parallel_async(db))
                finally:
                    # Wait for pending tasks and cancel them before closing
                    try:
                        # Give a moment for Playwright's internal cleanup
                        pending = asyncio.all_tasks(new_loop)
                        if pending:
                            for task in pending:
                                task.cancel()
                            # Wait briefly for cancellations
                            new_loop.run_until_complete(
                                asyncio.gather(*pending, return_exceptions=True)
                            )
                    except Exception:
                        pass  # Ignore errors during cleanup
                    finally:
                        new_loop.close()
            
            collection_thread = threading.Thread(target=run_collection, daemon=False)
            collection_thread.start()
            collection_thread.join()
            
            # Calculate and log total scraping duration
            end_time = time.time()
            duration = end_time - start_time
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            logger.info("="*60)
            logger.info(f"⏱️  TOTAL SCRAPING TIME: {minutes} minutes {seconds} seconds ({duration:.1f} seconds)")
            logger.info("="*60)
            
            # Close async browser after collection - with timeout
            try:
                if scraper.async_contexts or scraper.async_browser:
                    def close_browser():
                        new_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(new_loop)
                        try:
                            new_loop.run_until_complete(asyncio.wait_for(scraper._close_async(), timeout=5.0))
                        except (asyncio.TimeoutError, Exception):
                            # Force cleanup on timeout
                            scraper.async_contexts = []
                            scraper.async_browser = None
                            scraper.async_playwright = None
                        finally:
                            # Wait for pending tasks before closing
                            try:
                                pending = asyncio.all_tasks(new_loop)
                                if pending:
                                    for task in pending:
                                        task.cancel()
                                    new_loop.run_until_complete(
                                        asyncio.gather(*pending, return_exceptions=True)
                                    )
                            except Exception:
                                pass
                            finally:
                                new_loop.close()
                    close_thread = threading.Thread(target=close_browser, daemon=True)
                    close_thread.start()
                    close_thread.join(timeout=6.0)  # Max 6 seconds
            except:
                pass
            
            # Get summary from database
            from datetime import datetime
            today = datetime.now().strftime('%Y-%m-%d')
            vehicles = db.get_vehicles_by_date(today)
            total_vehicles = len(vehicles)
            
            logger.info("="*60)
            logger.info("COLLECTION SUMMARY")
            logger.info("="*60)
            logger.info(f"Total vehicles collected: {total_vehicles}")
            
            # Count by city
            from collections import Counter
            cities = Counter(v.get('city') for v in vehicles)
            for city, count in cities.items():
                logger.info(f"  {city}: {count} vehicles")
            
            vehicles_with_urls = sum(1 for v in vehicles if v.get('detail_url'))
            vehicles_with_screenshots = sum(1 for v in vehicles if v.get('screenshot_path'))
            logger.info(f"Vehicles with detail URLs: {vehicles_with_urls}/{total_vehicles}")
            logger.info(f"Vehicles with screenshots: {vehicles_with_screenshots}/{total_vehicles}")
            logger.info("="*60)
            
        except Exception as e:
            logger.error(f"Error during collection: {str(e)}", exc_info=True)
        finally:
            # Always cleanup
            logger.info("Cleaning up and closing all browsers...")
            try:
                scraper.close()
            except Exception as e:
                logger.warning(f"Error closing scraper: {str(e)}")
            
            try:
                db.close()
            except Exception as e:
                logger.warning(f"Error closing database: {str(e)}")
            
            logger.info("Collection completed and all resources cleaned up")
    
    except KeyboardInterrupt:
        logger.info("Collection interrupted by user")
        try:
            if 'scraper' in locals():
                scraper.close()
            if 'db' in locals():
                db.close()
        except:
            pass
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error during collection: {str(e)}", exc_info=True)
        try:
            if 'scraper' in locals():
                scraper.close()
            if 'db' in locals():
                db.close()
        except:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()

