#!/usr/bin/env python3
"""
Retry failed URL extractions using the exact Selenium/Cloudflare
handling from fmit-crawler/crawler.py.
"""

import glob
import json
import logging
import os
import platform
import re
import subprocess
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium_stealth import stealth
from webdriver_manager.chrome import ChromeDriverManager

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Configuration
FAILED_URLS_FILE = "failed_urls_all_accounts.txt"
OUTPUT_FILE = "retry_results.json"
BATCH_SIZE = 10

CLOUDFLARE_KEYWORDS = [
    "just a moment",
    "checking your browser",
    "please enable cookies",
    "attention required",
    "verify you are human",
    "enable javascript",
]


def get_chrome_version() -> str:
    """Get Chrome version from binary."""
    chrome_bin = os.getenv("CHROME_BIN")
    if not chrome_bin:
        chrome_bin = "google-chrome"
        if os.path.exists("/opt/hostedtoolcache/setup-chrome/chromium"):
            chrome_bin_pattern = "/opt/hostedtoolcache/setup-chrome/chromium/*/x64/chrome"
            matches = glob.glob(chrome_bin_pattern)
            if matches:
                chrome_bin = matches[0]
    
    try:
        result = subprocess.run(
            [chrome_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        version_output = result.stdout.strip()
        logging.info(f"Chrome version output: {version_output}")
        
        match = re.search(r'(\d+\.\d+\.\d+\.\d+)', version_output)
        if match:
            full_version = match.group(1)
            logging.info(f"Detected full Chrome version: {full_version}")
            major_version = full_version.split('.')[0]
            logging.info(f"Detected Chrome version: {major_version}")
            return major_version
        return None
    except Exception as e:
        logging.warning(f"Could not detect Chrome version: {e}")
        return None


def download_chromedriver_for_version(chrome_version: str) -> str:
    """Download ChromeDriver for a specific Chrome version from Chrome for Testing."""
    try:
        system = platform.system().lower()
        if system == "darwin":
            if platform.machine().lower() in ["arm64", "aarch64"]:
                platform_name = "mac-arm64"
            else:
                platform_name = "mac-x64"
        elif system == "linux":
            platform_name = "linux64"
        elif system == "windows":
            platform_name = "win64"
        else:
            platform_name = "linux64"
        
        logging.info(f"Detected platform: {platform_name}")
        
        versions_url = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json"
        response = requests.get(versions_url, timeout=30)
        response.raise_for_status()
        versions_data = response.json()
        
        target_version = None
        for version_info in reversed(versions_data["versions"]):
            version_str = version_info["version"]
            if version_str.startswith(f"{chrome_version}."):
                target_version = version_str
                break
        
        if not target_version:
            logging.warning(f"No ChromeDriver found for Chrome {chrome_version}, trying latest")
            for version_info in reversed(versions_data["versions"]):
                version_str = version_info["version"]
                if version_str.split('.')[0] == chrome_version:
                    target_version = version_str
                    break
        
        if not target_version:
            raise Exception(f"No ChromeDriver found for Chrome version {chrome_version}")
        
        logging.info(f"Found ChromeDriver version: {target_version}")
        
        download_url = None
        for version_info in versions_data["versions"]:
            if version_info["version"] == target_version:
                downloads = version_info.get("downloads", {})
                chromedriver = downloads.get("chromedriver", [])
                for item in chromedriver:
                    if item["platform"] == platform_name:
                        download_url = item["url"]
                        break
                break
        
        if not download_url:
            raise Exception(f"No {platform_name} ChromeDriver download found for version {target_version}")
        
        logging.info(f"Downloading ChromeDriver from {download_url}")
        cache_dir = Path.home() / ".wdm" / "drivers" / "chromedriver" / platform_name / target_version
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        zip_filename = {
            "linux64": "chromedriver-linux64.zip",
            "mac-x64": "chromedriver-mac-x64.zip",
            "mac-arm64": "chromedriver-mac-arm64.zip",
            "win64": "chromedriver-win64.zip"
        }.get(platform_name, "chromedriver.zip")
        
        zip_path = cache_dir / zip_filename
        response = requests.get(download_url, timeout=120)
        response.raise_for_status()
        with open(zip_path, "wb") as f:
            f.write(response.content)
        
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(cache_dir)
        
        chromedriver_path = None
        executable_name = "chromedriver.exe" if system == "windows" else "chromedriver"
        for root, dirs, files in os.walk(cache_dir):
            if executable_name in files:
                chromedriver_path = Path(root) / executable_name
                break
        
        if not chromedriver_path or not chromedriver_path.exists():
            raise Exception(f"ChromeDriver executable not found after extraction in {cache_dir}")
        
        if system != "windows":
            os.chmod(chromedriver_path, 0o755)
        
        logging.info(f"ChromeDriver installed at: {chromedriver_path}")
        return str(chromedriver_path)
        
    except Exception as e:
        logging.error(f"Failed to download ChromeDriver for version {chrome_version}: {e}")
        raise


def create_driver() -> webdriver.Chrome:
    logging.info("Creating Chrome driver...")
    
    chrome_bin = os.getenv("CHROME_BIN")
    if not chrome_bin:
        if os.path.exists("/opt/hostedtoolcache/setup-chrome/chromium"):
            chrome_bin_pattern = "/opt/hostedtoolcache/setup-chrome/chromium/*/x64/chrome"
            matches = glob.glob(chrome_bin_pattern)
            if matches:
                chrome_bin = matches[0]
        else:
            chrome_bin = "google-chrome"
    
    if not os.path.exists(chrome_bin):
        raise FileNotFoundError(f"Chrome binary not found at: {chrome_bin}")
    
    if not os.access(chrome_bin, os.X_OK):
        raise PermissionError(f"Chrome binary is not executable: {chrome_bin}")
    
    logging.info(f"Using Chrome binary: {chrome_bin}")
    
    try:
        result = subprocess.run(
            [chrome_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        logging.info(f"Chrome binary version check: {result.stdout.strip()}")
    except Exception as e:
        logging.warning(f"Could not verify Chrome binary version: {e}")
    
    chrome_options = Options()
    chrome_options.binary_location = chrome_bin
    
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36")
    
    chromedriver_path = None
    try:
        original_chrome_bin = os.getenv("CHROME_BIN")
        os.environ["CHROME_BIN"] = chrome_bin
        
        chrome_version = get_chrome_version()
        if chrome_version:
            logging.info(f"Installing ChromeDriver for Chrome {chrome_version}...")
            chromedriver_path = download_chromedriver_for_version(chrome_version)
        
        if original_chrome_bin:
            os.environ["CHROME_BIN"] = original_chrome_bin
        elif "CHROME_BIN" in os.environ:
            del os.environ["CHROME_BIN"]
    except Exception as e:
        logging.warning(f"Failed to get ChromeDriver for specific version: {e}")
        logging.info("Falling back to webdriver-manager...")
    
    if not chromedriver_path:
        try:
            logging.info("Installing ChromeDriver via webdriver-manager...")
            chromedriver_path = ChromeDriverManager().install()
        except Exception as e:
            logging.error(f"Failed to install ChromeDriver: {e}")
            raise
    
    service = Service(chromedriver_path)
    logging.info("Starting Chrome browser...")
    logging.info(f"ChromeDriver path: {chromedriver_path}")
    logging.info(f"Chrome binary path: {chrome_bin}")
    
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        stealth(driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Linux",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
        )
        
        logging.info("Chrome driver created successfully with stealth mode enabled")
        return driver
    except Exception as e:
        logging.error(f"Failed to create Chrome driver: {e}")
        logging.error(f"ChromeDriver path: {chromedriver_path}")
        logging.error(f"Chrome binary path: {chrome_bin}")
        raise


def wait_for_cloudflare_clear(driver: webdriver.Chrome, url: str, timeout: int = 45) -> bool:
    """Detect and wait for Cloudflare challenge pages to clear."""
    start_time = time.time()
    already_refreshed = False
    while time.time() - start_time < timeout:
        try:
            title = (driver.title or "").lower()
        except Exception:
            title = ""
        try:
            page_source = driver.page_source.lower() if driver.page_source else ""
        except Exception:
            page_source = ""
        
        if any(keyword in title or keyword in page_source for keyword in CLOUDFLARE_KEYWORDS):
            logging.warning(f"☁️  Cloudflare challenge detected on {url}. Waiting for clearance...")
            time.sleep(5)
            if not already_refreshed:
                try:
                    driver.refresh()
                    already_refreshed = True
                except Exception:
                    pass
            continue
        return True

    logging.error(f"❌ Cloudflare challenge did not clear for {url} within {timeout}s")
    return False


def extract_url_data(driver: webdriver.Chrome, url: str, max_retries: int = 5) -> Tuple[Dict[str, str], webdriver.Chrome]:
    for attempt in range(max_retries):
        try:
            driver.get(url)
            
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            if not wait_for_cloudflare_clear(driver, url):
                raise TimeoutException("Cloudflare challenge did not clear in time")
            
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            h1 = h2 = content = ""
            try:
                h1_el = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h1.dictionary-detail-title"))
                )
                h1 = h1_el.text.strip()
            except TimeoutException:
                pass
            try:
                h2_el = driver.find_element(By.CSS_SELECTOR, "h2.dictionary-detail-title")
                h2 = h2_el.text.strip()
            except NoSuchElementException:
                pass
            try:
                content_el = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.dictionary-details"))
                )
                content = content_el.text.strip()
            except TimeoutException:
                pass
            return {"url": url, "h1": h1, "h2": h2, "content": content}, driver
        except Exception as e:
            logging.warning(f"URL error {url} (attempt {attempt + 1}/{max_retries}): {e}. Retry in 10s...")
            time.sleep(10)
    return {"url": url, "h1": "", "h2": "", "content": ""}, driver


def load_failed_urls() -> List[str]:
    if not os.path.exists(FAILED_URLS_FILE):
        logging.error(f"❌ {FAILED_URLS_FILE} not found!")
        return []
    with open(FAILED_URLS_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip()]
    logging.info(f"📂 Loaded {len(urls)} failed URLs")
    return urls


def load_existing_results() -> List[str]:
    if not os.path.exists(OUTPUT_FILE):
        return []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [item.get("url", "") for item in data if item.get("url")]
    except Exception:
        return []


def save_results(results: List[Dict[str, str]]) -> None:
    existing = []
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    existing.extend(results)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    logging.info(f"💾 Saved {len(results)} results (total: {len(existing)})")


def main():
    logging.info("=" * 70)
    logging.info("🔄 RETRYING FAILED URL EXTRACTIONS")
    logging.info("=" * 70)

    failed_urls = load_failed_urls()
    if not failed_urls:
        return

    processed = set(load_existing_results())
    remaining = [url for url in failed_urls if url not in processed]

    logging.info(f"📊 Total failed URLs: {len(failed_urls)}")
    logging.info(f"✅ Already processed: {len(processed)}")
    logging.info(f"⏳ Remaining to process: {len(remaining)}")

    if not remaining:
        logging.info("✅ All URLs already processed!")
        return

    batch: List[Dict[str, str]] = []
    successful = 0
    still_failed = 0

    for idx, url in enumerate(remaining, 1):
        logging.info(f"[{idx}/{len(remaining)}] Processing: {url}")
        driver = None
        try:
            driver = create_driver()
            data, driver = extract_url_data(driver, url)
            if data.get("h1") or data.get("h2") or data.get("content"):
                successful += 1
                logging.info("  ✅ Success!")
            else:
                still_failed += 1
                logging.warning("  ❌ Still empty")
            data["extracted_at"] = datetime.utcnow().isoformat()
            batch.append(data)
            if len(batch) >= BATCH_SIZE:
                save_results(batch)
                batch = []
        except Exception as exc:
            still_failed += 1
            logging.error(f"  ❌ Error: {exc}")
            batch.append({
                "url": url,
                "h1": "",
                "h2": "",
                "content": "",
                "error": str(exc),
                "extracted_at": datetime.utcnow().isoformat(),
            })
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            time.sleep(2)

    if batch:
        save_results(batch)

    logging.info("=" * 70)
    logging.info("📊 RETRY SUMMARY")
    logging.info("=" * 70)
    logging.info(f"✅ Successful: {successful}")
    logging.info(f"❌ Still failed: {still_failed}")
    logging.info(f"📝 Total processed: {len(remaining)}")
    logging.info("=" * 70)


if __name__ == "__main__":
    main()
