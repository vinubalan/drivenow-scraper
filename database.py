"""
Database module for storing scraped vehicle data using Supabase (PostgreSQL).
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import List, Dict, Optional
from dotenv import load_dotenv
import pytz

# Load environment variables
load_dotenv()

# AEST timezone (handles both AEST UTC+10 and AEDT UTC+11 automatically)
AEST = pytz.timezone('Australia/Sydney')


def get_aest_now():
    """Get current datetime in AEST timezone."""
    return datetime.now(AEST)


class Database:
    """Handles database operations for vehicle data using Supabase PostgreSQL."""
    
    def __init__(self):
        """
        Initialize database connection to Supabase.
        """
        # Get Supabase connection details from environment variables
        self.db_host = os.getenv('SUPABASE_DB_HOST')
        self.db_port = os.getenv('SUPABASE_DB_PORT', '5432')
        self.db_name = os.getenv('SUPABASE_DB_NAME')
        self.db_user = os.getenv('SUPABASE_DB_USER')
        self.db_password = os.getenv('SUPABASE_DB_PASSWORD')
        
        if not all([self.db_host, self.db_name, self.db_user, self.db_password]):
            raise ValueError(
                "Missing Supabase database credentials. "
                "Please set SUPABASE_DB_HOST, SUPABASE_DB_NAME, SUPABASE_DB_USER, and SUPABASE_DB_PASSWORD in .env"
            )
        
        self.conn = None
        self._connect()
        self._create_tables()
    
    def _connect(self):
        """Establish connection to PostgreSQL database."""
        try:
            self.conn = psycopg2.connect(
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                user=self.db_user,
                password=self.db_password,
                connect_timeout=10
            )
            self.conn.autocommit = False
            
            # Set session timezone to AEST so TIMESTAMPTZ values are displayed in AEST
            cursor = self.conn.cursor()
            cursor.execute("SET timezone = 'Australia/Sydney'")
            cursor.close()
            self.conn.commit()
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Supabase database: {str(e)}")
    
    def _create_tables(self):
        """Create necessary database tables if they don't exist."""
        cursor = self.conn.cursor()
        
        try:
            # Vehicles table
            # Use TIMESTAMPTZ (TIMESTAMP WITH TIME ZONE) to preserve timezone information
            # All timestamps are stored in AEST timezone
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vehicles (
                    id SERIAL PRIMARY KEY,
                    scrape_datetime TIMESTAMPTZ NOT NULL,
                    city VARCHAR(255) NOT NULL,
                    pickup_date TIMESTAMPTZ NOT NULL,
                    return_date TIMESTAMPTZ NOT NULL,
                    vehicle_name TEXT,
                    vehicle_type TEXT,
                    seats TEXT,
                    doors TEXT,
                    transmission TEXT,
                    excess TEXT,
                    fuel_type TEXT,
                    logo_url TEXT,
                    price_per_day TEXT,
                    total_price TEXT,
                    currency VARCHAR(10) DEFAULT 'AUD',
                    detail_url TEXT,
                    screenshot_path TEXT,
                    depot_code VARCHAR(50),
                    supplier_code VARCHAR(50),
                    city_latitude NUMERIC(10, 8),
                    city_longitude NUMERIC(11, 8)
                )
            """)
            
            # Drop created_at column if it exists (redundant - scrape_datetime serves the same purpose)
            try:
                cursor.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='vehicles' AND column_name='created_at'
                """)
                if cursor.fetchone():
                    cursor.execute("ALTER TABLE vehicles DROP COLUMN created_at")
            except Exception as e:
                # Ignore errors (column might not exist or other issues)
                pass
            
            # Migrate existing TIMESTAMP columns to TIMESTAMPTZ if they exist
            # This ensures timezone information is preserved
            # Assumes existing TIMESTAMP data is stored in UTC (common for PostgreSQL)
            timestamp_columns = ['scrape_datetime', 'pickup_date', 'return_date']
            for column_name in timestamp_columns:
                try:
                    # Check current data type
                    cursor.execute("""
                        SELECT data_type 
                        FROM information_schema.columns 
                        WHERE table_name='vehicles' AND column_name=%s
                    """, (column_name,))
                    result = cursor.fetchone()
                    if result and result[0] == 'timestamp without time zone':
                        # Convert to TIMESTAMPTZ
                        # Treat existing timestamp as UTC (preserves the actual moment in time)
                        # TIMESTAMPTZ stores internally as UTC, so this conversion preserves the moment
                        cursor.execute(f"""
                            ALTER TABLE vehicles 
                            ALTER COLUMN {column_name} TYPE TIMESTAMPTZ 
                            USING {column_name} AT TIME ZONE 'UTC'
                        """)
                except Exception as e:
                    # Ignore errors (column might not exist or already converted)
                    pass
            
            # Create indexes for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_vehicles_scrape_datetime 
                ON vehicles(scrape_datetime)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_vehicles_city 
                ON vehicles(city)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_vehicles_pickup_date 
                ON vehicles(pickup_date)
            """)
            # Add depot_code and supplier_code columns if they don't exist (migration for existing databases)
            depot_code_columns = [
                ('depot_code', 'VARCHAR(50)'),
                ('supplier_code', 'VARCHAR(50)'),
            ]
            
            for column_name, column_type in depot_code_columns:
                try:
                    # Check if column exists
                    cursor.execute("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name='vehicles' AND column_name=%s
                    """, (column_name,))
                    if not cursor.fetchone():
                        # Column doesn't exist, add it
                        cursor.execute(f"""
                            ALTER TABLE vehicles 
                            ADD COLUMN {column_name} {column_type}
                        """)
                except Exception as e:
                    # Ignore errors (column might already exist or other issues)
                    pass
            
            # Remove old depot info columns if they exist (cleanup migration)
            old_depot_columns = [
                'depot_name',
                'depot_address',
                'depot_city',
                'depot_postcode',
                'depot_phone',
            ]
            
            for column_name in old_depot_columns:
                try:
                    # Check if column exists
                    cursor.execute("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name='vehicles' AND column_name=%s
                    """, (column_name,))
                    if cursor.fetchone():
                        # Column exists, drop it
                        cursor.execute(f"""
                            ALTER TABLE vehicles 
                            DROP COLUMN {column_name}
                        """)
                except Exception as e:
                    # Ignore errors (column might not exist or other issues)
                    pass
            
            # Drop screenshots table if it exists (no longer needed - screenshots stored in vehicles table)
            try:
                cursor.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_name='screenshots'
                """)
                if cursor.fetchone():
                    # Table exists, drop it
                    cursor.execute("DROP TABLE screenshots CASCADE")
            except Exception as e:
                # Ignore errors (table might not exist or other issues)
                pass
            
            # Add city location columns if they don't exist (migration for existing databases)
            city_location_columns = [
                ('city_latitude', 'NUMERIC(10, 8)'),
                ('city_longitude', 'NUMERIC(11, 8)'),
            ]
            
            for column_name, column_type in city_location_columns:
                try:
                    # Check if column exists
                    cursor.execute("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name='vehicles' AND column_name=%s
                    """, (column_name,))
                    if not cursor.fetchone():
                        # Column doesn't exist, add it
                        cursor.execute(f"""
                            ALTER TABLE vehicles 
                            ADD COLUMN {column_name} {column_type}
                        """)
                except Exception as e:
                    # Ignore errors (column might already exist or other issues)
                    pass
            
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to create tables: {str(e)}")
        finally:
            cursor.close()
    
    def insert_vehicle(self, vehicle_data: Dict) -> int:
        """
        Insert a vehicle record into the database.
        
        Args:
            vehicle_data: Dictionary containing vehicle information
            
        Returns:
            ID of the inserted record
        """
        cursor = self.conn.cursor()
        
        try:
            # Parse datetime strings - ensure they're timezone-aware (AEST)
            # scrape_datetime comes from get_aest_now() which is already AEST-aware
            scrape_dt_str = vehicle_data.get('scrape_datetime')
            if scrape_dt_str:
                scrape_dt = datetime.fromisoformat(scrape_dt_str.replace('Z', '+00:00'))
                # Ensure it's AEST-aware (if not already)
                if scrape_dt.tzinfo is None:
                    scrape_dt = AEST.localize(scrape_dt)
                elif scrape_dt.tzinfo != AEST:
                    scrape_dt = scrape_dt.astimezone(AEST)
            else:
                scrape_dt = get_aest_now()
            
            # pickup_date and return_date should also be AEST-aware
            pickup_dt_str = vehicle_data.get('pickup_date')
            if pickup_dt_str:
                pickup_dt = datetime.fromisoformat(pickup_dt_str.replace('Z', '+00:00'))
                if pickup_dt.tzinfo is None:
                    pickup_dt = AEST.localize(pickup_dt)
                elif pickup_dt.tzinfo != AEST:
                    pickup_dt = pickup_dt.astimezone(AEST)
            else:
                raise ValueError("pickup_date is required")
            
            return_dt_str = vehicle_data.get('return_date')
            if return_dt_str:
                return_dt = datetime.fromisoformat(return_dt_str.replace('Z', '+00:00'))
                if return_dt.tzinfo is None:
                    return_dt = AEST.localize(return_dt)
                elif return_dt.tzinfo != AEST:
                    return_dt = return_dt.astimezone(AEST)
            else:
                raise ValueError("return_date is required")
            
            cursor.execute("""
                INSERT INTO vehicles (
                    scrape_datetime, city, pickup_date, return_date,
                    vehicle_name, vehicle_type,
                    seats, doors, transmission, excess,
                    fuel_type, logo_url,
                    price_per_day, total_price, currency,
                    detail_url, screenshot_path,
                    depot_code, supplier_code,
                    city_latitude, city_longitude
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                scrape_dt,
                vehicle_data.get('city'),
                pickup_dt,
                return_dt,
                vehicle_data.get('vehicle_name'),
                vehicle_data.get('vehicle_type'),
                vehicle_data.get('seats'),
                vehicle_data.get('doors'),
                vehicle_data.get('transmission'),
                vehicle_data.get('excess'),
                vehicle_data.get('fuel_type'),
                vehicle_data.get('logo_url'),
                vehicle_data.get('price_per_day'),
                vehicle_data.get('total_price'),
                vehicle_data.get('currency', 'AUD'),
                vehicle_data.get('detail_url'),
                vehicle_data.get('screenshot_path'),
                vehicle_data.get('depot_code'),
                vehicle_data.get('supplier_code'),
                vehicle_data.get('city_latitude'),
                vehicle_data.get('city_longitude')
            ))
            
            vehicle_id = cursor.fetchone()[0]
            self.conn.commit()
            return vehicle_id
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to insert vehicle: {str(e)}")
        finally:
            cursor.close()
    
    def get_vehicles_by_date(self, date: str, city: Optional[str] = None) -> List[Dict]:
        """
        Get vehicles scraped on a specific date.
        
        Args:
            date: Scrape date (YYYY-MM-DD)
            city: Optional city filter
            
        Returns:
            List of vehicle records
        """
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            if city:
                cursor.execute("""
                    SELECT * FROM vehicles 
                    WHERE DATE(scrape_datetime) = %s AND city = %s
                    ORDER BY pickup_date, return_date
                """, (date, city))
            else:
                cursor.execute("""
                    SELECT * FROM vehicles 
                    WHERE DATE(scrape_datetime) = %s
                    ORDER BY city, pickup_date, return_date
                """, (date,))
            
            results = cursor.fetchall()
            # Convert RealDictRow to regular dict
            return [dict(row) for row in results]
        finally:
            cursor.close()
    
    def get_vehicles_without_screenshots(self) -> List[Dict]:
        """
        Get all vehicles that don't have screenshots yet.
        
        Returns:
            List of vehicle records with detail_url
        """
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            cursor.execute("""
                SELECT * FROM vehicles 
                WHERE (screenshot_path IS NULL OR screenshot_path = '')
                AND detail_url IS NOT NULL
                AND detail_url != ''
                ORDER BY scrape_datetime, city, pickup_date
            """)
            
            results = cursor.fetchall()
            return [dict(row) for row in results]
        finally:
            cursor.close()
    
    def update_vehicle_screenshot(self, vehicle_id: int, screenshot_path: str):
        """
        Update a vehicle record with screenshot path.
        
        Args:
            vehicle_id: ID of the vehicle record
            screenshot_path: Path to the screenshot file
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                UPDATE vehicles 
                SET screenshot_path = %s 
                WHERE id = %s
            """, (screenshot_path, vehicle_id))
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to update vehicle screenshot: {str(e)}")
        finally:
            cursor.close()
    
    def update_screenshot_path_for_combination(self, scrape_datetime: str, city: str,
                                               pickup_date: str, return_date: str,
                                               old_path: str, new_path: str):
        """
        Update screenshot path for all vehicles in a city-date combination.
        Used when compression converts PNG to JPEG.
        
        Args:
            scrape_datetime: Scrape datetime (ISO format)
            city: City name
            pickup_date: Pickup date (ISO format)
            return_date: Return date (ISO format)
            old_path: Old screenshot path (to match)
            new_path: New screenshot path (to set)
            
        Returns:
            Number of records updated
        """
        cursor = self.conn.cursor()
        try:
            # Parse datetime strings to TIMESTAMP
            scrape_dt = datetime.fromisoformat(scrape_datetime.replace('Z', '+00:00'))
            pickup_dt = datetime.fromisoformat(pickup_date.replace('Z', '+00:00'))
            return_dt = datetime.fromisoformat(return_date.replace('Z', '+00:00'))
            
            cursor.execute("""
                UPDATE vehicles 
                SET screenshot_path = %s 
                WHERE DATE(scrape_datetime) = DATE(%s)
                AND city = %s 
                AND pickup_date = %s 
                AND return_date = %s
                AND screenshot_path = %s
            """, (new_path, scrape_dt, city, pickup_dt, return_dt, old_path))
            updated_count = cursor.rowcount
            self.conn.commit()
            return updated_count
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to update screenshot paths: {str(e)}")
        finally:
            cursor.close()
    
    def delete_vehicles_for_pickup_date(self, pickup_date: str, cloud_storage=None):
        """
        Delete all vehicles for a specific pickup_date (across all cities and return dates).
        Also deletes associated screenshots from R2 if cloud_storage is provided.
        This is faster than deleting per combination - single bulk delete operation.
        
        Args:
            pickup_date: Pickup date (ISO format, e.g., '2025-11-21T10:00:00+10:00' or '2025-11-21')
            cloud_storage: Optional CloudflareR2Storage instance for deleting screenshots from R2
            
        Returns:
            Tuple of (number of records deleted, number of screenshots deleted from R2)
        """
        cursor = self.conn.cursor()
        screenshots_deleted = 0
        
        try:
            # Parse pickup_date - handle both datetime and date-only formats
            try:
                pickup_dt = datetime.fromisoformat(pickup_date.replace('Z', '+00:00'))
            except:
                # If parsing fails, try date-only format
                pickup_dt = datetime.strptime(pickup_date.split('T')[0], '%Y-%m-%d')
            
            # First, get all unique screenshot paths for this pickup_date before deleting
            screenshot_paths_to_delete = set()
            if cloud_storage:
                cursor.execute("""
                    SELECT DISTINCT screenshot_path 
                    FROM vehicles 
                    WHERE DATE(pickup_date) = DATE(%s)
                    AND screenshot_path IS NOT NULL
                    AND screenshot_path != ''
                """, (pickup_dt,))
                screenshot_paths = cursor.fetchall()
                screenshot_paths_to_delete = {row[0] for row in screenshot_paths if row[0]}
            
            # Delete screenshots from R2 if cloud storage is enabled
            if cloud_storage and screenshot_paths_to_delete:
                from urllib.parse import urlparse
                import os
                
                for screenshot_path in screenshot_paths_to_delete:
                    try:
                        # Extract R2 file path from URL or use path directly
                        if screenshot_path.startswith('http'):
                            # Extract path from URL (e.g., https://public-url.com/screenshots/file.jpg -> screenshots/file.jpg)
                            parsed_url = urlparse(screenshot_path)
                            # Remove leading slash
                            r2_path = parsed_url.path.lstrip('/')
                        else:
                            # Local path - use as is (relative to bucket root)
                            r2_path = screenshot_path.lstrip('/')
                        
                        # Delete from R2
                        if cloud_storage.delete_file(r2_path):
                            screenshots_deleted += 1
                    except Exception as e:
                        # Log error but continue - don't fail the whole operation
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"Failed to delete screenshot from R2: {screenshot_path} - {str(e)}")
            
            # Delete all records for this pickup_date (date part only, ignoring time)
            cursor.execute("""
                DELETE FROM vehicles 
                WHERE DATE(pickup_date) = DATE(%s)
            """, (pickup_dt,))
            deleted_count = cursor.rowcount
            self.conn.commit()
            return deleted_count, screenshots_deleted
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to delete vehicles for pickup_date: {str(e)}")
        finally:
            cursor.close()
    
    def delete_vehicles_for_combination(self, scrape_datetime: str, city: str, 
                                       pickup_date: str, return_date: str):
        """
        Delete all vehicles for a specific city-date combination.
        This prevents duplicate records when re-scraping.
        NOTE: This method is kept for backward compatibility but is no longer used
        since we now use upfront deletion via delete_vehicles_for_pickup_date.
        
        Args:
            scrape_datetime: Scrape datetime (ISO format)
            city: City name
            pickup_date: Pickup date (ISO format)
            return_date: Return date (ISO format)
            
        Returns:
            Number of records deleted
        """
        cursor = self.conn.cursor()
        try:
            # Parse datetime strings to TIMESTAMP
            scrape_dt = datetime.fromisoformat(scrape_datetime.replace('Z', '+00:00'))
            pickup_dt = datetime.fromisoformat(pickup_date.replace('Z', '+00:00'))
            return_dt = datetime.fromisoformat(return_date.replace('Z', '+00:00'))
            
            cursor.execute("""
                DELETE FROM vehicles 
                WHERE DATE(scrape_datetime) = DATE(%s)
                AND city = %s 
                AND pickup_date = %s 
                AND return_date = %s
            """, (scrape_dt, city, pickup_dt, return_dt))
            deleted_count = cursor.rowcount
            self.conn.commit()
            return deleted_count
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to delete vehicles: {str(e)}")
        finally:
            cursor.close()
    
    def clear_all_data(self):
        """
        Clear all data from vehicles table.
        WARNING: This will delete ALL records!
        
        Returns:
            Number of vehicles deleted
        """
        cursor = self.conn.cursor()
        try:
            # Get count before deletion
            cursor.execute("SELECT COUNT(*) FROM vehicles")
            vehicle_count = cursor.fetchone()[0]
            
            # Clear vehicles table
            cursor.execute("TRUNCATE TABLE vehicles RESTART IDENTITY CASCADE")
            
            self.conn.commit()
            return vehicle_count
        except Exception as e:
            self.conn.rollback()
            raise Exception(f"Failed to clear database: {str(e)}")
        finally:
            cursor.close()
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
