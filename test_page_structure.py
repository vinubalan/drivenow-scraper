#!/usr/bin/env python3
"""Test script to understand page structure and find fastest way to capture vehicles."""
from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(viewport={'width': 1920, 'height': 1080})
    page = context.new_page()
    
    # Navigate to results
    url = "https://carhire.drivenow.com.au/drivenow/results/2025-11-18/10:00/2025-11-19/10:00/-33.86706149922719,151.2155219586914,2/-33.86706149922719,151.2155219586914,2/Sydney,%20New%20South%20Wales,%20Australia/Sydney,%20New%20South%20Wales,%20Australia/IN/30?radius=3&pickupCountry=AU&returnCountry=AU&bookingEngine=ube&affiliateCode=drivenow"
    
    print("Loading page...")
    page.goto(url, wait_until="domcontentloaded")
    time.sleep(3)
    
    # Find all "See Details" buttons
    buttons = page.query_selector_all("button:has-text('See Details'), a:has-text('See Details')")
    print(f"Found {len(buttons)} 'See Details' buttons")
    
    if buttons:
        print("\nClicking first button to see what happens...")
        url_before = page.url
        buttons[0].click()
        time.sleep(2)
        url_after = page.url
        
        print(f"URL before: {url_before}")
        print(f"URL after: {url_after}")
        print(f"Navigation occurred: {url_before != url_after}")
        
        # Check for modals
        modals = page.query_selector_all("[class*='modal'], [class*='overlay'], [role='dialog']")
        print(f"Found {len(modals)} modal/overlay elements")
        
        # Check page content
        body_text = page.evaluate("() => document.body.innerText")
        print(f"Page text length: {len(body_text)}")
    
    print("\nPress Enter to close...")
    input()
    browser.close()

