"""Smoke test: headless Chrome screenshot via Selenium."""
import sys
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

opts = Options()
opts.add_argument("--headless=new")
opts.add_argument("--no-sandbox")
opts.add_argument("--disable-gpu")
opts.add_argument("--window-size=1366,768")
try:
    driver = webdriver.Chrome(options=opts)
except Exception as e:
    print("DRIVER_FAIL:", type(e).__name__, str(e)[:500])
    sys.exit(2)
driver.get("http://127.0.0.1:8000/health")
print("TITLE:", driver.title)
print("BODY:", driver.find_element("tag name", "body").text[:200])
driver.save_screenshot(r"C:\Users\dumka\OneDrive\Desktop\GUI\shot_smoke.png")
print("SHOT_OK")
driver.quit()
