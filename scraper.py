"""
Web scraper for DriveNow.com.au vehicle listings using Playwright.
"""
import time
import random
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext, TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright, Browser as AsyncBrowser, Page as AsyncPage, BrowserContext as AsyncBrowserContext
from bs4 import BeautifulSoup
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import asyncio
from PIL import Image
import os
from cloud_storage import CloudflareR2Storage

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# User agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


class DriveNowScraper:
    """Scraper for DriveNow.com.au website using Playwright."""
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize the scraper with configuration.
        
        Args:
            config_path: Path to configuration YAML file
        """
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.results_base_url = self.config['scraper']['results_base_url']
        # Force headless mode in CI environments (GitHub Actions, etc.)
        # CI environments don't have a display server
        is_ci = os.getenv('CI', '').lower() == 'true' or os.getenv('GITHUB_ACTIONS', '').lower() == 'true'
        self.headless = True if is_ci else self.config['scraper']['headless']
        if is_ci and not self.config['scraper']['headless']:
            logger.info("CI environment detected - forcing headless mode (no display server available)")
        self.page_load_wait = self.config['scraper']['page_load_wait']
        self.screenshot_enabled = self.config['scraper']['screenshot']['enabled']
        self.screenshot_dir = Path(self.config['scraper']['screenshot']['directory'])
        self.screenshot_dir.mkdir(exist_ok=True)
        
        # Initialize cloud storage if enabled
        self.use_cloud_storage = self.config.get('cloud_storage', {}).get('enabled', False)
        self.cloud_storage = None
        if self.use_cloud_storage:
            try:
                self.cloud_storage = CloudflareR2Storage()
                logger.info("Cloudflare R2 storage initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize cloud storage: {str(e)}. Falling back to local storage.")
                self.use_cloud_storage = False
        
        # Rate limiting settings
        rate_config = self.config['scraper']['rate_limiting']
        self.delay_between_requests = rate_config['delay_between_requests']
        self.delay_between_vehicles = rate_config['delay_between_vehicles']
        self.delay_between_cities = rate_config['delay_between_cities']
        self.random_delay_min = rate_config['random_delay_min']
        self.random_delay_max = rate_config['random_delay_max']
        self.delay_between_batches = rate_config.get('delay_between_batches', 10.0)
        
        # Anti-detection settings
        anti_detection = self.config['scraper'].get('anti_detection', {})
        self.rotate_user_agents = anti_detection.get('rotate_user_agents', True)
        self.randomize_viewport = anti_detection.get('randomize_viewport', True)
        
        # Parallel processing settings
        parallel_config = self.config['scraper'].get('parallel', {})
        self.parallel_enabled = parallel_config.get('enabled', False)
        self.parallel_workers = parallel_config.get('workers', 5)
        self.batch_size = parallel_config.get('batch_size', 5)
        # Phase 1 parallel workers (for data collection)
        self.phase1_workers = parallel_config.get('phase1_workers', 25)
        
        self.playwright = None
        self.browser = None
        self.page = None
        self.contexts = []  # For parallel workers
        self.async_contexts = []  # For async parallel workers
        self.async_browser = None
        self.async_playwright = None
        self.db_lock = threading.Lock()  # Thread-safe database access
        self._setup_browser()
    
    def _create_browser_context(self, user_agent: str = None) -> BrowserContext:
        """Create a browser context with anti-detection measures."""
        context_options = {
            'viewport': {
                'width': self.config['scraper']['window_width'],
                'height': self.config['scraper']['window_height']
            },
            'user_agent': user_agent or (random.choice(USER_AGENTS) if self.rotate_user_agents else USER_AGENTS[0]),
            'locale': 'en-AU',
            'timezone_id': 'Australia/Sydney',
        }
        
        # Randomize viewport slightly if enabled
        if self.randomize_viewport:
            base_width = self.config['scraper']['window_width']
            base_height = self.config['scraper']['window_height']
            context_options['viewport'] = {
                'width': base_width + random.randint(-50, 50),
                'height': base_height + random.randint(-50, 50)
            }
        
        context = self.browser.new_context(**context_options)
        
        # Add extra HTTP headers
        context.set_extra_http_headers({
            'Accept-Language': 'en-AU,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        # Override webdriver property
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        return context
    
    def _setup_browser(self):
        """Set up Playwright browser with anti-detection measures."""
        self.playwright = sync_playwright().start()
        
        # Browser launch options
        browser_args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
        ]
        
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=browser_args
        )
        
        # Create main context and page
        context = self._create_browser_context()
        self.page = context.new_page()
        
        # Note: Parallel processing will use async API instead of sync
        # We'll set up async browser in the parallel method
    
    def _random_delay(self):
        """Add a random delay to avoid detection."""
        delay = random.uniform(self.random_delay_min, self.random_delay_max)
        time.sleep(delay)
    
    def _calculate_dates(self) -> Dict[str, List[datetime]]:
        """
        Calculate pickup and return dates based on configuration.
        
        Pickup date is always the NEXT day at 10 AM.
        If running on Nov 17, pickup date will be Nov 18 at 10:00 AM.
        
        Returns:
            Dictionary with 'pickup' and 'returns' dates
        """
        # Get current date/time
        now = datetime.now()
        today = now.date()
        
        # Pickup date: ALWAYS next day at 10 AM
        # If today is Nov 17, pickup will be Nov 18 at 10:00 AM
        next_day = today + timedelta(days=1)
        pickup_date = datetime.combine(next_day, datetime.min.time().replace(hour=10, minute=0, second=0, microsecond=0))
        
        logger.info(f"Today: {today.strftime('%Y-%m-%d')}, Pickup date: {pickup_date.strftime('%Y-%m-%d %H:%M')}")
        
        # Return dates: Based on return_days config (e.g., [1, 7] means +1 day and +7 days from pickup)
        return_days = self.config['date_config']['return_days']
        return_dates = [
            pickup_date + timedelta(days=days) 
            for days in return_days
        ]
        
        logger.info(f"Return dates: {[d.strftime('%Y-%m-%d %H:%M') for d in return_dates]}")
        
        return {
            'pickup': pickup_date,
            'returns': return_dates
        }
    
    def _format_date_for_url(self, date: datetime) -> str:
        """Format date for URL (YYYY-MM-DD)."""
        return date.strftime("%Y-%m-%d")
    
    def _format_time_for_url(self, date: datetime) -> str:
        """Format time for URL (HH:MM)."""
        return date.strftime("%H:%M")
    
    def _build_results_url(self, city: Dict, pickup_date: datetime, return_date: datetime) -> str:
        """Build the results URL directly based on the URL pattern."""
        from urllib.parse import quote
        
        pickup_date_str = self._format_date_for_url(pickup_date)
        pickup_time_str = self._format_time_for_url(pickup_date)
        return_date_str = self._format_date_for_url(return_date)
        return_time_str = self._format_time_for_url(return_date)
        
        lat = city['latitude']
        lng = city['longitude']
        location = city['location_string']
        radius = city.get('radius', 3)
        
        location_encoded = quote(location, safe=',')
        
        url = (
            f"{self.results_base_url}/"
            f"{pickup_date_str}/{pickup_time_str}/"
            f"{return_date_str}/{return_time_str}/"
            f"{lat},{lng},2/{lat},{lng},2/"
            f"{location_encoded}/{location_encoded}/"
            f"AU/30?radius={radius}&pickupCountry=AU&returnCountry=AU&bookingEngine=ube&affiliateCode=drivenow"
        )
        
        return url
    
    def _wait_for_page_load(self, page: Page, timeout: int = None) -> bool:
        """Wait for page to be loaded with actual content."""
        if timeout is None:
            timeout = self.page_load_wait * 1000
        
        try:
            # Wait for DOM to be ready
            page.wait_for_load_state("domcontentloaded", timeout=timeout)
            
            # Wait for network to be mostly idle (but don't wait too long)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout, 10000))
            except:
                pass  # Continue even if networkidle times out
            
            # Wait for JavaScript to execute and content to render
            time.sleep(1)
            
            # Verify page has content
            try:
                body_text = page.evaluate("() => document.body.innerText")
                if len(body_text) < 20:
                    logger.warning("Page has very little text content")
                    time.sleep(2)  # Wait more for content to load
            except:
                pass
            
            return True
        except PlaywrightTimeout:
            logger.warning("Page load timeout, but continuing...")
            return False
    
    def _get_vehicle_listings(self, page: Page) -> List[Dict]:
        """
        Extract vehicle listings from the results page.
        Returns list of vehicle info with selectors for "See Details" buttons.
        """
        vehicles = []
        
        try:
            # Wait for dynamic content to load
            time.sleep(1)
            
            # Wait for vehicle listings to appear
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
                    elements = page.query_selector_all(selector)
                    if elements and len(elements) > 0:
                        vehicle_elements = elements
                        logger.info(f"Found {len(elements)} vehicle elements using selector: {selector}")
                        break
                except:
                    continue
            
            if not vehicle_elements:
                # Fallback: try to find any clickable elements that might be "See Details"
                logger.warning("Could not find vehicle cards, trying fallback method...")
                # Try to find buttons/links that might be "See Details"
                see_details_selectors = [
                    "button:has-text('See Details')",
                    "a:has-text('See Details')",
                    "button:has-text('Details')",
                    "a:has-text('Details')",
                    "[class*='details']",
                    "[class*='see-details']",
                ]
                
                for selector in see_details_selectors:
                    try:
                        elements = page.query_selector_all(selector)
                        if elements:
                            logger.info(f"Found {len(elements)} detail buttons using selector: {selector}")
                            # Create vehicle entries for each button
                            for idx, btn in enumerate(elements):
                                vehicles.append({
                                    'index': idx,
                                    'detail_button': btn,
                                    'selector': selector,
                                })
                            return vehicles
                    except:
                        continue
            
            # First, try to find ALL "See Details" buttons on the page
            all_detail_buttons = []
            detail_selectors = [
                "button:has-text('See Details')",
                "a:has-text('See Details')",
                "button:has-text('Details')",
                "a:has-text('Details')",
                "button[class*='details']",
                "a[class*='details']",
                "button[class*='detail']",
                "a[class*='detail']",
            ]
            
            for selector in detail_selectors:
                try:
                    buttons = page.query_selector_all(selector)
                    if buttons:
                        all_detail_buttons = buttons
                        logger.info(f"Found {len(buttons)} detail buttons using selector: {selector}")
                        break
                except:
                    continue
            
            # If we found buttons directly, match them to vehicle elements
            if all_detail_buttons and len(all_detail_buttons) > 0:
                logger.info(f"Found {len(all_detail_buttons)} detail buttons, matching to {len(vehicle_elements)} vehicle elements")
                # Match buttons to vehicles (assuming same order)
                for idx, element in enumerate(vehicle_elements):
                    if idx < len(all_detail_buttons):
                        see_details_button = all_detail_buttons[idx]
                    else:
                        # Try to find button within this specific element
                        see_details_button = None
                        for selector in detail_selectors:
                            try:
                                btn = element.query_selector(selector)
                                if btn:
                                    see_details_button = btn
                                    break
                            except:
                                continue
                    
                    if see_details_button:
                        # Extract vehicle info
                        vehicle_name = None
                        price = None
                        detail_url = None
                        
                        try:
                            name_elem = element.query_selector("h2, h3, h4, [class*='name'], [class*='title']")
                            if name_elem:
                                vehicle_name = name_elem.inner_text().strip()
                            
                            price_elem = element.query_selector("[class*='price'], [class*='cost'], [class*='rate']")
                            if price_elem:
                                price_text = price_elem.inner_text().strip()
                                import re
                                price_match = re.search(r'[\d,]+\.?\d*', price_text.replace(',', ''))
                                if price_match:
                                    price = float(price_match.group().replace(',', ''))
                            
                            # Extract detail URL
                            try:
                                if see_details_button.get_attribute('href'):
                                    detail_url = see_details_button.get_attribute('href')
                                    if detail_url and not detail_url.startswith('http'):
                                        from urllib.parse import urljoin
                                        detail_url = urljoin(page.url, detail_url)
                                else:
                                    # Try onclick handler
                                    onclick = see_details_button.evaluate('el => el.getAttribute("onclick")')
                                    if onclick:
                                        import re
                                        match = re.search(r'["\']([^"\']+)["\']', onclick)
                                        if match:
                                            detail_url = match.group(1)
                                    
                                    # Try data attributes
                                    if not detail_url:
                                        data_url = see_details_button.get_attribute('data-url') or \
                                                  see_details_button.get_attribute('data-href') or \
                                                  see_details_button.get_attribute('data-link')
                                        if data_url:
                                            detail_url = data_url
                                            if not detail_url.startswith('http'):
                                                from urllib.parse import urljoin
                                                detail_url = urljoin(page.url, detail_url)
                            except:
                                pass
                        except:
                            pass
                        
                        vehicles.append({
                            'index': idx,
                            'vehicle_name': vehicle_name or f"Vehicle {idx + 1}",
                            'price': price,
                            'detail_url': detail_url,
                            'detail_button': see_details_button,  # Keep for fallback
                            'element': element,
                        })
                
                if vehicles:
                    logger.info(f"Found {len(vehicles)} vehicles with 'See Details' buttons")
                    return vehicles
            
            # Fallback: Extract vehicle info and find "See Details" buttons within each element
            for idx, element in enumerate(vehicle_elements):
                try:
                    # Try to find "See Details" button within this vehicle element
                    see_details_button = None
                    detail_selectors = [
                        "button:has-text('See Details')",
                        "a:has-text('See Details')",
                        "button:has-text('Details')",
                        "a:has-text('Details')",
                        "button[class*='details']",
                        "a[class*='details']",
                        "button",
                        "a[href*='detail']",
                        "a[href*='vehicle']",
                        "[role='button']",
                    ]
                    
                    for detail_selector in detail_selectors:
                        try:
                            btn = element.query_selector(detail_selector)
                            if btn:
                                # Check if button text contains "detail" or "see"
                                btn_text = btn.inner_text().lower()
                                if any(keyword in btn_text for keyword in ['detail', 'see', 'view', 'more', 'info']):
                                    see_details_button = btn
                                    break
                                # Also accept if it's the only button/link in the card
                                elif detail_selector in ["button", "a[href*='detail']", "a[href*='vehicle']"]:
                                    see_details_button = btn
                                    break
                        except:
                            continue
                    
                    # If not found in element, try to find nearby
                    if not see_details_button:
                        # Try to find by text in the element
                        element_text = element.inner_text()
                        if 'see details' in element_text.lower() or 'details' in element_text.lower():
                            # Try to find button/link in parent or nearby
                            try:
                                parent = element.evaluate_handle("el => el.parentElement")
                                if parent:
                                    for detail_selector in detail_selectors:
                                        try:
                                            btn = parent.query_selector(detail_selector)
                                            if btn:
                                                see_details_button = btn
                                                break
                                        except:
                                            continue
                            except:
                                pass
                    
                    # Extract vehicle name and price from element
                    vehicle_name = None
                    price = None
                    
                    try:
                        # Try to find vehicle name
                        name_elem = element.query_selector("h2, h3, [class*='name'], [class*='title']")
                        if name_elem:
                            vehicle_name = name_elem.inner_text().strip()
                        
                        # Try to find price
                        price_elem = element.query_selector("[class*='price'], [class*='cost']")
                        if price_elem:
                            price_text = price_elem.inner_text().strip()
                            import re
                            price_match = re.search(r'[\d,]+\.?\d*', price_text.replace(',', ''))
                            if price_match:
                                price = float(price_match.group().replace(',', ''))
                    except:
                        pass
                    
                    if see_details_button:
                        # Extract detail URL
                        detail_url = None
                        try:
                            if see_details_button.get_attribute('href'):
                                detail_url = see_details_button.get_attribute('href')
                                if detail_url and not detail_url.startswith('http'):
                                    from urllib.parse import urljoin
                                    detail_url = urljoin(page.url, detail_url)
                            else:
                                # Try onclick handler
                                onclick = see_details_button.evaluate('el => el.getAttribute("onclick")')
                                if onclick:
                                    import re
                                    match = re.search(r'["\']([^"\']+)["\']', onclick)
                                    if match:
                                        detail_url = match.group(1)
                                
                                # Try data attributes
                                if not detail_url:
                                    data_url = see_details_button.get_attribute('data-url') or \
                                              see_details_button.get_attribute('data-href') or \
                                              see_details_button.get_attribute('data-link')
                                    if data_url:
                                        detail_url = data_url
                                        if not detail_url.startswith('http'):
                                            from urllib.parse import urljoin
                                            detail_url = urljoin(page.url, detail_url)
                        except:
                            pass
                        
                        vehicles.append({
                            'index': idx,
                            'vehicle_name': vehicle_name or f"Vehicle {idx + 1}",
                            'price': price,
                            'detail_url': detail_url,
                            'detail_button': see_details_button,  # Keep for fallback
                            'element': element,
                        })
                except Exception as e:
                    logger.warning(f"Error processing vehicle {idx}: {str(e)}")
                    continue
            
            logger.info(f"Found {len(vehicles)} vehicles with 'See Details' buttons")
            return vehicles
            
        except Exception as e:
            logger.error(f"Error extracting vehicle listings: {str(e)}")
            return []
    
    async def _scrape_vehicle_detail_worker_async(self, context: AsyncBrowserContext, vehicle: Dict, 
                                                  results_url: str, city_name: str,
                                                  pickup_date: datetime, return_date: datetime, 
                                                  scrape_timestamp: str) -> Optional[Dict]:
        """
        Worker function to scrape a single vehicle detail page.
        Used for parallel processing - processes one vehicle independently.
        """
        page = None
        try:
            page = await context.new_page()
            
            # Navigate to results page first
            await page.goto(results_url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(0.5)  # Quick wait for initial load
            
            # Wait for page to be ready
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=8000)
            except:
                pass
            
            # Find the "See Details" button for this vehicle
            # We need to find it by vehicle name or index
            vehicle_index = vehicle.get('index', 0)
            see_details_button = None
            
            # Try to find the button using various selectors
            detail_selectors = [
                f"button:has-text('See Details')",
                f"a:has-text('See Details')",
                f"button:has-text('Details')",
                f"a:has-text('Details')",
            ]
            
            # Get all detail buttons and click the one at vehicle_index
            for selector in detail_selectors:
                try:
                    buttons = await page.query_selector_all(selector)
                    if buttons and len(buttons) > vehicle_index:
                        see_details_button = buttons[vehicle_index]
                        break
                except:
                    continue
            
            if not see_details_button:
                # Fallback: try to find by vehicle card index
                vehicle_selectors = [
                    ".vehicle-card",
                    ".car-card",
                    ".vehicle-item",
                    "[class*='vehicle']",
                ]
                
                for card_selector in vehicle_selectors:
                    try:
                        cards = await page.query_selector_all(card_selector)
                        if cards and len(cards) > vehicle_index:
                            card = cards[vehicle_index]
                            # Find button within this card
                            for detail_selector in detail_selectors:
                                btn = await card.query_selector(detail_selector)
                                if btn:
                                    see_details_button = btn
                                    break
                            if see_details_button:
                                break
                    except:
                        continue
            
            if not see_details_button:
                raise Exception(f"Could not find 'See Details' button for vehicle {vehicle_index}")
            
            # Click "See Details" button
            logger.info(f"[Worker] Clicking 'See Details' for vehicle: {vehicle.get('vehicle_name', 'Unknown')}")
            
            # Click and wait for navigation or content
            try:
                async with page.expect_navigation(timeout=8000, wait_until="domcontentloaded"):
                    await see_details_button.click()
            except:
                # No navigation - might be modal, just wait a bit
                await asyncio.sleep(1)
            
            # Wait for content to load (reasonable wait for proper rendering)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=8000)
                await asyncio.sleep(1)  # Wait for content to render
            except:
                pass
            
            # Scroll to top
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)
            
            # Generate screenshot filename
            city_safe = city_name.replace(' ', '_').lower()
            pickup_str = pickup_date.strftime("%Y%m%d_%H%M")
            return_str = return_date.strftime("%Y%m%d_%H%M")
            vehicle_safe = vehicle.get('vehicle_name', f"vehicle_{vehicle['index']}").replace(' ', '_').replace('/', '_').lower()[:50]
            filename = f"{city_safe}_{pickup_str}_{return_str}_{vehicle_safe}_{scrape_timestamp}.png"
            screenshot_path = self.screenshot_dir / filename
            
            # Take full page screenshot
            if self.screenshot_enabled:
                await page.screenshot(path=str(screenshot_path), full_page=True)
                logger.info(f"[Worker] Full page screenshot saved: {screenshot_path}")
                screenshot_path_str = str(screenshot_path)
            else:
                screenshot_path_str = None
            
            return {
                'vehicle_name': vehicle.get('vehicle_name'),
                'price': vehicle.get('price'),
                'screenshot_path': screenshot_path_str,
                'success': True
            }
            
        except Exception as e:
            logger.error(f"[Worker] Error scraping vehicle detail: {str(e)}")
            return {
                'vehicle_name': vehicle.get('vehicle_name'),
                'price': vehicle.get('price'),
                'screenshot_path': None,
                'success': False,
                'error': str(e)
            }
        finally:
            if page:
                await page.close()
    
    async def _wait_for_page_load_async(self, page: AsyncPage, timeout: int = None):
        """Wait for page to be loaded (async version - reasonable waits)."""
        if timeout is None:
            timeout = self.page_load_wait * 1000
        
        try:
            # Wait for DOM to be ready
            await page.wait_for_load_state("domcontentloaded", timeout=timeout)
            # Wait a bit for content to render
            await asyncio.sleep(1)
            return True
        except PlaywrightTimeout:
            return False
    
    def _scrape_vehicle_detail(self, page: Page, vehicle: Dict, city_name: str, 
                               pickup_date: datetime, return_date: datetime, 
                               scrape_timestamp: str, results_url: str) -> Optional[str]:
        """
        Click "See Details" for a vehicle, wait for detail page to load, and take screenshot.
        Uses a new tab for faster processing (no need to go back).
        
        Returns:
            Path to screenshot file or None
        """
        if not self.screenshot_enabled:
            return None
        
        detail_page = None
        try:
            # Click "See Details" button and wait for new page/tab
            logger.info(f"Clicking 'See Details' for vehicle: {vehicle.get('vehicle_name', 'Unknown')}")
            
            # Get the href if it's a link, or click button
            detail_url = None
            try:
                if vehicle['detail_button'].get_attribute('href'):
                    detail_url = vehicle['detail_button'].get_attribute('href')
                elif vehicle['detail_button'].evaluate('el => el.onclick'):
                    # Try to get URL from onclick handler
                    onclick = vehicle['detail_button'].evaluate('el => el.getAttribute("onclick")')
                    if onclick and 'href' in onclick:
                        import re
                        match = re.search(r'href=["\']([^"\']+)["\']', onclick)
                        if match:
                            detail_url = match.group(1)
            except:
                pass
            
            # Check if clicking opens a modal/overlay or navigates
            current_url_before = page.url
            
            # Click button and wait to see what happens
            try:
                # Use expect_navigation to detect if page navigates
                with page.expect_navigation(timeout=5000, wait_until="domcontentloaded") as navigation_info:
                    vehicle['detail_button'].click()
                detail_page = page
                logger.info("Navigation occurred after click")
            except:
                # No navigation detected - might be a modal/overlay or inline content
                logger.info("No navigation detected, checking for modal/overlay or inline content...")
                detail_page = page
                time.sleep(1)
                
                # Check if URL changed anyway
                current_url_after = detail_page.url
                if current_url_before != current_url_after:
                    logger.info("URL changed even though navigation wasn't detected")
                else:
                    # URL unchanged - likely a modal/overlay
                    logger.info("URL unchanged - likely a modal/overlay, waiting for it to appear...")
                    # Look for modal/overlay elements
                    modal_selectors = [
                        "[class*='modal']",
                        "[class*='overlay']",
                        "[class*='popup']",
                        "[class*='dialog']",
                        "[role='dialog']",
                        "[id*='modal']",
                        "[class*='detail']",
                    ]
                    
                    modal_found = False
                    for selector in modal_selectors:
                        try:
                            modal = detail_page.query_selector(selector)
                            if modal:
                                logger.info(f"Found modal/overlay element: {selector}")
                                modal_found = True
                                # Wait for modal content to load
                                time.sleep(2)
                                break
                        except:
                            continue
                    
                    if not modal_found:
                        logger.info("No modal found, might be inline content - waiting for content to appear")
                        time.sleep(2)
            
            # Wait for content to load properly (reasonable waits)
            logger.info("Waiting for content to appear...")
            
            # Wait for DOM
            try:
                detail_page.wait_for_load_state("domcontentloaded", timeout=8000)
            except:
                pass
            
            # Wait for content to render
            time.sleep(1.5)
            
            # Check for content elements
            try:
                detail_page.wait_for_selector("body", timeout=3000, state="visible")
            except:
                pass
            
            # Additional wait for rendering
            time.sleep(1)
            
            # Scroll to top
            detail_page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.3)
            
            # Generate screenshot filename
            city_safe = city_name.replace(' ', '_').lower()
            pickup_str = pickup_date.strftime("%Y%m%d_%H%M")
            return_str = return_date.strftime("%Y%m%d_%H%M")
            vehicle_safe = vehicle.get('vehicle_name', f"vehicle_{vehicle['index']}").replace(' ', '_').replace('/', '_').lower()[:50]
            filename = f"{city_safe}_{pickup_str}_{return_str}_{vehicle_safe}_{scrape_timestamp}.png"
            screenshot_path = self.screenshot_dir / filename
            
            # Take full page screenshot - ensure page is visible
            try:
                # Make sure page is in view and focused
                detail_page.evaluate("window.scrollTo(0, 0)")
                detail_page.bring_to_front()  # Ensure page is in front
                time.sleep(0.5)
                
                # Get current URL for logging
                current_url = detail_page.url
                logger.info(f"Taking screenshot of URL: {current_url}")
                
                # Take screenshot with full page
                detail_page.screenshot(
                    path=str(screenshot_path), 
                    full_page=True, 
                    timeout=30000,
                    animations='disabled'  # Disable animations for faster capture
                )
                logger.info(f"Full page screenshot saved: {screenshot_path}")
                
                # Verify screenshot was created and has content
                import os
                if os.path.exists(str(screenshot_path)):
                    file_size = os.path.getsize(str(screenshot_path))
                    logger.info(f"Screenshot file size: {file_size} bytes")
                    if file_size < 10000:  # Less than 10KB might be suspicious
                        logger.warning(f"Screenshot seems small ({file_size} bytes), might have issues")
                else:
                    logger.error("Screenshot file was not created!")
                    return None
            except Exception as e:
                logger.error(f"Error taking screenshot: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                return None
            
            # Close detail page if it's a new tab, or navigate back if same page
            if detail_page != page:
                detail_page.close()
            else:
                # Navigate back to results
                page.goto(results_url, wait_until="domcontentloaded", timeout=8000)
                self._wait_for_page_load(page, timeout=5000)
            
            return str(screenshot_path)
            
        except Exception as e:
            logger.error(f"Error scraping vehicle detail: {str(e)}")
            # Cleanup
            if detail_page and detail_page != page:
                try:
                    detail_page.close()
                except:
                    pass
            # Navigate back to results if needed
            if page.url != results_url:
                try:
                    page.goto(results_url, wait_until="domcontentloaded", timeout=8000)
                except:
                    pass
            return None
    
    def _search_vehicles(self, city: Dict, pickup_date: datetime, return_date: datetime) -> bool:
        """Navigate to results page and wait for it to load."""
        try:
            city_name = city['name']
            logger.info(f"Searching for vehicles in {city_name} from {pickup_date} to {return_date}")
            
            results_url = self._build_results_url(city, pickup_date, return_date)
            logger.info(f"Results URL: {results_url}")
            
            # Navigate to results page
            self.page.goto(results_url, wait_until="domcontentloaded")
            
            # Wait for page to load (reasonable wait)
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=8000)
                time.sleep(0.5)  # Wait for initial content
            except:
                pass
            
            logger.info(f"Page ready for {city_name}")
            return True
                
        except Exception as e:
            logger.error(f"Error navigating to results URL: {str(e)}")
            return False
    
    def scrape_city(self, city: Dict, db, collect_only: bool = False) -> List[Dict]:
        """
        Scrape vehicles for a specific city.
        
        Args:
            city: City configuration dict
            db: Database instance
            collect_only: If True, only collect data and URLs without screenshots (Phase 1)
        """
        city_name = city['name']
        dates = self._calculate_dates()
        pickup_date = dates['pickup']
        return_dates = dates['returns']
        
        scrape_datetime = datetime.now().isoformat()
        
        all_vehicles = []
        
        for return_date in return_dates:
            try:
                # Navigate to results page
                if not self._search_vehicles(city, pickup_date, return_date):
                    logger.warning(f"Navigation failed for {city_name} ({pickup_date} to {return_date})")
                    continue
                
                # Rate limiting delay
                self._random_delay()
                time.sleep(self.delay_between_requests)
                
                # Get vehicle listings
                logger.info("Extracting vehicle listings...")
                vehicles = self._get_vehicle_listings(self.page)
                
                if not vehicles:
                    logger.warning(f"No vehicles found for {city_name} ({pickup_date} to {return_date})")
                    continue
                
                logger.info(f"Found {len(vehicles)} vehicles")
                
                if collect_only:
                    # Phase 1: Just collect data and URLs, no screenshots
                    logger.info(f"Phase 1: Collecting data for {len(vehicles)} vehicles...")
                    for idx, vehicle in enumerate(vehicles):
                        try:
                            vehicle_data = {
                                'scrape_date': scrape_date,
                                'scrape_timestamp': scrape_timestamp,
                                'city': city_name,
                                'pickup_date': pickup_date.isoformat(),
                                'return_date': return_date.isoformat(),
                                'vehicle_name': vehicle.get('vehicle_name'),
                                'vehicle_category': None,
                                'price_per_day': vehicle.get('price'),
                                'total_price': vehicle.get('price'),
                                'currency': 'AUD',
                                'availability': 'Available',
                                'vehicle_details': {},
                                'detail_url': vehicle.get('detail_url'),  # Store URL for Phase 2
                                'screenshot_path': None,  # Will be filled in Phase 2
                            }
                            
                            vehicle_id = db.insert_vehicle(vehicle_data)
                            vehicle_data['id'] = vehicle_id
                            all_vehicles.append(vehicle_data)
                            
                            if (idx + 1) % 10 == 0:
                                logger.info(f"Collected {idx + 1}/{len(vehicles)} vehicles...")
                            
                        except Exception as e:
                            logger.error(f"Error saving vehicle {idx + 1}: {str(e)}")
                            continue
                    
                    logger.info(f"Phase 1 complete: Collected {len(vehicles)} vehicles for {city_name} ({pickup_date.date()} to {return_date.date()})")
                else:
                    # Phase 2: Take screenshots (original method - kept for backward compatibility)
                    logger.info(f"Found {len(vehicles)} vehicles, scraping details...")
                    results_url = self._build_results_url(city, pickup_date, return_date)
                    
                    # Use parallel processing if enabled
                    if self.parallel_enabled:
                        logger.info(f"Using parallel processing with {self.parallel_workers} workers...")
                        self._scrape_vehicles_parallel(
                            vehicles, results_url, city_name, pickup_date, return_date,
                            scrape_date, scrape_timestamp, db, all_vehicles
                        )
                    else:
                        # Sequential processing
                        logger.info("Using sequential processing...")
                        for idx, vehicle in enumerate(vehicles):
                            try:
                                logger.info(f"Processing vehicle {idx + 1}/{len(vehicles)}")
                                
                                screenshot_path = self._scrape_vehicle_detail(
                                    self.page, vehicle, city_name, pickup_date, return_date, scrape_timestamp, results_url
                                )
                                
                                if idx < len(vehicles) - 1:
                                    time.sleep(0.1)
                                
                                vehicle_data = {
                                    'scrape_date': scrape_date,
                                    'scrape_timestamp': scrape_timestamp,
                                    'city': city_name,
                                    'pickup_date': pickup_date.isoformat(),
                                    'return_date': return_date.isoformat(),
                                    'vehicle_name': vehicle.get('vehicle_name'),
                                    'vehicle_category': None,
                                    'price_per_day': vehicle.get('price'),
                                    'total_price': vehicle.get('price'),
                                    'currency': 'AUD',
                                    'availability': 'Available',
                                    'vehicle_details': {},
                                    'screenshot_path': screenshot_path,
                                }
                                
                                vehicle_id = db.insert_vehicle(vehicle_data)
                                all_vehicles.append(vehicle_data)
                                
                                logger.info(f"Saved vehicle {idx + 1}/{len(vehicles)}: {vehicle.get('vehicle_name', 'Unknown')}")
                                
                            except Exception as e:
                                logger.error(f"Error processing vehicle {idx + 1}: {str(e)}")
                                continue
                
            except Exception as e:
                logger.error(f"Error scraping {city_name} for dates {pickup_date} to {return_date}: {str(e)}")
                continue
        
        return all_vehicles
    
    async def _setup_async_browser(self, num_workers: int = None):
        """
        Set up async browser for parallel processing.
        
        Args:
            num_workers: Number of browser contexts to create. If None, uses parallel_workers.
        """
        if not self.async_playwright:
            self.async_playwright = await async_playwright().start()
            
            browser_args = [
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
            
            self.async_browser = await self.async_playwright.chromium.launch(
                headless=self.headless,
                args=browser_args
            )
        
        # Use specified workers or default to parallel_workers
        workers = num_workers or self.parallel_workers
        
        # Only create new contexts if we need more
        while len(self.async_contexts) < workers:
            context_options = {
                'viewport': {
                    'width': self.config['scraper']['window_width'],
                    'height': self.config['scraper']['window_height']
                },
                'user_agent': random.choice(USER_AGENTS),
                'locale': 'en-AU',
                'timezone_id': 'Australia/Sydney',
            }
            
            if self.randomize_viewport:
                base_width = self.config['scraper']['window_width']
                base_height = self.config['scraper']['window_height']
                context_options['viewport'] = {
                    'width': base_width + random.randint(-50, 50),
                    'height': base_height + random.randint(-50, 50)
                }
            
            context = await self.async_browser.new_context(**context_options)
            await context.set_extra_http_headers({
                'Accept-Language': 'en-AU,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            })
            
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)
            
            self.async_contexts.append(context)
        
        # Trim contexts if we have too many
        if len(self.async_contexts) > workers:
            excess = self.async_contexts[workers:]
            for context in excess:
                try:
                    await context.close()
                except:
                    pass
            self.async_contexts = self.async_contexts[:workers]
    
    async def _scrape_vehicles_parallel_async(self, vehicles: List[Dict], results_url: str,
                                              city_name: str, pickup_date: datetime, return_date: datetime,
                                              scrape_date: str, scrape_timestamp: str, db, all_vehicles: List[Dict]):
        """Scrape vehicles in parallel using async API."""
        # Set up async browser if not already done
        await self._setup_async_browser()
        
        # Process vehicles in batches
        for batch_start in range(0, len(vehicles), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(vehicles))
            batch = vehicles[batch_start:batch_end]
            
            logger.info(f"Processing batch {batch_start//self.batch_size + 1}: vehicles {batch_start + 1}-{batch_end} of {len(vehicles)}")
            
            # Create tasks for all vehicles in batch
            tasks = []
            for idx, vehicle in enumerate(batch):
                # Assign worker context (round-robin)
                worker_idx = (batch_start + idx) % len(self.async_contexts)
                context = self.async_contexts[worker_idx]
                
                task = self._scrape_vehicle_detail_worker_async(
                    context, vehicle, results_url, city_name,
                    pickup_date, return_date, scrape_timestamp
                )
                tasks.append((task, vehicle))
            
            # Run all tasks concurrently
            results = await asyncio.gather(*[t[0] for t in tasks], return_exceptions=True)
            
            # Process results
            for (task, vehicle), result in zip(tasks, results):
                try:
                    if isinstance(result, Exception):
                        logger.error(f"Error in async task: {str(result)}")
                        continue
                    
                    if result and result.get('success'):
                        # Save vehicle to database (thread-safe)
                        vehicle_data = {
                            'scrape_date': scrape_date,
                            'scrape_timestamp': scrape_timestamp,
                            'city': city_name,
                            'pickup_date': pickup_date.isoformat(),
                            'return_date': return_date.isoformat(),
                            'vehicle_name': result.get('vehicle_name'),
                            'vehicle_category': None,
                            'price_per_day': result.get('price'),
                            'total_price': result.get('price'),
                            'currency': 'AUD',
                            'availability': 'Available',
                            'vehicle_details': {},
                            'screenshot_path': result.get('screenshot_path'),
                        }
                        
                        with self.db_lock:
                            db.insert_vehicle(vehicle_data)
                            all_vehicles.append(vehicle_data)
                        
                        logger.info(f"✓ Saved: {result.get('vehicle_name', 'Unknown')}")
                    else:
                        logger.warning(f"✗ Failed: {vehicle.get('vehicle_name', 'Unknown')} - {result.get('error', 'Unknown error')}")
                        
                except Exception as e:
                    logger.error(f"Error processing vehicle result: {str(e)}")
            
            # Longer delay between batches to avoid detection
            if batch_end < len(vehicles):
                batch_delay = self.delay_between_batches + random.uniform(self.random_delay_min, self.random_delay_max)
                logger.info(f"Waiting {batch_delay:.1f} seconds before next screenshot batch to avoid detection...")
                await asyncio.sleep(batch_delay)
    
    def _scrape_vehicles_parallel(self, vehicles: List[Dict], results_url: str,
                                  city_name: str, pickup_date: datetime, return_date: datetime,
                                  scrape_date: str, scrape_timestamp: str, db, all_vehicles: List[Dict]):
        """Scrape vehicles in parallel using async API (wrapper for sync code)."""
        # Always create a new event loop in a thread to avoid conflicts
        import concurrent.futures
        import threading
        
        def run_async():
            # Create new event loop in this thread
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                new_loop.run_until_complete(self._scrape_vehicles_parallel_async(
                    vehicles, results_url, city_name, pickup_date, return_date,
                    scrape_date, scrape_timestamp, db, all_vehicles
                ))
            finally:
                new_loop.close()
        
        # Run in a separate thread with its own event loop
        thread = threading.Thread(target=run_async, daemon=False)
        thread.start()
        thread.join()  # Wait for completion
    
    def _generate_screenshot_path(self, vehicle: Dict) -> str:
        """Generate screenshot file path for a vehicle."""
        city_safe = vehicle['city'].replace(' ', '_').lower()
        pickup_date = datetime.fromisoformat(vehicle['pickup_date'])
        return_date = datetime.fromisoformat(vehicle['return_date'])
        pickup_str = pickup_date.strftime("%Y%m%d_%H%M")
        return_str = return_date.strftime("%Y%m%d_%H%M")
        vehicle_safe = (vehicle.get('vehicle_name') or f"vehicle_{vehicle.get('id', 'unknown')}").replace(' ', '_').replace('/', '_').lower()[:50]
        # Extract timestamp from scrape_datetime for filename
        scrape_datetime_str = vehicle.get('scrape_datetime', datetime.now().isoformat())
        try:
            dt = datetime.fromisoformat(scrape_datetime_str.replace('Z', '+00:00'))
            scrape_timestamp = dt.strftime("%Y%m%d_%H%M%S")
        except:
            scrape_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{city_safe}_{pickup_str}_{return_str}_{vehicle_safe}_{scrape_timestamp}.png"
        return str(self.screenshot_dir / filename)
    
    def _generate_results_screenshot_path(self, city: str, pickup_date: datetime, return_date: datetime, scrape_datetime: str) -> str:
        """Generate screenshot file path for a results page (city-date combination)."""
        city_safe = city.replace(' ', '_').lower()
        pickup_str = pickup_date.strftime("%Y%m%d_%H%M")
        return_str = return_date.strftime("%Y%m%d_%H%M")
        # Extract timestamp from scrape_datetime for filename
        try:
            dt = datetime.fromisoformat(scrape_datetime.replace('Z', '+00:00'))
            scrape_timestamp = dt.strftime("%Y%m%d_%H%M%S")
        except:
            scrape_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{city_safe}_{pickup_str}_{return_str}_results_{scrape_timestamp}.png"
        return str(self.screenshot_dir / filename)
    
    def _compress_screenshot(self, screenshot_path: str, quality: int = 75, max_width: int = 1920) -> tuple:
        """
        Compress a screenshot to reduce file size.
        Converts to JPEG format for better compression (screenshots don't need transparency).
        
        Args:
            screenshot_path: Path to the screenshot file
            quality: JPEG quality (1-100, lower = smaller file but lower quality)
            max_width: Maximum width in pixels (resize if larger to reduce file size)
            
        Returns:
            Tuple of (success: bool, new_path: str) - new_path may be different if converted to JPEG
        """
        try:
            if not os.path.exists(screenshot_path):
                logger.warning(f"Screenshot file not found for compression: {screenshot_path}")
                return False, screenshot_path
            
            # Get original file size
            original_size = os.path.getsize(screenshot_path)
            
            # Open the image
            with Image.open(screenshot_path) as img:
                # Convert RGBA to RGB (removes alpha channel)
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create a white background for transparency
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    rgb_img.paste(img, mask=img.split()[3] if img.mode == 'RGBA' else None)
                    img = rgb_img
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Resize if image is too wide (maintains aspect ratio)
                original_dimensions = (img.width, img.height)
                if img.width > max_width:
                    ratio = max_width / img.width
                    new_height = int(img.height * ratio)
                    img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                    logger.debug(f"Resized image from {original_dimensions} to {max_width}x{new_height}")
                
                # Convert PNG path to JPEG path
                jpeg_path = screenshot_path.replace('.png', '.jpg')
                
                # Save as JPEG with quality setting (much better compression than PNG)
                img.save(
                    jpeg_path,
                    'JPEG',
                    quality=quality,
                    optimize=True
                )
                
                # Remove original PNG file
                os.remove(screenshot_path)
            
            # Get compressed file size
            compressed_size = os.path.getsize(jpeg_path)
            compression_ratio = (1 - compressed_size / original_size) * 100
            
            logger.info(f"Compressed screenshot: {os.path.basename(screenshot_path)} -> {os.path.basename(jpeg_path)}")
            logger.info(f"  Original size: {original_size / 1024:.1f} KB")
            logger.info(f"  Compressed size: {compressed_size / 1024:.1f} KB")
            logger.info(f"  Compression: {compression_ratio:.1f}% reduction")
            
            return True, jpeg_path
        except Exception as e:
            logger.error(f"Error compressing screenshot {screenshot_path}: {str(e)}", exc_info=True)
            return False, screenshot_path
    
    async def _capture_screenshot_batch_async(self, context: AsyncBrowserContext, 
                                              detail_url: str, screenshot_path: str) -> bool:
        """Capture screenshot for a single detail URL."""
        page = None
        try:
            page = await context.new_page()
            
            # Add random delay before navigating to avoid detection
            pre_navigation_delay = random.uniform(self.random_delay_min, self.random_delay_max)
            await asyncio.sleep(pre_navigation_delay)
            
            # Navigate to detail page
            await page.goto(detail_url, wait_until="domcontentloaded", timeout=20000)
            
            # Wait for DOM to be ready
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except:
                logger.debug(f"DOM load timeout for {detail_url}, continuing...")
            
            # Wait for network to be mostly idle (important for dynamic content)
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
                logger.debug(f"Network idle reached for {detail_url}")
            except:
                logger.debug(f"Network idle timeout for {detail_url} (continuing anyway)")
            
            # Additional wait for initial content to load
            await asyncio.sleep(3)
            
            # Additional wait for dynamic content to render
            await asyncio.sleep(2)
            
            # Wait for page content to appear - check for common vehicle detail page elements
            content_selectors = [
                "body",
                "[class*='vehicle']",
                "[class*='detail']",
                "[class*='booking']",
                "h1",
                "h2",
            ]
            
            content_found = False
            for selector in content_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=5000, state="visible")
                    elements = await page.query_selector_all(selector)
                    if elements and len(elements) > 0:
                        content_found = True
                        break
                except:
                    continue
            
            if not content_found:
                logger.warning(f"No content found immediately for {detail_url}, waiting more...")
                await asyncio.sleep(3)
            
            # Additional wait for JavaScript to fully render
            await asyncio.sleep(2)
            
            # Verify page has substantial content
            try:
                body_text = await page.evaluate("() => document.body.innerText")
                if len(body_text) < 100:
                    logger.warning(f"Page content seems minimal ({len(body_text)} chars) for {detail_url}, waiting more...")
                    await asyncio.sleep(3)
            except:
                pass
            
            # Wait for network idle one more time to ensure all resources are loaded
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except:
                pass
            
            # Additional wait for final rendering
            await asyncio.sleep(2)
            
            # Scroll to top to ensure we start from the beginning
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(1)
            
            # Take screenshot with full page
            await page.screenshot(path=screenshot_path, full_page=True, timeout=30000)
            logger.debug(f"Screenshot captured for {detail_url}")
            return True
        except Exception as e:
            logger.error(f"Error capturing screenshot for {detail_url}: {str(e)}")
            return False
        finally:
            if page:
                await page.close()
    
    async def capture_all_screenshots_async(self, db):
        """Phase 2: Capture screenshots for all vehicles in parallel."""
        # Get all vehicles without screenshots
        vehicles = db.get_vehicles_without_screenshots()
        
        if not vehicles:
            logger.info("No vehicles need screenshots. Phase 2 skipped.")
            return
        
        logger.info(f"Phase 2: Capturing screenshots for {len(vehicles)} vehicles...")
        
        # Set up async browser
        await self._setup_async_browser()
        
        # Process in batches
        total_processed = 0
        for batch_start in range(0, len(vehicles), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(vehicles))
            batch = vehicles[batch_start:batch_end]
            
            logger.info(f"Processing screenshot batch {batch_start//self.batch_size + 1}: vehicles {batch_start + 1}-{batch_end} of {len(vehicles)}")
            
            tasks = []
            for vehicle in batch:
                if vehicle.get('detail_url'):
                    screenshot_path = self._generate_screenshot_path(vehicle)
                    # Assign context round-robin
                    context = self.async_contexts[vehicle['id'] % len(self.async_contexts)]
                    task = self._capture_screenshot_batch_async(
                        context, vehicle['detail_url'], screenshot_path
                    )
                    tasks.append((task, vehicle, screenshot_path))
                else:
                    logger.warning(f"Vehicle {vehicle.get('id')} has no detail_url, skipping screenshot")
            
            # Run all screenshot tasks in parallel
            results = await asyncio.gather(*[t[0] for t in tasks], return_exceptions=True)
            
            # Update database with screenshot paths
            for (task, vehicle, screenshot_path), result in zip(tasks, results):
                try:
                    if isinstance(result, Exception):
                        logger.error(f"Error in screenshot task for vehicle {vehicle.get('id')}: {str(result)}")
                        continue
                    
                    if result:
                        db.update_vehicle_screenshot(vehicle['id'], screenshot_path)
                        total_processed += 1
                        if total_processed % 10 == 0:
                            logger.info(f"Captured {total_processed}/{len(vehicles)} screenshots...")
                    else:
                        logger.warning(f"Failed to capture screenshot for vehicle {vehicle.get('id')}")
                except Exception as e:
                    logger.error(f"Error updating screenshot for vehicle {vehicle.get('id')}: {str(e)}")
            
            # Longer delay between batches to avoid detection
            if batch_end < len(vehicles):
                batch_delay = self.delay_between_batches + random.uniform(self.random_delay_min, self.random_delay_max)
                logger.info(f"Waiting {batch_delay:.1f} seconds before next screenshot batch to avoid detection...")
                await asyncio.sleep(batch_delay)
        
        logger.info(f"Phase 2 complete: Captured {total_processed}/{len(vehicles)} screenshots")
    
    def _generate_all_combinations(self) -> List[Dict]:
        """
        Generate all (city, date) combinations for parallel processing.
        
        Returns:
            List of dicts with 'city' and 'return_date' keys
        """
        combinations = []
        cities = self.config['cities']
        dates = self._calculate_dates()
        pickup_date = dates['pickup']
        return_dates = dates['returns']
        
        for city in cities:
            for return_date in return_dates:
                combinations.append({
                    'city': city,
                    'pickup_date': pickup_date,
                    'return_date': return_date
                })
        
        return combinations
    
    async def _collect_vehicle_data_worker_async(self, context: AsyncBrowserContext,
                                                 city: Dict, pickup_date: datetime, return_date: datetime,
                                                 scrape_datetime: str, db) -> List[Dict]:
        """
        Worker function to collect vehicle data for a single (city, date) combination.
        Used for Phase 1 parallel processing.
        """
        page = None
        vehicles_collected = []
        city_name = city['name']
        
        try:
            page = await context.new_page()
            
            # Build results URL
            results_url = self._build_results_url_async(city, pickup_date, return_date)
            
            # Add random delay before navigating to avoid detection
            pre_navigation_delay = random.uniform(self.random_delay_min, self.random_delay_max)
            await asyncio.sleep(pre_navigation_delay)
            
            # Navigate to results page - wait for DOM first
            logger.debug(f"[Worker] Navigating to {city_name} results page...")
            await page.goto(results_url, wait_until="domcontentloaded", timeout=20000)
            
            # Wait for DOM to be ready
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except:
                logger.warning(f"[Worker] DOM load timeout for {city_name}, continuing...")
            
            # Wait for network to be mostly idle (but don't wait too long)
            logger.debug(f"[Worker] Waiting for network idle for {city_name}...")
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
                logger.debug(f"[Worker] Network idle reached for {city_name}")
            except:
                logger.debug(f"[Worker] Network idle timeout for {city_name} (continuing anyway)")
            
            # Reduced wait - networkidle already ensures content is loaded
            await asyncio.sleep(1)  # Reduced from 3+2=5 seconds to 1 second
            
            # Wait for vehicle-related content to appear (this is the important check)
            logger.debug(f"[Worker] Waiting for vehicle content to appear for {city_name}...")
            vehicle_selectors = [
                "[class*='vehicle']",
                "[class*='car']",
                "button:has-text('See Details')",
                "a:has-text('See Details')",
                "[data-testid*='vehicle']",
                "[data-testid*='car']",
            ]
            
            content_found = False
            for selector in vehicle_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=10000, state="visible")
                    elements = await page.query_selector_all(selector)
                    if elements and len(elements) > 0:
                        logger.debug(f"[Worker] Found {len(elements)} elements with selector '{selector}' for {city_name}")
                        content_found = True
                        break
                except:
                    continue
            
            if not content_found:
                logger.warning(f"[Worker] No vehicle content found immediately for {city_name}, waiting more...")
                await asyncio.sleep(2)  # Reduced from 3 seconds
            
            # Reduced wait - selector check already ensures content is there
            await asyncio.sleep(1)  # Reduced from 2 seconds
            
            # Quick content verification (non-blocking check)
            try:
                body_text = await page.evaluate("() => document.body.innerText")
                if len(body_text) < 100:
                    logger.warning(f"[Worker] Page content seems minimal ({len(body_text)} chars) for {city_name}, waiting more...")
                    await asyncio.sleep(2)  # Reduced from 3 seconds
            except:
                pass
            
            # Extract vehicle listings
            logger.debug(f"[Worker] Extracting vehicle listings for {city_name}...")
            vehicles = await self._get_vehicle_listings_async(page)
            
            if not vehicles:
                logger.warning(f"[Worker] No vehicles found for {city_name} ({pickup_date.date()} to {return_date.date()})")
                return vehicles_collected
            
            logger.info(f"[Worker] Found {len(vehicles)} vehicles for {city_name} ({pickup_date.date()} to {return_date.date()})")
            
            # Delete existing records for this combination to prevent duplicates
            with self.db_lock:
                deleted_count = db.delete_vehicles_for_combination(
                    scrape_datetime, city_name, 
                    pickup_date.isoformat(), return_date.isoformat()
                )
                if deleted_count > 0:
                    logger.debug(f"[Worker] Deleted {deleted_count} existing records for {city_name} ({pickup_date.date()} to {return_date.date()})")
            
            # Take screenshot of results page (before saving vehicles)
            # Page is already fully loaded after vehicle extraction, so no extra waits needed
            screenshot_path = None
            if self.screenshot_enabled:
                try:
                    # Scroll to top (no wait needed - page is already loaded)
                    await page.evaluate("window.scrollTo(0, 0)")
                    
                    # Generate screenshot path for this city-date combination
                    screenshot_path = self._generate_results_screenshot_path(
                        city_name, pickup_date, return_date, scrape_datetime
                    )
                    
                    # Take full page screenshot (page is already fully loaded)
                    await page.screenshot(path=screenshot_path, full_page=True, timeout=30000)
                    
                    # Compress and upload to get R2 URL before saving vehicles
                    # This ensures screenshot_path in database is the R2 URL, not local path
                    # Run in thread pool to avoid blocking async event loop, but wait for completion
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        def compress_and_upload():
                            try:
                                # Compress screenshot first
                                success, compressed_path = self._compress_screenshot(screenshot_path)
                                final_path = compressed_path if success else screenshot_path
                                
                                # Upload to cloud storage if enabled
                                if self.use_cloud_storage and self.cloud_storage:
                                    try:
                                        # Generate remote path (same structure as local)
                                        remote_path = final_path.replace(str(self.screenshot_dir), '').lstrip('/')
                                        cloud_url = self.cloud_storage.upload_file(
                                            final_path,
                                            remote_path,
                                            content_type='image/jpeg' if final_path.endswith('.jpg') else 'image/png'
                                        )
                                        
                                        if cloud_url:
                                            # Delete local file after successful upload
                                            try:
                                                os.remove(final_path)
                                            except:
                                                pass
                                            return cloud_url
                                        else:
                                            logger.warning(f"[Worker] Cloud upload succeeded but no URL returned for {city_name}")
                                            return final_path
                                    except Exception as e:
                                        logger.warning(f"[Worker] Failed to upload to cloud storage: {str(e)}")
                                        return final_path
                                elif success and compressed_path != screenshot_path:
                                    # No cloud storage, but compression happened - use compressed path
                                    return compressed_path
                                else:
                                    return screenshot_path
                            except Exception as e:
                                logger.warning(f"[Worker] Error compressing/uploading screenshot for {city_name}: {str(e)}")
                                return screenshot_path
                        
                        # Wait for compression/upload to complete (with timeout)
                        future = executor.submit(compress_and_upload)
                        try:
                            screenshot_path = future.result(timeout=60)  # 60 second timeout
                            if self.use_cloud_storage and screenshot_path.startswith('http'):
                                logger.info(f"[Worker] Uploaded screenshot to R2: {screenshot_path}")
                        except concurrent.futures.TimeoutError:
                            logger.error(f"[Worker] Timeout compressing/uploading screenshot for {city_name}")
                            # Keep original path if timeout
                        except Exception as e:
                            logger.error(f"[Worker] Error in compression/upload thread: {str(e)}")
                            # Keep original path if error
                    
                    logger.info(f"[Worker] Captured results page screenshot for {city_name} ({pickup_date.date()} to {return_date.date()})")
                except Exception as e:
                    logger.error(f"[Worker] Error capturing screenshot for {city_name}: {str(e)}")
                    screenshot_path = None
            
            # Save vehicles to database (thread-safe) - all share the same screenshot path
            for vehicle in vehicles:
                try:
                    vehicle_data = {
                        'scrape_datetime': scrape_datetime,
                        'city': city_name,
                        'pickup_date': pickup_date.isoformat(),
                        'return_date': return_date.isoformat(),
                        'vehicle_name': vehicle.get('vehicle_name'),
                        'vehicle_type': vehicle.get('vehicle_type'),
                        'seats': vehicle.get('seats'),
                        'doors': vehicle.get('doors'),
                        'transmission': vehicle.get('transmission'),
                        'excess': vehicle.get('excess'),
                        'fuel_type': vehicle.get('fuel_type'),
                        'logo_url': vehicle.get('logo_url'),
                        'price_per_day': vehicle.get('price_per_day'),
                        'total_price': vehicle.get('total_price'),
                        'currency': 'AUD',
                        'detail_url': vehicle.get('detail_url'),
                        'screenshot_path': screenshot_path,  # All vehicles from same combination share screenshot
                    }
                    
                    with self.db_lock:
                        vehicle_id = db.insert_vehicle(vehicle_data)
                        vehicle_data['id'] = vehicle_id
                    
                    vehicles_collected.append(vehicle_data)
                except Exception as e:
                    logger.error(f"[Worker] Error saving vehicle for {city_name}: {str(e)}")
                    continue
            
            return vehicles_collected
            
        except Exception as e:
            logger.error(f"[Worker] Error collecting data for {city_name} ({pickup_date.date()} to {return_date.date()}): {str(e)}")
            return vehicles_collected
        finally:
            if page:
                await page.close()
    
    def _build_results_url_async(self, city: Dict, pickup_date: datetime, return_date: datetime) -> str:
        """Build the results URL (same as sync version but for async context)."""
        from urllib.parse import quote
        
        pickup_date_str = self._format_date_for_url(pickup_date)
        pickup_time_str = self._format_time_for_url(pickup_date)
        return_date_str = self._format_date_for_url(return_date)
        return_time_str = self._format_time_for_url(return_date)
        
        lat = city['latitude']
        lng = city['longitude']
        location = city['location_string']
        radius = city.get('radius', 3)
        
        location_encoded = quote(location, safe=',')
        
        url = (
            f"{self.results_base_url}/"
            f"{pickup_date_str}/{pickup_time_str}/"
            f"{return_date_str}/{return_time_str}/"
            f"{lat},{lng},2/{lat},{lng},2/"
            f"{location_encoded}/{location_encoded}/"
            f"AU/30?radius={radius}&pickupCountry=AU&returnCountry=AU&bookingEngine=ube&affiliateCode=drivenow"
        )
        
        return url
    
    def _parse_vehicle_details(self, vehicle_text: str) -> Dict[str, any]:
        """
        Parse vehicle name text into structured fields.
        
        Example input:
        "BYD Atto 3 or similar\n\nElectric\n\nIntermediate SUV\n\n5 seats\n\n5 doors\n\n1 Large, 2 Small\n\nAutomatic\n\nAUD $6,050 excess"
        
        Returns:
            Dictionary with parsed vehicle details
        """
        import re
        
        details = {
            'vehicle_model': None,
            'vehicle_type': None,
            'vehicle_category': None,
            'seats': None,
            'doors': None,
            'luggage': None,
            'transmission': None,
            'excess': None,
        }
        
        if not vehicle_text:
            return details
        
        # Split by newlines and clean up
        lines = [line.strip() for line in vehicle_text.split('\n') if line.strip()]
        
        if not lines:
            return details
        
        # First line is usually the vehicle model/name
        details['vehicle_model'] = lines[0] if lines else None
        
        # Common patterns to look for
        for i, line in enumerate(lines):
            line_lower = line.lower()
            
            # Vehicle type (Electric, Petrol, Diesel, Hybrid, etc.)
            if not details['vehicle_type']:
                vehicle_types = ['electric', 'petrol', 'diesel', 'hybrid', 'plug-in hybrid', 'lpg', 'cng']
                if any(vt in line_lower for vt in vehicle_types):
                    details['vehicle_type'] = line
                    continue
            
            # Vehicle category (Economy, Intermediate, SUV, etc.)
            if not details['vehicle_category']:
                categories = ['economy', 'compact', 'intermediate', 'standard', 'full size', 'premium', 
                             'luxury', 'suv', 'van', 'pickup', 'convertible', 'wagon', 'hatchback', 'sedan']
                if any(cat in line_lower for cat in categories):
                    details['vehicle_category'] = line
                    continue
            
            # Seats
            if not details['seats']:
                seats_match = re.search(r'(\d+)\s*seat', line_lower)
                if seats_match:
                    try:
                        details['seats'] = int(seats_match.group(1))
                    except:
                        pass
                    continue
            
            # Doors
            if not details['doors']:
                doors_match = re.search(r'(\d+)\s*door', line_lower)
                if doors_match:
                    try:
                        details['doors'] = int(doors_match.group(1))
                    except:
                        pass
                    continue
            
            # Luggage
            if not details['luggage']:
                if 'luggage' in line_lower or 'bag' in line_lower or ('large' in line_lower and 'small' in line_lower):
                    details['luggage'] = line
                    continue
            
            # Transmission
            if not details['transmission']:
                transmissions = ['automatic', 'manual', 'cvt', 'semi-automatic']
                if any(trans in line_lower for trans in transmissions):
                    details['transmission'] = line
                    continue
            
            # Excess
            if not details['excess']:
                if 'excess' in line_lower:
                    details['excess'] = line
                    continue
        
        return details
    
    async def _extract_vehicle_details_from_element_async(self, element) -> Dict[str, any]:
        """
        Extract only the specified fields from the element using exact class names.
        
        Returns:
            Dictionary with vehicle_name, fuel_type, vehicle_type, seats, doors, 
            transmission, excess, price_per_day, total_price, logo_url
        """
        details = {
            'vehicle_name': None,
            'fuel_type': None,
            'vehicle_type': None,
            'seats': None,
            'doors': None,
            'transmission': None,
            'excess': None,
            'price_per_day': None,
            'total_price': None,
            'logo_url': None,
        }
        
        # Extract vehicle name from fuel-type-tag--container
        try:
            name_elem = await element.query_selector(".fuel-type-tag--container")
            if name_elem:
                name_text = (await name_elem.inner_text()).strip()
                if name_text:
                    details['vehicle_name'] = name_text
        except:
            pass
        
        # Extract fuel type from fuel-type-tag
        try:
            fuel_elem = await element.query_selector(".fuel-type-tag")
            if fuel_elem:
                fuel_text = (await fuel_elem.inner_text()).strip()
                if fuel_text:
                    details['fuel_type'] = fuel_text
        except:
            pass
        
        # Extract vehicle type from vehicle-type
        try:
            cat_elem = await element.query_selector(".vehicle-type")
            if cat_elem:
                cat_text = (await cat_elem.inner_text()).strip()
                if cat_text:
                    details['vehicle_type'] = cat_text
        except:
            pass
        
        # Extract features from feature-item elements (by index)
        try:
            feature_items = await element.query_selector_all(".feature-item")
            
            # First feature-item (index 0) -> seats
            if len(feature_items) > 0:
                try:
                    seats_text = (await feature_items[0].inner_text()).strip()
                    if seats_text:
                        details['seats'] = seats_text
                except:
                    pass
            
            # Second feature-item (index 1) -> doors
            if len(feature_items) > 1:
                try:
                    doors_text = (await feature_items[1].inner_text()).strip()
                    if doors_text:
                        details['doors'] = doors_text
                except:
                    pass
            
            # Fourth feature-item (index 3) -> transmission
            if len(feature_items) > 3:
                try:
                    transmission_text = (await feature_items[3].inner_text()).strip()
                    if transmission_text:
                        details['transmission'] = transmission_text
                except:
                    pass
            
            # Fifth feature-item (index 4) -> excess
            if len(feature_items) > 4:
                try:
                    excess_text = (await feature_items[4].inner_text()).strip()
                    if excess_text:
                        details['excess'] = excess_text
                except:
                    pass
        except:
            pass
        
        # Extract total price from total-price-number
        try:
            total_price_elem = await element.query_selector(".total-price-number")
            if total_price_elem:
                total_price_text = (await total_price_elem.inner_text()).strip()
                if total_price_text:
                    details['total_price'] = total_price_text
        except:
            pass
        
        # Extract price per day from perdayprice
        try:
            perday_elem = await element.query_selector(".perdayprice")
            if perday_elem:
                perday_text = (await perday_elem.inner_text()).strip()
                if perday_text:
                    details['price_per_day'] = perday_text
        except:
            pass
        
        # Extract logo URL from first img-responsive
        try:
            imgs = await element.query_selector_all(".img-responsive")
            if imgs and len(imgs) > 0:
                logo_src = await imgs[0].get_attribute('src')
                if logo_src:
                    details['logo_url'] = logo_src
        except:
            pass
        
        return details
    
    
    
    async def _get_vehicle_listings_async(self, page: AsyncPage) -> List[Dict]:
        """
        Extract vehicle listings from the results page (async version).
        Returns list of vehicle info with detail URLs/links.
        """
        vehicles = []
        
        try:
            # Wait for vehicle listings to appear - exact class only
            # Reduced initial wait since page is already loaded
            await asyncio.sleep(1)  # Reduced from 2 seconds
            
            vehicle_selectors_to_wait = [
                ".veh-list-container",
            ]
            
            element_found = False
            for selector in vehicle_selectors_to_wait:
                try:
                    await page.wait_for_selector(selector, timeout=10000, state="visible")
                    elements = await page.query_selector_all(selector)
                    if elements and len(elements) > 0:
                        logger.debug(f"[Async] Found {len(elements)} elements waiting for selector: {selector}")
                        element_found = True
                        break
                except:
                    continue
            
            if not element_found:
                logger.warning("[Async] No vehicle elements found after initial wait, waiting more...")
                await asyncio.sleep(2)  # Reduced from 3 seconds
            
            # Reduced wait - selector check already ensures content is there
            await asyncio.sleep(1)  # Reduced from 2 seconds
            
            # Quick content check (non-blocking)
            try:
                body_text = await page.evaluate("() => document.body.innerText")
                if len(body_text) < 200:
                    logger.warning(f"[Async] Page content seems minimal ({len(body_text)} chars), waiting more...")
                    await asyncio.sleep(2)  # Reduced from 3 seconds
            except:
                pass
            
            # Scroll to trigger lazy loading - vehicles might load as you scroll
            logger.debug("[Async] Scrolling page to trigger lazy loading...")
            try:
                # Wait for network to be idle first
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except:
                    pass
                
                # Scroll gradually to bottom to load all vehicles
                scroll_height = await page.evaluate("document.body.scrollHeight")
                scroll_step = 800  # Increased from 500 to scroll faster
                current_scroll = 0
                
                while current_scroll < scroll_height:
                    current_scroll += scroll_step
                    await page.evaluate(f"window.scrollTo(0, {current_scroll})")
                    await asyncio.sleep(0.3)  # Reduced from 0.5 seconds
                    
                    # Check if page height increased (new content loaded)
                    new_height = await page.evaluate("document.body.scrollHeight")
                    if new_height > scroll_height:
                        scroll_height = new_height
                
                # Final scroll to absolute bottom
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2)  # Reduced from 3 seconds
                
                # Wait for network idle after scrolling (shorter timeout)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)  # Reduced from 10000
                except:
                    pass
                
                await asyncio.sleep(1)  # Reduced from 2 seconds
                
                # Scroll back to top (no wait needed)
                await page.evaluate("window.scrollTo(0, 0)")
            except:
                pass
            
            # Wait for vehicle listings to appear - use exact class name only
            vehicle_selectors = [
                ".veh-list-container",  # Exact class from table structure
            ]
            
            vehicle_elements = []
            max_elements = 0
            best_selector = None
            
            # Try all selectors and use the one that finds the most elements
            for selector in vehicle_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    if elements and len(elements) > max_elements:
                        max_elements = len(elements)
                        vehicle_elements = elements
                        best_selector = selector
                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {str(e)}")
                    continue
            
            if vehicle_elements:
                logger.info(f"[Async] Found {len(vehicle_elements)} vehicle elements using selector: {best_selector}")
                
                # Check for "Load More" or pagination buttons
                load_more_selectors = [
                    "button:has-text('Load More')",
                    "button:has-text('Show More')",
                    "button:has-text('View More')",
                    "a:has-text('Load More')",
                    "a:has-text('Show More')",
                    "[class*='load-more']",
                    "[class*='show-more']",
                ]
                
                # Try to click "Load More" buttons multiple times
                for load_more_attempt in range(20):  # Try up to 20 times
                    load_more_clicked = False
                    for selector in load_more_selectors:
                        try:
                            load_more_btn = await page.query_selector(selector)
                            if load_more_btn:
                                # Check if button is visible
                                is_visible = await load_more_btn.is_visible()
                                if is_visible:
                                    await load_more_btn.click()
                                    await asyncio.sleep(2)  # Reduced from 3 seconds
                                    
                                    # Wait for network idle after clicking (shorter timeout)
                                    try:
                                        await page.wait_for_load_state("networkidle", timeout=5000)  # Reduced from 10000
                                    except:
                                        pass
                                    
                                    await asyncio.sleep(1)  # Reduced from 2 seconds
                                    load_more_clicked = True
                                    logger.info(f"[Async] Clicked 'Load More' button (attempt {load_more_attempt + 1})")
                                    break
                        except:
                            continue
                    
                    if not load_more_clicked:
                        break  # No more "Load More" buttons found
                    
                    # Re-check vehicle count after clicking
                    elements = await page.query_selector_all(".veh-list-container")
                    if elements:
                        vehicle_elements = elements
                        logger.info(f"[Async] Vehicle count after Load More: {len(elements)}")
                
                # If we found some vehicles, scroll again and check if more appear (lazy loading)
                previous_count = len(vehicle_elements)
                max_scroll_attempts = 15  # Increase scroll attempts
                no_change_count = 0
                
                for scroll_attempt in range(max_scroll_attempts):
                    # Scroll gradually in increments
                    scroll_height = await page.evaluate("document.body.scrollHeight")
                    scroll_step = 800  # Scroll in 800px increments
                    current_scroll = 0
                    
                    while current_scroll < scroll_height:
                        current_scroll += scroll_step
                        await page.evaluate(f"window.scrollTo(0, {current_scroll})")
                        await asyncio.sleep(0.5)  # Reduced from 0.8 seconds
                        
                        # Check if page height increased
                        new_height = await page.evaluate("document.body.scrollHeight")
                        if new_height > scroll_height:
                            scroll_height = new_height
                    
                    # Final scroll to absolute bottom
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2)  # Reduced from 3 seconds
                    
                    # Wait for network idle (shorter timeout)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)  # Reduced from 8000
                    except:
                        pass
                    
                    await asyncio.sleep(1)  # Reduced from 2 seconds
                    
                    # Re-check vehicle count - use exact selector
                    try:
                        elements = await page.query_selector_all(".veh-list-container")
                        if elements and len(elements) > previous_count:
                            vehicle_elements = elements
                            previous_count = len(elements)
                            no_change_count = 0  # Reset counter
                            logger.info(f"[Async] Found more vehicles after scroll ({len(elements)} total)")
                        else:
                            no_change_count += 1
                    except:
                        no_change_count += 1
                    
                    # If no new vehicles found after 3 consecutive scrolls, stop
                    if no_change_count >= 3:
                        logger.info(f"[Async] No new vehicles found after {no_change_count} scroll attempts, stopping")
                        break
                
                # Final wait to ensure all content is loaded (reduced)
                await asyncio.sleep(1)  # Reduced from 3 seconds
                
                # Wait for network idle one more time (shorter timeout)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)  # Reduced from 10000
                except:
                    pass
                
                # Final check of vehicle count
                elements = await page.query_selector_all(".veh-list-container")
                if elements:
                    vehicle_elements = elements
                    logger.info(f"[Async] Final vehicle count: {len(vehicle_elements)}")
                
                # Scroll back to top (no wait needed)
                await page.evaluate("window.scrollTo(0, 0)")
            else:
                logger.warning("[Async] No vehicle elements found with any selector")
            
            # First, try to find ALL "See Details" buttons on the page directly
            all_detail_buttons = []
            detail_selectors = [
                "a:has-text('See Details')",
                "button:has-text('See Details')",
                "a:has-text('Details')",
                "button:has-text('Details')",
                "a[class*='details']",
                "button[class*='details']",
                "a[class*='detail']",
                "button[class*='detail']",
            ]
            
            for selector in detail_selectors:
                try:
                    buttons = await page.query_selector_all(selector)
                    if buttons and len(buttons) > len(all_detail_buttons):
                        all_detail_buttons = buttons
                        logger.debug(f"[Async] Found {len(buttons)} detail buttons using: {selector}")
                except:
                    continue
            
            # Process ALL vehicle elements - the container itself might have an href
            logger.info(f"[Async] Processing {len(vehicle_elements)} vehicle elements...")
            
            for idx, element in enumerate(vehicle_elements):
                see_details_button = None
                detail_url = None
                
                # First, check if the container itself has an href (veh-list-container href)
                try:
                    container_href = await element.get_attribute('href')
                    if container_href:
                        detail_url = container_href
                        if not detail_url.startswith('http'):
                            from urllib.parse import urljoin
                            current_url = page.url
                            detail_url = urljoin(current_url, detail_url)
                except:
                    pass
                
                # If we found detail buttons, try to match them
                if all_detail_buttons and len(all_detail_buttons) > 0 and not detail_url:
                    # Try to find button within this element first
                    for detail_selector in detail_selectors:
                        try:
                            btn = await element.query_selector(detail_selector)
                            if btn:
                                btn_text = (await btn.inner_text()).lower() if await btn.inner_text() else ""
                                if any(keyword in btn_text for keyword in ['detail', 'see', 'view', 'more', 'info', 'book']):
                                    see_details_button = btn
                                    break
                        except:
                            continue
                    
                    # If not found within element, try matching by index
                    if not see_details_button and idx < len(all_detail_buttons):
                        see_details_button = all_detail_buttons[idx]
                    
                    # If still not found, search for any clickable element in the vehicle card
                    if not see_details_button:
                        try:
                            # Look for any link or button in the element
                            clickables = await element.query_selector_all("a[href], button")
                            for clickable in clickables:
                                try:
                                    text = (await clickable.inner_text()).lower() if await clickable.inner_text() else ""
                                    if any(keyword in text for keyword in ['detail', 'see', 'view', 'more', 'info', 'book', 'select', 'choose']):
                                        see_details_button = clickable
                                        break
                                except:
                                    continue
                        except:
                            pass
                    
                    # Extract URL from button if we found one
                    if see_details_button and not detail_url:
                        try:
                            href = await see_details_button.get_attribute('href')
                            if href:
                                detail_url = href
                                if not detail_url.startswith('http'):
                                    from urllib.parse import urljoin
                                    current_url = page.url
                                    detail_url = urljoin(current_url, detail_url)
                            else:
                                # Try data attributes
                                data_url = await see_details_button.get_attribute('data-url') or \
                                          await see_details_button.get_attribute('data-href') or \
                                          await see_details_button.get_attribute('data-link')
                                if data_url:
                                    detail_url = data_url
                                    if not detail_url.startswith('http'):
                                        from urllib.parse import urljoin
                                        current_url = page.url
                                        detail_url = urljoin(current_url, detail_url)
                        except:
                            pass
                
                # Process this vehicle element regardless of whether we found a button
                # Extract vehicle info
                vehicle_name = None
                price = None
                
                try:
                    # Extract vehicle details using exact class names
                    vehicle_details_parsed = await self._extract_vehicle_details_from_element_async(element)
                except:
                    vehicle_details_parsed = {}
                
                vehicles.append({
                    'index': idx,
                    'detail_url': detail_url,
                    **vehicle_details_parsed,  # Include all parsed details
                })
            
            if vehicles:
                logger.info(f"[Async] Found {len(vehicles)} vehicles total")
                return vehicles
            
            # If we found vehicle elements but no buttons yet, search within them
            if vehicle_elements and len(vehicle_elements) > 0:
                logger.info(f"[Async] Found {len(vehicle_elements)} vehicle elements, searching for buttons within...")
                # Search for buttons within each vehicle element
                for idx, element in enumerate(vehicle_elements):
                    # Skip if we already added this vehicle
                    if any(v.get('index') == idx for v in vehicles):
                        continue
                    
                    # Try to find "See Details" button within this element
                    see_details_button = None
                    detail_selectors = [
                        "button:has-text('See Details')",
                        "a:has-text('See Details')",
                        "button:has-text('Details')",
                        "a:has-text('Details')",
                        "button",
                        "a[href]",
                    ]
                    
                    for selector in detail_selectors:
                        try:
                            btn = await element.query_selector(selector)
                            if btn:
                                btn_text = (await btn.inner_text()).lower() if await btn.inner_text() else ""
                                if any(keyword in btn_text for keyword in ['detail', 'see', 'view', 'more', 'info', 'book']):
                                    see_details_button = btn
                                    break
                                # If it's the only button/link, use it
                                elif selector in ["button", "a[href]"]:
                                    # Check if there are multiple buttons
                                    all_buttons = await element.query_selector_all("button, a[href]")
                                    if len(all_buttons) == 1:
                                        see_details_button = btn
                                        break
                        except:
                            continue
                    
                    if see_details_button:
                        # Extract vehicle info
                        vehicle_name = None
                        price = None
                        detail_url = None
                        
                        try:
                            # Extract vehicle details using exact class names
                            vehicle_details_parsed = await self._extract_vehicle_details_from_element_async(element)
                        except:
                            vehicle_details_parsed = {}
                        
                        # Extract detail URL from button if not already found
                        if not detail_url:
                            try:
                                href = await see_details_button.get_attribute('href')
                                if href:
                                    detail_url = href
                                    if not detail_url.startswith('http'):
                                        from urllib.parse import urljoin
                                        current_url = page.url
                                        detail_url = urljoin(current_url, detail_url)
                            except:
                                pass
                        
                        vehicles.append({
                            'index': idx,
                            'detail_url': detail_url,
                            **vehicle_details_parsed,  # Include all parsed details
                        })
                
                if vehicles:
                    logger.info(f"[Async] Found {len(vehicles)} vehicles with buttons")
                    return vehicles
            
            if not vehicle_elements:
                # Fallback: try to find "See Details" buttons directly
                see_details_selectors = [
                    "button:has-text('See Details')",
                    "a:has-text('See Details')",
                    "button:has-text('Details')",
                    "a:has-text('Details')",
                ]
                
                for selector in see_details_selectors:
                    try:
                        elements = await page.query_selector_all(selector)
                        if elements:
                            logger.info(f"Found {len(elements)} detail buttons using selector: {selector}")
                            for idx, btn in enumerate(elements):
                                vehicles.append({
                                    'index': idx,
                                    'detail_button': btn,
                                    'selector': selector,
                                })
                            return vehicles
                    except:
                        continue
            
            # Find all "See Details" buttons
            all_detail_buttons = []
            detail_selectors = [
                "button:has-text('See Details')",
                "a:has-text('See Details')",
                "button:has-text('Details')",
                "a:has-text('Details')",
                "button[class*='details']",
                "a[class*='details']",
                "button[class*='detail']",
                "a[class*='detail']",
            ]
            
            for selector in detail_selectors:
                try:
                    buttons = await page.query_selector_all(selector)
                    if buttons:
                        all_detail_buttons = buttons
                        logger.debug(f"Found {len(buttons)} detail buttons using selector: {selector}")
                        break
                except:
                    continue
            
            # Match buttons to vehicle elements
            if all_detail_buttons and len(all_detail_buttons) > 0:
                for idx, element in enumerate(vehicle_elements):
                    if idx < len(all_detail_buttons):
                        see_details_button = all_detail_buttons[idx]
                    else:
                        see_details_button = None
                        for selector in detail_selectors:
                            try:
                                btn = await element.query_selector(selector)
                                if btn:
                                    see_details_button = btn
                                    break
                            except:
                                continue
                    
                    if see_details_button:
                        # Extract vehicle info
                        vehicle_name = None
                        price = None
                        detail_url = None
                        
                        try:
                            # Extract vehicle details using exact class names
                            vehicle_details_parsed = await self._extract_vehicle_details_from_element_async(element)
                        except:
                            vehicle_details_parsed = {}
                        
                        # Extract detail URL from button if not already found
                        if not detail_url:
                            try:
                                href = await see_details_button.get_attribute('href')
                                if href:
                                    detail_url = href
                                    if not detail_url.startswith('http'):
                                        from urllib.parse import urljoin
                                        current_url = page.url
                                        detail_url = urljoin(current_url, detail_url)
                                else:
                                    # Try onclick handler
                                    onclick = await see_details_button.get_attribute('onclick')
                                    if onclick:
                                        import re
                                        match = re.search(r'["\']([^"\']+)["\']', onclick)
                                        if match:
                                            detail_url = match.group(1)
                                    
                                    # Try data attributes
                                    if not detail_url:
                                        data_url = await see_details_button.get_attribute('data-url') or \
                                                  await see_details_button.get_attribute('data-href') or \
                                                  await see_details_button.get_attribute('data-link')
                                        if data_url:
                                            detail_url = data_url
                                            if not detail_url.startswith('http'):
                                                from urllib.parse import urljoin
                                                current_url = page.url
                                                detail_url = urljoin(current_url, detail_url)
                            except:
                                pass
                        
                        vehicles.append({
                            'index': idx,
                            'detail_url': detail_url,
                            **vehicle_details_parsed,  # Include all parsed details
                        })
                
                if vehicles:
                    logger.debug(f"Found {len(vehicles)} vehicles with 'See Details' buttons")
                    return vehicles
            
            # Fallback: try to find buttons within each element
            for idx, element in enumerate(vehicle_elements):
                try:
                    see_details_button = None
                    for detail_selector in detail_selectors:
                        try:
                            btn = await element.query_selector(detail_selector)
                            if btn:
                                btn_text = (await btn.inner_text()).lower()
                                if any(keyword in btn_text for keyword in ['detail', 'see', 'view', 'more', 'info']):
                                    see_details_button = btn
                                    break
                        except:
                            continue
                    
                    if see_details_button:
                        # Extract vehicle info
                        vehicle_name = None
                        price = None
                        detail_url = None
                        
                        try:
                            # Extract vehicle details using exact class names
                            vehicle_details_parsed = await self._extract_vehicle_details_from_element_async(element)
                        except:
                            vehicle_details_parsed = {}
                        
                        # Extract detail URL from button if not already found
                        if not detail_url:
                            try:
                                href = await see_details_button.get_attribute('href')
                                if href:
                                    detail_url = href
                                    if not detail_url.startswith('http'):
                                        from urllib.parse import urljoin
                                        current_url = page.url
                                        detail_url = urljoin(current_url, detail_url)
                            except:
                                pass
                        
                        vehicles.append({
                            'index': idx,
                            'detail_url': detail_url,
                            **vehicle_details_parsed,  # Include all parsed details
                        })
                except Exception as e:
                    logger.warning(f"Error processing vehicle {idx}: {str(e)}")
                    continue
            
            logger.debug(f"Found {len(vehicles)} vehicles with 'See Details' buttons")
            return vehicles
            
        except Exception as e:
            logger.error(f"Error extracting vehicle listings: {str(e)}")
            return []
    
    async def _collect_all_vehicles_parallel_async(self, db):
        """Collect all vehicle data and capture results page screenshots in parallel using flat parallelization."""
        # Generate all (city, date) combinations
        combinations = self._generate_all_combinations()
        logger.info(f"Processing {len(combinations)} (city, date) combinations in parallel (with screenshots)...")
        
        # Set up async browser with Phase 1 workers
        await self._setup_async_browser(num_workers=self.phase1_workers)
        
        scrape_datetime = datetime.now().isoformat()
        
        # Process in batches
        total_collected = 0
        for batch_start in range(0, len(combinations), self.phase1_workers):
            batch_end = min(batch_start + self.phase1_workers, len(combinations))
            batch = combinations[batch_start:batch_end]
            
            logger.info(f"Processing batch {batch_start//self.phase1_workers + 1}: combinations {batch_start + 1}-{batch_end} of {len(combinations)}")
            
            # Create tasks for all combinations in batch
            tasks = []
            for combo in batch:
                context = self.async_contexts[combo['city']['name'].__hash__() % len(self.async_contexts)]
                task = self._collect_vehicle_data_worker_async(
                    context, combo['city'], combo['pickup_date'], combo['return_date'],
                    scrape_datetime, db
                )
                tasks.append((task, combo))
            
            # Run all tasks concurrently (but with staggered start to avoid simultaneous requests)
            # Stagger the start of tasks slightly to avoid all hitting the server at once
            async def create_staggered_task(task, idx):
                # Stagger each task by a small random delay (0-2 seconds per task)
                start_delay = random.uniform(0, 2.0) * idx
                await asyncio.sleep(start_delay)
                return await task
            
            staggered_tasks = [create_staggered_task(task, idx) for idx, (task, combo) in enumerate(tasks)]
            results = await asyncio.gather(*staggered_tasks, return_exceptions=True)
            
            # Count collected vehicles
            for (task, combo), result in zip(tasks, results):
                try:
                    if isinstance(result, Exception):
                        logger.error(f"Error in task for {combo['city']['name']}: {str(result)}")
                        continue
                    
                    if result:
                        count = len(result)
                        total_collected += count
                        if count > 0:
                            logger.info(f"✓ {combo['city']['name']} ({combo['pickup_date'].date()} to {combo['return_date'].date()}): {count} vehicles")
                        
                        # Add delay after each successful combination to avoid detection
                        post_combo_delay = random.uniform(self.random_delay_min, self.random_delay_max)
                        await asyncio.sleep(post_combo_delay)
                except Exception as e:
                    logger.error(f"Error processing result: {str(e)}")
            
            # Longer delay between batches to avoid detection
            if batch_end < len(combinations):
                batch_delay = self.delay_between_batches + random.uniform(self.random_delay_min, self.random_delay_max)
                logger.info(f"Waiting {batch_delay:.1f} seconds before next batch to avoid detection...")
                await asyncio.sleep(batch_delay)
        
        logger.info(f"Collection complete: Collected {total_collected} vehicles total")
    
    def scrape_all(self, db) -> Dict[str, List[Dict]]:
        """
        Scrape all configured cities (single phase).
        Collects vehicle data and captures results page screenshots in parallel.
        """
        logger.info("="*60)
        logger.info("Collecting vehicle data and capturing results page screenshots...")
        logger.info("="*60)
        
        # Run collection in separate thread with event loop
        def run_collection():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                new_loop.run_until_complete(self._collect_all_vehicles_parallel_async(db))
            finally:
                new_loop.close()
        
        collection_thread = threading.Thread(target=run_collection, daemon=False)
        collection_thread.start()
        collection_thread.join()
        
        # Close async browser after collection
        try:
            if self.async_contexts or self.async_browser:
                def close_browser():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        new_loop.run_until_complete(self._close_async())
                    finally:
                        new_loop.close()
                close_thread = threading.Thread(target=close_browser, daemon=False)
                close_thread.start()
                close_thread.join(timeout=5)
        except:
            pass
        
        logger.info("="*60)
        logger.info("Collection complete!")
        logger.info("="*60)
        
        # Return summary (vehicles are already in database)
        return {}
    
    async def _close_async(self):
        """Close async browser and contexts (fast, non-blocking)."""
        # Close all async contexts in parallel with timeout
        if self.async_contexts:
            close_tasks = []
            for context in self.async_contexts:
                async def close_context(ctx):
                    try:
                        await asyncio.wait_for(ctx.close(), timeout=2.0)
                    except (Exception, asyncio.TimeoutError):
                        pass  # Ignore errors/timeouts for faster cleanup
                close_tasks.append(close_context(context))
            
            # Close all contexts in parallel with short timeout
            try:
                await asyncio.wait_for(asyncio.gather(*close_tasks, return_exceptions=True), timeout=3.0)
            except asyncio.TimeoutError:
                pass  # Continue even if some contexts don't close in time
        
        # Close async browser with timeout
        if self.async_browser:
            try:
                await asyncio.wait_for(self.async_browser.close(), timeout=2.0)
            except (Exception, asyncio.TimeoutError):
                pass  # Ignore errors/timeouts for faster cleanup
        
        # Stop async playwright with timeout
        if self.async_playwright:
            try:
                await asyncio.wait_for(self.async_playwright.stop(), timeout=2.0)
            except (Exception, asyncio.TimeoutError):
                pass  # Ignore errors/timeouts for faster cleanup
        
        # Clear the lists immediately
        self.async_contexts = []
        self.async_browser = None
        self.async_playwright = None
    
    def close(self):
        """Close the browser and cleanup (fast, with timeouts)."""
        logger.info("Closing all browsers and cleaning up...")
        
        # Close all parallel worker contexts (sync) - fast, ignore errors
        for context in self.contexts:
            try:
                context.close()
            except:
                pass
        self.contexts = []
        
        # Close async browser if it exists - with short timeout
        if self.async_contexts or self.async_browser or self.async_playwright:
            try:
                # Always create a new event loop in a thread for async cleanup
                import concurrent.futures
                import threading
                
                def run_close():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        new_loop.run_until_complete(asyncio.wait_for(self._close_async(), timeout=5.0))
                    except (asyncio.TimeoutError, Exception):
                        # Force cleanup on timeout/error
                        self.async_contexts = []
                        self.async_browser = None
                        self.async_playwright = None
                    finally:
                        new_loop.close()
                
                # Run in thread with timeout
                thread = threading.Thread(target=run_close, daemon=True)
                thread.start()
                thread.join(timeout=6.0)  # Max 6 seconds total
                
            except Exception as e:
                logger.debug(f"Error closing async browser: {str(e)}")
                # Force cleanup
                self.async_contexts = []
                self.async_browser = None
                self.async_playwright = None
        
        # Close main page and browser - fast, ignore errors
        if self.page:
            try:
                self.page.close()
            except:
                pass
            self.page = None
        
        if self.browser:
            try:
                self.browser.close()
            except:
                pass
            self.browser = None
        
        if self.playwright:
            try:
                self.playwright.stop()
            except:
                pass
            self.playwright = None
        
        logger.info("Browser cleanup completed")
