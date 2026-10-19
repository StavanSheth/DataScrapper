import sqlite3
import json
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

conn = sqlite3.connect('data/database/leads.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

cursor.execute('SELECT COUNT(*) FROM platform_listings')
total = cursor.fetchone()[0]

cursor.execute('SELECT * FROM platform_listings ORDER BY id DESC LIMIT 5')
rows = cursor.fetchall()

print(f"================================================================================")
print(f"📊 TOTAL SCRAPED PLATFORM LISTINGS IN DATABASE: {total}")
print(f"================================================================================\n")

for i, r in enumerate(rows, 1):
    d = dict(r)
    print(f"--- [RECORD #{d.get('id')}] Platform: {d.get('platform')} ---")
    print(f"  Title          : {d.get('title')}")
    print(f"  Clean Brand    : {d.get('clean_brand')}")
    print(f"  Category       : {d.get('category')}")
    print(f"  Rating         : {d.get('rating')} / 5.0")
    print(f"  Reviews Count  : {d.get('reviews_count')}")
    print(f"  Price Info     : {d.get('price_info') or 'Standard / Free Quote'}")
    print(f"  Direct Link    : {d.get('url')}")
    print(f"  Booking URL    : {d.get('booking_url')}")
    print(f"  Address/Area   : {d.get('address')}")
    print(f"  Website Status : {d.get('website_status')}")
    print(f"  Bot Protection : {d.get('bot_protection')}")
    print(f"  Captured At    : {d.get('created_at')}")
    print()
