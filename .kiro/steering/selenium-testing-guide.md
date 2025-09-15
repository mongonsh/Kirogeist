---
inclusion: fileMatch
fileMatchPattern: "agents.py,app.py,*selenium*,*test*"
---

# Selenium Testing Guidelines for Kirogeist

## Browser Automation Best Practices

### WebDriver Configuration
```python
def make_driver(headless: bool = True):
    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--allow-insecure-localhost")
    opts.add_argument("--window-size=1366,900")
    if headless:
        opts.add_argument("--headless=new")
    
    # Production-specific options
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--no-first-run")
    opts.add_argument("--disable-default-apps")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)
```

### Wait Strategies
Always use explicit waits instead of time.sleep():

```python
# Good - Explicit wait
wait = WebDriverWait(driver, 20)
element = wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

# Better - Custom wait conditions
def page_loaded(driver):
    return driver.execute_script("return document.readyState") == "complete"

wait.until(page_loaded)

# Best - Multiple conditions
wait.until(lambda d: d.find_element(By.TAG_NAME, "body") and 
                    d.execute_script("return document.readyState") == "complete")
```

### Error Detection Patterns
```python
def extract_php_error(html: str, driver=None) -> Tuple[bool, str, str]:
    """
    Extract PHP errors from page content with high accuracy
    Returns: (has_error, error_text, file_path)
    """
    # Check for visible error elements first
    if driver:
        error_elements = driver.find_elements(By.XPATH, 
            "//*[contains(text(), 'Fatal error') or contains(text(), 'Warning') or contains(text(), 'Notice')]")
        for elem in error_elements:
            if elem.is_displayed():
                return True, elem.text, extract_file_path(elem.text)
    
    # Fallback to HTML parsing
    return parse_html_for_errors(html)
```

### Screenshot Best Practices
```python
def fullpage_screenshot(driver, out_path: str):
    """Take full-page screenshot with proper sizing"""
    try:
        # Get full page height
        total_height = driver.execute_script("""
            return Math.max(
                document.body.scrollHeight,
                document.body.offsetHeight,
                document.documentElement.clientHeight,
                document.documentElement.scrollHeight,
                document.documentElement.offsetHeight
            );
        """)
        
        # Set window size to capture full page
        driver.set_window_size(1366, min(total_height, 5000))
        time.sleep(1)  # Allow resize to complete
        
        driver.save_screenshot(out_path)
    except Exception as e:
        # Fallback to viewport screenshot
        driver.save_screenshot(out_path)
```

### Login Automation
```python
def selenium_login(driver, login_url: str, credentials: Dict[str, str]):
    """Robust login automation with error handling"""
    wait = WebDriverWait(driver, 20)
    
    try:
        driver.get(login_url)
        
        # Wait for login form
        username_field = wait.until(
            EC.presence_of_element_located((By.NAME, credentials['username_field']))
        )
        password_field = wait.until(
            EC.presence_of_element_located((By.NAME, credentials['password_field']))
        )
        
        # Clear and fill fields
        username_field.clear()
        username_field.send_keys(credentials['username'])
        
        password_field.clear()
        password_field.send_keys(credentials['password'])
        
        # Submit form
        submit_button = wait.until(
            EC.element_to_be_clickable((By.NAME, credentials.get('submit_field', 'submit')))
        )
        submit_button.click()
        
        # Wait for redirect (login success)
        wait.until(lambda d: d.current_url != login_url)
        
    except TimeoutException:
        raise Exception(f"Login failed: timeout waiting for elements")
    except Exception as e:
        raise Exception(f"Login failed: {str(e)}")
```

### Cookie Management
```python
def transfer_cookies_to_requests(session: requests.Session, driver, base_url: str):
    """Transfer Selenium cookies to requests session for API calls"""
    parsed_url = urlparse(base_url)
    domain = parsed_url.hostname or "localhost"
    
    for cookie in driver.get_cookies():
        session.cookies.set(
            name=cookie['name'],
            value=cookie.get('value', ''),
            domain=cookie.get('domain', domain).lstrip('.'),
            path=cookie.get('path', '/'),
            secure=cookie.get('secure', False)
        )
```

## Error Handling Strategies

### Robust Element Interaction
```python
def safe_click(driver, locator, timeout=10):
    """Safely click element with retry logic"""
    wait = WebDriverWait(driver, timeout)
    
    for attempt in range(3):
        try:
            element = wait.until(EC.element_to_be_clickable(locator))
            element.click()
            return True
        except StaleElementReferenceException:
            if attempt == 2:
                raise
            time.sleep(1)
        except ElementClickInterceptedException:
            # Scroll element into view and retry
            element = driver.find_element(*locator)
            driver.execute_script("arguments[0].scrollIntoView(true);", element)
            time.sleep(0.5)
            element.click()
            return True
    
    return False
```

### Page Load Detection
```python
def wait_for_page_load(driver, timeout=30):
    """Wait for page to fully load including AJAX"""
    wait = WebDriverWait(driver, timeout)
    
    # Wait for document ready
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    
    # Wait for jQuery if present
    try:
        wait.until(lambda d: d.execute_script("return typeof jQuery === 'undefined' || jQuery.active === 0"))
    except:
        pass  # jQuery not present
    
    # Wait for any loading indicators to disappear
    try:
        wait.until(EC.invisibility_of_element_located((By.CLASS_NAME, "loading")))
    except:
        pass  # No loading indicators
```

## Performance Optimization

### Resource Management
```python
class WebDriverManager:
    """Context manager for WebDriver lifecycle"""
    
    def __init__(self, headless=True):
        self.headless = headless
        self.driver = None
    
    def __enter__(self):
        self.driver = make_driver(self.headless)
        return self.driver
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass  # Driver already closed

# Usage
with WebDriverManager(headless=True) as driver:
    driver.get("https://example.com")
    # Driver automatically cleaned up
```

### Parallel Testing Considerations
- Use separate WebDriver instances for concurrent tests
- Implement proper resource cleanup
- Consider memory usage with multiple Chrome instances
- Use thread-safe data structures for shared state

### Docker Environment Setup
```dockerfile
# Ensure proper Chrome setup in containers
RUN apt-get update && apt-get install -y \
    wget gnupg unzip curl xvfb \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update && apt-get install -y google-chrome-stable

# Start virtual display for headless operation
ENV DISPLAY=:99
CMD ["sh", "-c", "Xvfb :99 -screen 0 1024x768x24 & python app.py"]
```

## Testing Patterns

### Test Data Organization
```python
@dataclass
class TestEndpoint:
    url: str
    method: str = "GET"
    expected_status: int = 200
    requires_auth: bool = False
    timeout: int = 30
    
class TestSuite:
    def __init__(self, base_url: str, endpoints: List[TestEndpoint]):
        self.base_url = base_url
        self.endpoints = endpoints
    
    def run_smoke_tests(self) -> List[TestResult]:
        results = []
        with WebDriverManager() as driver:
            for endpoint in self.endpoints:
                result = self.test_endpoint(driver, endpoint)
                results.append(result)
        return results
```

### Error Classification
```python
def classify_error_severity(error_text: str, http_status: int) -> str:
    """Classify error severity for prioritization"""
    if http_status >= 500 or "fatal error" in error_text.lower():
        return "Critical"
    elif http_status == 404 or "undefined function" in error_text.lower():
        return "High"
    elif "undefined array key" in error_text.lower():
        return "Medium"
    elif "deprecated" in error_text.lower():
        return "Low"
    else:
        return "Medium"
```