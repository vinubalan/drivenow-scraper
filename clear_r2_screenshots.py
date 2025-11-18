#!/usr/bin/env python3
"""
Script to clear all screenshots from Cloudflare R2 storage.
"""
import sys
import logging
from cloud_storage import CloudflareR2Storage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def clear_r2_screenshots():
    """Clear all screenshots from R2 storage."""
    try:
        r2_storage = CloudflareR2Storage()
        
        try:
            # List all files first to show what will be deleted
            logger.info("Listing all files in R2 bucket...")
            all_files = r2_storage.list_all_files()
            
            if not all_files:
                logger.info("No files found in R2 bucket.")
                return
            
            logger.info(f"Found {len(all_files)} files in R2 bucket")
            
            # Filter for screenshot files (jpg, jpeg, png)
            screenshot_files = [
                f for f in all_files 
                if f.lower().endswith(('.jpg', '.jpeg', '.png'))
            ]
            
            if not screenshot_files:
                logger.info("No screenshot files found in R2 bucket.")
                return
            
            logger.info(f"Found {len(screenshot_files)} screenshot files to delete")
            
            # Delete all screenshot files
            deleted_count = 0
            for file_path in screenshot_files:
                if r2_storage.delete_file(file_path):
                    deleted_count += 1
            
            logger.info("="*60)
            logger.info(f"Deleted {deleted_count} screenshot files from R2")
            logger.info("="*60)
            
        except Exception as e:
            logger.error(f"Error clearing R2 screenshots: {str(e)}")
            raise
            
    except Exception as e:
        logger.error(f"Failed to clear R2 screenshots: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    print("="*60)
    print("WARNING: This will delete ALL screenshot files from R2 storage!")
    print("="*60)
    response = input("Are you sure you want to continue? (yes/no): ")
    
    if response.lower() == 'yes':
        clear_r2_screenshots()
    else:
        print("Operation cancelled.")
        sys.exit(0)

