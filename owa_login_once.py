# owa_login_once.py
# Persistent login για Outlook Web με Edge + stealth tweaks για SSO/GoDaddy

from playwright.sync_api import sync_playwright
import os
from dotenv import load_dotenv

load_dotenv()

PROFILE_DIR = os.getenv("OWA_PROFILE_DIR", "owa_profile")
HEADLESS = (os.getenv("OWA_HEADLESS", "false").lower() == "true")
URL = "https://outlook.office.com/mail/"
BROWSER_CHANNEL = os.getenv("OWA_BROWSER_CHANNEL", "msedge").strip() or None
CUSTOM_UA = os.getenv(
    "OWA_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
SLOW_MO = int(os.getenv("OWA_SLOW_MO", "120"))

STEALTH_JS = r"""
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins',  { get: () => [1,2,3,4,5] });
Object.defineProperty(navigator, 'languages',{ get: () => ['en-US','en'] });
Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
window.chrome = window.chrome || { runtime: {} };
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
  parameters.name === 'notifications'
    ? Promise.resolve({ state: Notification.permission })
    : originalQuery(parameters)
);
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
  if (parameter == 37445) return 'Intel Inc.';
  if (parameter == 37446) return 'Intel Iris OpenGL';
  return getParameter.call(this, parameter);
};
"""

def main():
    os.makedirs(PROFILE_DIR, exist_ok=True)
    print(f"🔐 Άνοιγμα Edge (persistent) με προφίλ: {PROFILE_DIR}")
    print("➡️ Κάνε κανονικά login (GoDaddy/Microsoft 365).")
    print("ℹ️ Όταν δεις το Inbox, γύρνα στο terminal και πάτα Enter για αποθήκευση session.")

    with sync_playwright() as p:
        launch_args = [
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
            "--disable-extensions",
        ]

        context = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=HEADLESS,
            accept_downloads=True,
            args=launch_args,
            channel=BROWSER_CHANNEL,
            user_agent=CUSTOM_UA,
            viewport=None,
            slow_mo=SLOW_MO,
            ignore_default_args=["--enable-automation", "--disable-component-update", "--no-sandbox"],
        )

        # stealth πριν ανοίξουν σελίδες
        context.add_init_script(STEALTH_JS)

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(URL, timeout=120_000)

        try:
            page.wait_for_selector('[role="navigation"]', timeout=30_000)
        except Exception:
            pass

        input("\n✅ Όταν ολοκληρώσεις το login και δεις το Inbox, πάτα Enter εδώ για να κλείσουμε... ")
        context.close()

    print("💾 Το session αποθηκεύτηκε. Τώρα τρέξε: python owa_fetch_pdfs.py")

if __name__ == "__main__":
    main()
