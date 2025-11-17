#!/usr/bin/env python3
"""Test script to check if page is loading fully."""
import asyncio
from playwright.async_api import async_playwright
from scraper import DriveNowScraper
from datetime import datetime, timedelta
import yaml

async def test_page_load():
    """Test if page loads fully and how many vehicles are found."""
    with open('config.yaml') as f:
        config = yaml.safe_load(f)
    
    # Get first city and date combination
    city = config['cities'][0]
    
    # Calculate dates manually
    from datetime import datetime, timedelta
    today = datetime.now().date()
    next_day = today + timedelta(days=1)
    pickup_date = datetime.combine(next_day, datetime.min.time().replace(hour=10, minute=0, second=0, microsecond=0))
    return_date = pickup_date + timedelta(days=1)
    
    # Build URL manually
    from urllib.parse import quote
    pickup_date_str = pickup_date.strftime("%Y-%m-%d")
    pickup_time_str = pickup_date.strftime("%H:%M")
    return_date_str = return_date.strftime("%Y-%m-%d")
    return_time_str = return_date.strftime("%H:%M")
    lat = city['latitude']
    lng = city['longitude']
    location = city['location_string']
    radius = city.get('radius', 3)
    location_encoded = quote(location, safe=',')
    results_base_url = config['scraper']['results_base_url']
    
    results_url = (
        f"{results_base_url}/"
        f"{pickup_date_str}/{pickup_time_str}/"
        f"{return_date_str}/{return_time_str}/"
        f"{lat},{lng},2/{lat},{lng},2/"
        f"{location_encoded}/{location_encoded}/"
        f"IN/30?radius={radius}&pickupCountry=AU&returnCountry=AU&bookingEngine=ube&affiliateCode=drivenow"
    )
    print(f"Testing URL: {results_url}")
    print(f"City: {city['name']}")
    print(f"Pickup: {pickup_date}, Return: {return_date}")
    print("-" * 60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()
        
        # Navigate
        print("Navigating to page...")
        await page.goto(results_url, wait_until="domcontentloaded", timeout=20000)
        
        # Wait progressively and check content
        print("\n--- Checking page load status ---")
        
        # Step 1: DOM loaded
        print("1. Waiting for DOM...")
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
        await asyncio.sleep(1)
        body_text = await page.evaluate("() => document.body.innerText")
        print(f"   Body text length: {len(body_text)} chars")
        
        # Step 2: Network idle
        print("2. Waiting for network idle...")
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
            print("   Network idle reached")
        except:
            print("   Network idle timeout (continuing anyway)")
        
        await asyncio.sleep(2)
        body_text = await page.evaluate("() => document.body.innerText")
        print(f"   Body text length after networkidle: {len(body_text)} chars")
        
        # Step 3: Wait for specific selectors
        print("3. Waiting for vehicle elements...")
        vehicle_selectors = [
            "[class*='vehicle']",
            "[class*='car']",
            "button:has-text('See Details')",
            "a:has-text('See Details')",
        ]
        
        found_elements = []
        for selector in vehicle_selectors:
            try:
                await page.wait_for_selector(selector, timeout=10000, state="visible")
                elements = await page.query_selector_all(selector)
                if elements:
                    found_elements.append((selector, len(elements)))
                    print(f"   Found {len(elements)} elements with: {selector}")
            except:
                print(f"   No elements found with: {selector}")
        
        # Step 4: Additional wait and check
        print("4. Waiting additional 3 seconds for dynamic content...")
        await asyncio.sleep(3)
        
        # Check again
        print("\n--- Final check ---")
        body_text = await page.evaluate("() => document.body.innerText")
        print(f"Body text length: {len(body_text)} chars")
        
        # Try to find vehicles using similar logic
        print("\n--- Trying to extract vehicles ---")
        vehicles = []
        
        # Wait more
        await asyncio.sleep(3)
        
        # Try to find vehicle elements
        vehicle_selectors = [
            ".vehicle-card",
            ".car-card",
            ".vehicle-item",
            ".listing-item",
            "[class*='vehicle']",
            "[class*='car']",
            "[data-testid*='vehicle']",
            "[data-testid*='car']",
        ]
        
        vehicle_elements = []
        for selector in vehicle_selectors:
            try:
                elements = await page.query_selector_all(selector)
                if elements and len(elements) > 0:
                    vehicle_elements = elements
                    print(f"Found {len(elements)} vehicle elements using: {selector}")
                    break
            except:
                continue
        
        # Try to find "See Details" buttons
        detail_selectors = [
            "button:has-text('See Details')",
            "a:has-text('See Details')",
            "button:has-text('Details')",
            "a:has-text('Details')",
        ]
        
        detail_buttons = []
        for selector in detail_selectors:
            try:
                buttons = await page.query_selector_all(selector)
                if buttons:
                    detail_buttons = buttons
                    print(f"Found {len(buttons)} detail buttons using: {selector}")
                    break
            except:
                continue
        
        print(f"Total vehicle elements: {len(vehicle_elements)}")
        print(f"Total detail buttons: {len(detail_buttons)}")
        
        if vehicles:
            print("\nFirst few vehicles:")
            for i, v in enumerate(vehicles[:5]):
                print(f"  {i+1}. {v.get('vehicle_name', 'Unknown')} - {v.get('detail_url', 'No URL')[:80]}")
        else:
            print("\n⚠️  NO VEHICLES FOUND!")
            print("\nPage HTML snippet (first 2000 chars):")
            html = await page.content()
            print(html[:2000])
        
        # Take a screenshot for inspection
        await page.screenshot(path="test_page_load.png", full_page=True)
        print(f"\nScreenshot saved to: test_page_load.png")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_page_load())

