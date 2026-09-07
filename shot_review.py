"""Screenshot review: login + workspaces at 1366x768, control at 3 widths.
Collects browser console errors. Saves PNGs next to the project root."""
import sys, time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

ROOT = r"C:\Users\dumka\OneDrive\Desktop\GUI"
BASE = "http://127.0.0.1:8000"
errors = []

def make_driver(w, h):
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument(f"--window-size={w},{h}")
    opts.add_argument("--force-device-scale-factor=1")
    d = webdriver.Chrome(options=opts)
    d.set_window_size(w, h)
    return d

def console_errors(d):
    global errors
    try:
        logs = d.get_log("browser")
    except Exception as e:
        return ["log-access-failed: %s" % e]
    out = [l for l in logs if l.get("level") in ("SEVERE", "ERROR")]
    errors.extend(out)
    return out

def login(d, user, pw):
    d.get(BASE + "/api/login")
    time.sleep(1)
    tok = d.find_element(By.CSS_SELECTOR, 'meta[name="stcs-csrf-token"]').get_attribute("content")
    d.find_element(By.ID, "username").send_keys(user)
    d.find_element(By.ID, "password").send_keys(pw)
    d.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
    time.sleep(2)
    return tok

# login page shots (unauthenticated)
d = make_driver(1366, 768)
d.get(BASE + "/api/login")
time.sleep(1)
d.save_screenshot(ROOT + "\\shot_login_1366.png")
print("LOGIN_HTML_BYTES:", len(d.page_source))
login(d, "Admin", "Admin@123")
print("AFTER_LOGIN_URL:", d.current_url)
for name, url in [("control", "/app/control"), ("observations", "/app/observations"),
                  ("camera", "/app/camera"), ("system", "/app/system"),
                  ("admin", "/app/admin")]:
    d.get(BASE + url)
    time.sleep(1.5)
    d.save_screenshot(f"{ROOT}\\shot_{name}_1366.png")
    errs = console_errors(d)
    print(f"SHOT {name}_1366 console_errors={len(errs)} scrollH={d.execute_script('return document.documentElement.scrollWidth > window.innerWidth')} scrollV={d.execute_script('return document.documentElement.scrollHeight > window.innerHeight')}")
    for e in errs:
        print("  CONSOLE:", str(e)[:220])
d.quit()

for w, h in [(1440, 900), (1920, 1080)]:
    d = make_driver(w, h)
    d.get(BASE + "/api/login")
    time.sleep(1)
    login(d, "Admin", "Admin@123")
    d.get(BASE + "/app/control")
    time.sleep(1.5)
    d.save_screenshot(f"{ROOT}\\shot_control_{w}.png")
    errs = console_errors(d)
    print(f"SHOT control_{w} console_errors={len(errs)} scrollH={d.execute_script('return document.documentElement.scrollWidth > window.innerWidth')} scrollV={d.execute_script('return document.documentElement.scrollHeight > window.innerHeight')}")
    for e in errs:
        print("  CONSOLE:", str(e)[:220])
    d.quit()
print("TOTAL_CONSOLE_ERRORS:", len(errors))
print("SHOTS_DONE")
