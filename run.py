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
HEADERS    = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
TIMEOUT    = 20  # seconds

# Keywords to look for in new content (case-insensitive)
TICKET_KEYWORDS = [
    'biglietti',      # tickets
    'biglietto',      # ticket
    'prezzo',         # price
    'prezzi',         # prices
    'costo',          # cost
    'vendita',        # sale
    'acquisto',       # purchase
    'prenotazione',   # reservation
    'prenotazioni',   # reservations
    'disponibili',    # available
    'disponibile',    # available
    'aperto',         # open
    'apertura',       # opening
    'chiusura',       # closing
    'orari',          # hours/schedule
    'orario',         # hour/schedule
    'euro',           # euro
    '€',              # euro symbol
    'gratuito',       # free
    'gratis',         # free
    'posti',          # seats
    'posto',          # seat
    'sala',           # hall/room
    'cinema',         # cinema
    'film',           # film/movie
    'proiezione',     # screening
    'proiezioni',     # screenings
    'festival',       # festival
    'biennale',       # biennale
    'venezia'         # venice
]

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

def contains_keywords(text: str, keywords: list) -> bool:
    """Check if text contains any of the specified keywords (case-insensitive)."""
    text_lower = text.lower()
    return any(keyword.lower() in text_lower for keyword in keywords)

def generate_diff(old_text: str, new_text: str, max_lines: int = 10) -> tuple[str, bool]:
    """Generate a short diff showing only new information (additions). Returns (diff_text, has_keywords)."""
    if not old_text:
        # If no old text, show first few lines of new text
        new_lines = new_text.split('\n')[:max_lines]
        diff_text = f"📝 New content (first {len(new_lines)} lines):\n" + '\n'.join(f"+ {line}" for line in new_lines)
        has_keywords = contains_keywords('\n'.join(new_lines), TICKET_KEYWORDS)
        return diff_text, has_keywords

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
        return "📝 Content changed but no clear diff available", False

    # Filter to show only additions (lines starting with '+') and context lines
    additions_only = []
    keyword_additions = []  # Track additions with keywords
    
    for line in diff[3:]:  # Skip header lines
        if line.startswith('+'):
            additions_only.append(line)
            # Check if this addition contains keywords
            line_content = line[1:].strip()  # Remove '+' prefix
            if contains_keywords(line_content, TICKET_KEYWORDS):
                keyword_additions.append(line)
        elif line.startswith(' ') and additions_only:
            # Include context lines only if we already have some additions
            additions_only.append(line)
    
    # Limit to max_lines
    additions_only = additions_only[:max_lines]

    if not additions_only:
        return "📝 Content changed (no new information detected)", False

    diff_text = f"📝 New information:\n<code>" + '\n'.join(additions_only) + "</code>"
    has_keywords = len(keyword_additions) > 0
    
    return diff_text, has_keywords

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
                diff_text, has_keywords = generate_diff(old_text, new_text)
                
                if has_keywords:
                    print(f"  ✅ Keywords found in changes - will notify")
                    changes_detected.append({
                        "page_name": page_name,
                        "url": url,
                        "hash": new_hash,
                        "diff": diff_text
                    })
                else:
                    print(f"  ⏭️ No relevant keywords found in changes - skipping notification")

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