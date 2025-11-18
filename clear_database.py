#!/usr/bin/env python3
"""
Script to clear all data from database tables.
"""
import sys
import logging
from database import Database

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def clear_database():
    """Clear all data from vehicles table."""
    try:
        db = Database()
        
        try:
            # Clear all data
            vehicle_count = db.clear_all_data()
            
            logger.info(f"Deleted {vehicle_count} vehicles")
            logger.info("="*60)
            logger.info("Database cleared successfully!")
            logger.info("="*60)
            
        except Exception as e:
            logger.error(f"Error clearing database: {str(e)}")
            raise
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Failed to clear database: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    print("="*60)
    print("WARNING: This will delete ALL data from vehicles table!")
    print("="*60)
    response = input("Are you sure you want to continue? (yes/no): ")
    
    if response.lower() == 'yes':
        clear_database()
    else:
        print("Operation cancelled.")
        sys.exit(0)

