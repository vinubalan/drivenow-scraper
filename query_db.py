#!/usr/bin/env python3
"""
Utility script to query the scraped data from the database.
"""
import sys
import argparse
from datetime import datetime
from database import Database
import json


def format_vehicle(vehicle):
    """Format vehicle data for display."""
    print(f"\n{'='*60}")
    print(f"Vehicle: {vehicle.get('vehicle_name', 'N/A')}")
    print(f"Category: {vehicle.get('vehicle_category', 'N/A')}")
    print(f"City: {vehicle.get('city')}")
    print(f"Pickup: {vehicle.get('pickup_date')}")
    print(f"Return: {vehicle.get('return_date')}")
    print(f"Price: ${vehicle.get('total_price', 'N/A')} {vehicle.get('currency', 'AUD')}")
    print(f"Scraped: {vehicle.get('scrape_date')} at {vehicle.get('scrape_timestamp')}")
    if vehicle.get('screenshot_path'):
        print(f"Screenshot: {vehicle.get('screenshot_path')}")


def query_by_date(db, date, city=None):
    """Query vehicles by scrape date."""
    vehicles = db.get_vehicles_by_date(date, city)
    
    if not vehicles:
        print(f"No vehicles found for date: {date}" + (f" in {city}" if city else ""))
        return
    
    print(f"\nFound {len(vehicles)} vehicles for date: {date}" + (f" in {city}" if city else ""))
    
    for vehicle in vehicles:
        format_vehicle(vehicle)


def list_all_dates(db):
    """List all unique scrape dates in the database."""
    cursor = db.conn.cursor()
    cursor.execute("SELECT DISTINCT scrape_date FROM vehicles ORDER BY scrape_date DESC")
    dates = [row[0] for row in cursor.fetchall()]
    
    if not dates:
        print("No data found in database.")
        return
    
    print("\nAvailable scrape dates:")
    for date in dates:
        cursor.execute("SELECT COUNT(*) FROM vehicles WHERE scrape_date = ?", (date,))
        count = cursor.fetchone()[0]
        print(f"  {date}: {count} vehicles")


def list_cities(db):
    """List all cities in the database."""
    cursor = db.conn.cursor()
    cursor.execute("SELECT DISTINCT city FROM vehicles ORDER BY city")
    cities = [row[0] for row in cursor.fetchall()]
    
    if not cities:
        print("No cities found in database.")
        return
    
    print("\nAvailable cities:")
    for city in cities:
        cursor.execute("SELECT COUNT(*) FROM vehicles WHERE city = ?", (city,))
        count = cursor.fetchone()[0]
        print(f"  {city}: {count} vehicles")


def stats(db):
    """Show database statistics."""
    cursor = db.conn.cursor()
    
    # Total vehicles
    cursor.execute("SELECT COUNT(*) FROM vehicles")
    total_vehicles = cursor.fetchone()[0]
    
    # Total screenshots
    cursor.execute("SELECT COUNT(*) FROM screenshots")
    total_screenshots = cursor.fetchone()[0]
    
    # Cities
    cursor.execute("SELECT COUNT(DISTINCT city) FROM vehicles")
    num_cities = cursor.fetchone()[0]
    
    # Dates
    cursor.execute("SELECT COUNT(DISTINCT scrape_date) FROM vehicles")
    num_dates = cursor.fetchone()[0]
    
    # Average price
    cursor.execute("SELECT AVG(total_price) FROM vehicles WHERE total_price IS NOT NULL")
    avg_price = cursor.fetchone()[0]
    
    print("\n" + "="*60)
    print("DATABASE STATISTICS")
    print("="*60)
    print(f"Total vehicles: {total_vehicles}")
    print(f"Total screenshots: {total_screenshots}")
    print(f"Number of cities: {num_cities}")
    print(f"Number of scrape dates: {num_dates}")
    if avg_price:
        print(f"Average price: ${avg_price:.2f} AUD")
    print("="*60)


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Query DriveNow scraper database')
    parser.add_argument('--date', type=str, help='Query by scrape date (YYYY-MM-DD)')
    parser.add_argument('--city', type=str, help='Filter by city name')
    parser.add_argument('--list-dates', action='store_true', help='List all available dates')
    parser.add_argument('--list-cities', action='store_true', help='List all available cities')
    parser.add_argument('--stats', action='store_true', help='Show database statistics')
    parser.add_argument('--db', type=str, default='drivenow_data.db', help='Database file path')
    
    args = parser.parse_args()
    
    # Initialize database
    db = Database(args.db)
    
    try:
        if args.stats:
            stats(db)
        elif args.list_dates:
            list_dates(db)
        elif args.list_cities:
            list_cities(db)
        elif args.date:
            query_by_date(db, args.date, args.city)
        else:
            parser.print_help()
            print("\nExample usage:")
            print("  python query_db.py --stats")
            print("  python query_db.py --list-dates")
            print("  python query_db.py --date 2024-01-15")
            print("  python query_db.py --date 2024-01-15 --city Sydney")
    finally:
        db.close()


if __name__ == "__main__":
    main()

