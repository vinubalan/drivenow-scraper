#!/usr/bin/env python3
"""
Script to inspect API calls made by the DriveNow website.
"""
from playwright.sync_api import sync_playwright
import json
import time

def inspect_api_calls():
    """Launch browser and capture all network requests."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
        # Capture all network requests
        api_calls = []
        
        def handle_request(request):
            url = request.url
            method = request.method
            if any(keyword in url.lower() for keyword in ['api', 'json', 'data', 'vehicle', 'car', 'detail', 'result']):
                api_calls.append({
                    'url': url,
                    'method': method,
                    'headers': request.headers,
                })
        
        def handle_response(response):
            url = response.url
            if any(keyword in url.lower() for keyword in ['api', 'json', 'data', 'vehicle', 'car', 'detail', 'result']):
                try:
                    content_type = response.headers.get('content-type', '')
                    if 'json' in content_type:
                        body = response.json()
                        api_calls.append({
                            'url': url,
                            'method': response.request.method,
                            'status': response.status,
                            'body': body,
                        })
                except:
                    pass
        
        page.on("request", handle_request)
        page.on("response", handle_response)
        
        # Navigate to results page
        results_url = "https://carhire.drivenow.com.au/drivenow/results/2025-11-18/10:00/2025-11-19/10:00/-33.86706149922719,151.2155219586914,2/-33.86706149922719,151.2155219586914,2/Sydney,%20New%20South%20Wales,%20Australia/Sydney,%20New%20South%20Wales,%20Australia/IN/30?radius=3&pickupCountry=AU&returnCountry=AU&bookingEngine=ube&affiliateCode=drivenow"
        
        print(f"Navigating to: {results_url}")
        page.goto(results_url, wait_until="networkidle")
        time.sleep(5)
        
        # Try clicking a "See Details" button
        try:
            buttons = page.query_selector_all("button:has-text('See Details'), a:has-text('See Details')")
            if buttons:
                print(f"Found {len(buttons)} 'See Details' buttons")
                print("Clicking first button and monitoring API calls...")
                buttons[0].click()
                time.sleep(5)
        except Exception as e:
            print(f"Error clicking button: {e}")
        
        # Print all API calls
        print("\n" + "="*80)
        print("API CALLS FOUND:")
        print("="*80)
        for i, call in enumerate(api_calls, 1):
            print(f"\n{i}. {call.get('method', 'GET')} {call.get('url', 'N/A')}")
            if 'status' in call:
                print(f"   Status: {call['status']}")
            if 'body' in call:
                print(f"   Response (first 500 chars): {str(call['body'])[:500]}")
        
        # Save to file
        with open('api_calls.json', 'w') as f:
            json.dump(api_calls, f, indent=2, default=str)
        
        print(f"\n\nSaved {len(api_calls)} API calls to api_calls.json")
        print("\nPress Enter to close browser...")
        input()
        
        browser.close()

if __name__ == "__main__":
    inspect_api_calls()

