from pathlib import Path
import hashlib
import requests
import os
import sys
import difflib
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv()  # Load environment variables from .env file

# List of pages to monitor
PAGES = [
    {
        "page_name": "Informazioni",
        "url": "https://www.labiennale.org/it/cinema/2025/informazioni",
        "filename": "informazioni.txt"
    },
    {
        "page_name": "labiennale.org/it",
        "url": "https://www.labiennale.org/it",
        "filename": "labienalle_it.txt"
    },
    {
        "page_name": "labiennale.org/it/cinema/2025",
        "url": "https://www.labiennale.org/it/cinema/2025",
        "filename": "labienalle_cinema.txt"
    }
]

CACHE_DIR  = Path("cache")
HEADERS    = {"User-Agent": "ticket-watcher/1.0 (+https://github.com/your/repo)"}
TIMEOUT    = 20  # seconds

# Telegram configuration
KEY = os.getenv('TELEGRAM_BOT_TOKEN', '')  # Bot token stored in environment variable
CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID', '')  # Channel ID (e.g., @your_channel or -100123456789)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

def fetch_page(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text

def extract_text_content(html: str) -> str:
    """Extract only the text content from HTML using Beautiful Soup."""
    soup = BeautifulSoup(html, 'html.parser')
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    # Get text and normalize whitespace
    text = soup.get_text()
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    return '\n'.join(chunk for chunk in chunks if chunk)

def generate_diff(old_text: str, new_text: str, max_lines: int = 10) -> str:
    """Generate a short diff showing changes between old and new text."""
    if not old_text:
        # If no old text, show first few lines of new text
        new_lines = new_text.split('\n')[:max_lines]
        return f"📝 New content (first {len(new_lines)} lines):\n" + '\n'.join(f"+ {line}" for line in new_lines)

    old_lines = old_text.split('\n')
    new_lines = new_text.split('\n')

    # Generate unified diff
    diff = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile='previous',
        tofile='current',
        lineterm='',
        n=2  # Context lines
    ))

    if not diff:
        return "📝 Content changed but no clear diff available"

    # Filter out header lines and limit to max_lines
    relevant_diff = [line for line in diff[3:] if line.startswith(('+', '-', ' '))][:max_lines]

    if not relevant_diff:
        return "📝 Content structure changed"

    return f"📝 Changes:\n<code>" + '\n'.join(relevant_diff) + "</code>"

def send_telegram_message(message: str) -> bool:
    """Send a message to Telegram channel. Returns True if successful."""
    if not KEY or not CHANNEL_ID:
        print("❌ Telegram credentials not configured (KEY or CHANNEL_ID missing)")
        return False

    telegram_url = f"https://api.telegram.org/bot{KEY}/sendMessage"

    payload = {
        'chat_id': CHANNEL_ID,
        'text': message,
        'parse_mode': 'HTML'  # Allows basic HTML formatting
    }

    try:
        response = requests.post(telegram_url, data=payload, timeout=TIMEOUT)
        response.raise_for_status()

        result = response.json()
        if result.get('ok'):
            print("✅ Telegram channel notification sent successfully")
            return True
        else:
            print(f"❌ Telegram API error: {result.get('description', 'Unknown error')}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to send Telegram notification: {e}")
        return False

def main() -> None:
    CACHE_DIR.mkdir(exist_ok=True)

    changes_detected = []
    errors_encountered = []

    # Iterate through all pages to monitor
    for page in PAGES:
        page_name = page["page_name"]
        url = page["url"]
        cache_file = CACHE_DIR / page["filename"]

        print(f"Checking {page_name}...")
        
        # Debug: Check if cache file exists
        if cache_file.exists():
            print(f"  📁 Cache file found: {cache_file}")
        else:
            print(f"  📁 Cache file missing: {cache_file} (first run or cache cleared)")

        try:
            new_html = fetch_page(url)
            new_text = extract_text_content(new_html)
            new_hash = sha(new_text)
            old_text = cache_file.read_text() if cache_file.exists() else ""
            old_hash = sha(old_text) if old_text else None

            if old_hash != new_hash:
                print(f"🎫 CHANGE DETECTED on {page_name}!")
                diff_text = generate_diff(old_text, new_text)
                changes_detected.append({
                    "page_name": page_name,
                    "url": url,
                    "hash": new_hash,
                    "diff": diff_text
                })

            else:
                print(f"No change detected on {page_name}.")

            # Always update cache file
            cache_file.write_text(new_text)

        except requests.exceptions.RequestException as e:
            error_msg = f"Error fetching {page_name}: {e}"
            print(f"❌ {error_msg}")
            errors_encountered.append({
                "page_name": page_name,
                "url": url,
                "error": str(e)
            })

    # Send notifications for changes
    for change in changes_detected:
        message = (
            f"🎫 <b>{change['page_name']} Update!</b>\n\n"
            f"A change has been detected on the {change['page_name']} page.\n\n"
            f"{change['diff']}\n\n"
            f"🔗 <a href='{change['url']}'>Check the page now</a>\n\n"
        )
        send_telegram_message(message)

    # Send error notifications
    for error in errors_encountered:
        error_message = (
            f"⚠️ <b>{error['page_name']} Watcher Error</b>\n\n"
            f"Failed to fetch the {error['page_name']} page:\n<code>{error['error']}</code>\n\n"
            f"🔗 <a href='{error['url']}'>Target URL</a>"
        )
        send_telegram_message(error_message)

    # Exit with error code if any errors occurred
    if errors_encountered:
        sys.exit(1)

if __name__ == "__main__":
    main()