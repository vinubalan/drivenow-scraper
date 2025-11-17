#!/usr/bin/env python3
"""
Phase 2: Capture screenshots for all vehicles that have detail URLs.
Run this after Phase 1 to capture screenshots in parallel.
"""
import sys
import logging
from pathlib import Path
from database import Database
from scraper import DriveNowScraper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('phase2.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def main():
    """Run Phase 2: Capture screenshots for all vehicles."""
    try:
        # Load configuration
        config_path = "config.yaml"
        if not Path(config_path).exists():
            logger.error(f"Configuration file not found: {config_path}")
            sys.exit(1)
        
        # Initialize database
        logger.info("Initializing database...")
        db = Database()
        
        # Check how many vehicles need screenshots
        vehicles_needing_screenshots = db.get_vehicles_without_screenshots()
        total = len(vehicles_needing_screenshots)
        with_urls = sum(1 for v in vehicles_needing_screenshots if v.get('detail_url'))
        
        logger.info("="*60)
        logger.info("PHASE 2: Screenshot Capture")
        logger.info("="*60)
        logger.info(f"Vehicles needing screenshots: {total}")
        logger.info(f"Vehicles with detail URLs: {with_urls}")
        logger.info("="*60)
        
        if total == 0:
            logger.info("No vehicles need screenshots. Phase 2 skipped.")
            return
        
        # Initialize scraper
        logger.info("Initializing scraper...")
        scraper = DriveNowScraper(config_path)
        
        try:
            # Run Phase 2 only
            logger.info("="*60)
            logger.info("PHASE 2: Capturing screenshots for all vehicles...")
            logger.info("="*60)
            
            # Run screenshot capture in separate thread with event loop
            import threading
            import asyncio
            
            def run_screenshots():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    new_loop.run_until_complete(scraper.capture_all_screenshots_async(db))
                finally:
                    new_loop.close()
            
            phase2_thread = threading.Thread(target=run_screenshots, daemon=False)
            phase2_thread.start()
            phase2_thread.join()
            
            # Close async browser after Phase 2 - with timeout
            try:
                if scraper.async_contexts or scraper.async_browser:
                    def close_phase2():
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
                            new_loop.close()
                    close_thread = threading.Thread(target=close_phase2, daemon=True)
                    close_thread.start()
                    close_thread.join(timeout=6.0)  # Max 6 seconds
            except:
                pass
            
            # Get summary from database
            from datetime import datetime
            today = datetime.now().strftime('%Y-%m-%d')
            vehicles_with_screenshots = db.get_vehicles_by_date(today)
            vehicles_with_screenshots = [v for v in vehicles_with_screenshots if v.get('screenshot_path')]
            
            logger.info("="*60)
            logger.info("PHASE 2 SUMMARY")
            logger.info("="*60)
            logger.info(f"Total vehicles with screenshots: {len(vehicles_with_screenshots)}")
            
            # Count by city
            from collections import Counter
            cities = Counter(v.get('city') for v in vehicles_with_screenshots)
            for city, count in cities.items():
                logger.info(f"  {city}: {count} screenshots")
            
            # Count screenshots on disk
            import os
            screenshot_count = len([f for f in os.listdir('screenshots') if f.endswith('.png')]) if os.path.exists('screenshots') else 0
            logger.info(f"Screenshots on disk: {screenshot_count}")
            logger.info("="*60)
            
        except Exception as e:
            logger.error(f"Error during Phase 2: {str(e)}", exc_info=True)
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
            
            logger.info("Phase 2 completed and all resources cleaned up")
    
    except KeyboardInterrupt:
        logger.info("Phase 2 interrupted by user")
        try:
            if 'scraper' in locals():
                scraper.close()
            if 'db' in locals():
                db.close()
        except:
            pass
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error during Phase 2: {str(e)}", exc_info=True)
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

