#!/usr/bin/env python3
"""
Main script to run the DriveNow scraper.
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
        logging.FileHandler('scraper.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def main():
    """Main function to run the scraper."""
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
            # Run scraper for all cities
            logger.info("Starting scrape for all cities...")
            results = scraper.scrape_all(db)
            
            # Print summary
            total_vehicles = sum(len(vehicles) for vehicles in results.values())
            logger.info("=" * 60)
            logger.info("SCRAPE SUMMARY")
            logger.info("=" * 60)
            for city, vehicles in results.items():
                logger.info(f"{city}: {len(vehicles)} vehicles scraped")
            logger.info(f"Total vehicles scraped: {total_vehicles}")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Error during scraping: {str(e)}", exc_info=True)
        finally:
            # Always cleanup - close all browsers
            logger.info("Cleaning up and closing all browsers...")
            try:
                scraper.close()
            except Exception as e:
                logger.warning(f"Error closing scraper: {str(e)}")
            
            try:
                db.close()
            except Exception as e:
                logger.warning(f"Error closing database: {str(e)}")
            
            logger.info("Scraping completed and all resources cleaned up")
    
    except KeyboardInterrupt:
        logger.info("Scraping interrupted by user")
        # Ensure browsers are closed on interrupt
        try:
            if 'scraper' in locals():
                scraper.close()
            if 'db' in locals():
                db.close()
        except:
            pass
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error during scraping: {str(e)}", exc_info=True)
        # Ensure browsers are closed on error
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

