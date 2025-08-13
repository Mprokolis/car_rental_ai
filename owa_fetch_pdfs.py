# owa_fetch_pdfs.py
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from tenacity import retry, stop_after_attempt, wait_fixed
import os, json, hashlib, datetime, re, base64
from pathlib import Path
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

PROFILE_DIR   = os.getenv("OWA_PROFILE_DIR", "owa_profile")
DOWNLOAD_DIR  = os.getenv("OWA_DOWNLOAD_DIR", "reservations_inbox")
SENDER        = (os.getenv("OWA_SENDER_FILTER", "") or "").strip()
EXTRA         = (os.getenv("OWA_SEARCH_EXTRA", "hasattachments:yes") or "").strip()
MAX_MSG       = int(os.getenv("OWA_MAX_MESSAGES", "50"))
HEADLESS      = (os.getenv("OWA_HEADLESS", "false").lower() == "true")

BASE_URL  = "https://outlook.office.com/mail/"
STATE_FILE = "owa_download_state.json"   # κρατάμε hashes για αποφυγή διπλολήψεων

Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE, "r", encoding="utf-8"))
        except Exception:
            pass
    return {"hashes": []}

def save_state(state):
    json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def sha256_of_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def sanitize_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]", "_", name or "")
    name = name.strip().strip(".")
    return name or "attachment.pdf"

def build_query():
    parts = []
    if SENDER:
        parts.append(f"from:{SENDER}")
    if EXTRA:
        parts.append(EXTRA)
    return " ".join(parts) if parts else EXTRA

def open_search(page, query: str):
    q = quote(query)
    page.goto(f"https://outlook.office.com/mail/search?q={q}", timeout=120_000)
    page.wait_for_selector('[role="listbox"] [role="option"]', timeout=30_000)

def enumerate_indices(page, limit):
    items = page.locator('[role="listbox"] [role="option"]')
    count = items.count()
    return list(range(min(count, limit)))

def open_message_by_index(page, index: int):
    items = page.locator('[role="listbox"] [role="option"]')
    it = items.nth(index)
    it.click()
    page.wait_for_selector('div[role="document"]', timeout=20_000)

def find_pdf_attachment_elements(page):
    candidates = [
        'button[aria-label^="Download"]',
        'button[title^="Download"]',
        'a[download]',
        '[data-automationid="AttachmentWell"] a',
        '[data-automationid="AttachmentWell"] button',
    ]
    found = []
    for sel in candidates:
        try:
            els = page.query_selector_all(sel)
            for el in els:
                text = ""
                try:
                    text = (el.get_attribute("download") or el.get_attribute("title") or el.inner_text() or "")
                except Exception:
                    pass
                if ".pdf" in (text or "").lower():
                    found.append(el)
        except Exception:
            continue
    # Αφαίρεση διπλοτύπων
    uniq, seen = [], set()
    for el in found:
        try:
            sig = el.evaluate("el => el.outerHTML")
        except Exception:
            sig = str(el)
        if sig not in seen:
            seen.add(sig)
            uniq.append(el)
    return uniq

def save_download(download, target_dir):
    suggested = download.suggested_filename or "attachment.pdf"
    safe = sanitize_filename(suggested)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(target_dir) / f"{ts}__{safe}"
    download.save_as(str(dest))
    return str(dest)

@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def wait_for_results(page):
    page.wait_for_selector('[role="listbox"] [role="option"]', timeout=25_000)

def main():
    state = load_state()
    hashes = set(state.get("hashes", []))

    query = build_query()
    print(f"🔎 Search: {query}")
    print(f"💾 Downloads → {DOWNLOAD_DIR}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=HEADLESS,
            accept_downloads=True,
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(BASE_URL, timeout=120_000)

        # Αν ζητήσει login, σταματάμε για να τρέξεις ξανά το owa_login_once.py
        if any(key in page.url.lower() for key in ("login", "signin", "account")):
            context.close()
            raise SystemExit("⚠️ Δεν είσαι συνδεδεμένος. Τρέξε πρώτα: python owa_login_once.py")

        open_search(page, query)
        wait_for_results(page)

        indices = enumerate_indices(page, MAX_MSG)
        if not indices:
            print("ℹ️ Δεν βρέθηκαν μηνύματα.")
            context.close()
            return

        processed = 0
        new_files = 0
        skipped = 0
        failed = 0

        for idx in indices:
            processed += 1
            try:
                open_message_by_index(page, idx)
                page.wait_for_timeout(400)

                pdf_buttons = find_pdf_attachment_elements(page)
                if not pdf_buttons:
                    skipped += 1
                    continue

                for el in pdf_buttons:
                    try:
                        with page.expect_download(timeout=25_000) as dl_info:
                            el.click(force=True)
                        download = dl_info.value
                        tmp_path = save_download(download, DOWNLOAD_DIR)

                        file_hash = sha256_of_file(tmp_path)
                        if file_hash in hashes:
                            try:
                                os.remove(tmp_path)
                            except Exception:
                                pass
                            continue

                        hashes.add(file_hash)
                        new_files += 1
                        print(f"⬇️  {os.path.basename(tmp_path)}")
                    except PWTimeout:
                        failed += 1
                    except Exception as e:
                        print(f"❌ Σφάλμα download: {e}")
                        failed += 1

                page.wait_for_timeout(250)

            except Exception as e:
                print(f"❌ Σφάλμα ανοίγματος μηνύματος: {e}")
                failed += 1

        state["hashes"] = list(hashes)[-5000:]
        save_state(state)
        context.close()

    print(f"\n✅ ΤΕΛΟΣ: processed={processed}, new_files={new_files}, skipped={skipped}, failed={failed}")
    print(f"📁 Δες τα PDF στο: {DOWNLOAD_DIR}")

if __name__ == "__main__":
    main()
