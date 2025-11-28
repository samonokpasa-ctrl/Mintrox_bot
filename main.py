import time
import threading
from datetime import datetime, timezone
import feedparser
import telebot
from supabase import create_client
from flask import Flask, request
import os

# ------------------- CONFIG -------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
USER_CHAT_ID = int(os.environ.get("USER_CHAT_ID"))
BATCH_SIZE = 5
BATCH_SEND_INTERVAL = 600  # 10 minutes
PULSE_DELAY = 7
BUFFER_LOW_THRESHOLD = 10
STATUS_INTERVAL = 1800
FETCH_INTERVAL = 300  # 5 minutes

# ------------------- SUPABASE SETUP -------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TABLE_NAME = "sent_posts"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ------------------- VERIFIED WORKING FEEDS -------------------
# Only using feeds that actually work on Render
RSS_FEEDS_PRIORITY = {
    "AI News": [
        "https://techcrunch.com/tag/artificial-intelligence/feed/",
    ],
    "Tech News": [
        "https://www.techmeme.com/feed.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
        "https://feeds.bbci.co.uk/news/technology/rss.xml"
    ]
}

# ------------------- BUFFER -------------------
semi_fetch_buffer = []
buffer_lock = threading.Lock()

# ------------------- SUPABASE HELPERS -------------------
def link_sent(chat_id, url):
    try:
        result = supabase.table(TABLE_NAME).select("*").eq("chat_id", chat_id).eq("url", url).execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"Database error: {e}")
        return False

def mark_sent(chat_id, url):
    try:
        supabase.table(TABLE_NAME).insert({"chat_id": chat_id, "url": url}).execute()
        print(f"✓ Marked as sent: {url[:50]}...")
    except Exception as e:
        print(f"Mark sent error: {e}")

# ------------------- SILENT FETCHER -------------------
def fetch_rss_posts():
    """Fetch posts without verbose logging"""
    all_posts = []
    fetched_count = 0
    
    for category, feeds in RSS_FEEDS_PRIORITY.items():
        for url in feeds:
            try:
                feed = feedparser.parse(url)
                
                if not feed.entries:
                    continue
                    
                for entry in feed.entries[:10]:  # Only recent 10 entries
                    link = entry.get("link")
                    title = entry.get("title", "No Title")
                    published = entry.get("published_parsed", time.gmtime(0))
                    
                    if link and not link_sent(USER_CHAT_ID, link):
                        post = {
                            "title": title,
                            "link": link,
                            "published_parsed": published,
                            "category": category
                        }
                        all_posts.append(post)
                        fetched_count += 1
                        
            except Exception as e:
                # Silently skip failed feeds - we already know which ones work
                continue
    
    all_posts.sort(key=lambda x: x["published_parsed"], reverse=True)
    
    if fetched_count > 0:
        print(f"✅ Fetched {fetched_count} new posts from {len(RSS_FEEDS_PRIORITY)} sources")
    
    return all_posts

# ------------------- ADAPTIVE FETCHER -------------------
def adaptive_fetcher():
    """Continuous fetcher"""
    while True:
        try:
            with buffer_lock:
                current_size = len(semi_fetch_buffer)
                
            if current_size < BUFFER_LOW_THRESHOLD:
                new_posts = fetch_rss_posts()
                if new_posts:
                    with buffer_lock:
                        semi_fetch_buffer.extend(new_posts)
                    print(f"📦 Buffer: {len(semi_fetch_buffer)} posts")
                else:
                    print("ℹ️ No new posts found this cycle")
            else:
                print(f"💤 Buffer sufficient ({current_size} posts)")
                
        except Exception as e:
            print(f"Fetcher error: {e}")
            
        time.sleep(FETCH_INTERVAL)

# ------------------- BATCH SENDER -------------------
def send_batch():
    """Send posts to Telegram"""
    while True:
        try:
            with buffer_lock:
                if semi_fetch_buffer:
                    batch_size = min(BATCH_SIZE, len(semi_fetch_buffer))
                    batch = semi_fetch_buffer[:batch_size]
                    semi_fetch_buffer[:batch_size] = []
                    
                    print(f"🚀 Sending batch of {len(batch)} posts to Telegram...")
                    
                    successful_sends = 0
                    for i, post in enumerate(batch):
                        try:
                            msg = f"📘 **THOT SIGNAL** - {post['category']}\n**{post['title']}**\n{post['link']}"
                            bot.send_message(USER_CHAT_ID, msg, parse_mode="Markdown")
                            mark_sent(USER_CHAT_ID, post["link"])
                            successful_sends += 1
                            
                            # Add delay between posts, but not after the last one
                            if i < len(batch) - 1:
                                time.sleep(PULSE_DELAY)
                                
                        except Exception as e:
                            print(f"❌ Failed to send post: {e}")
                            # Put failed post back to buffer for retry
                            with buffer_lock:
                                semi_fetch_buffer.append(post)
                    
                    print(f"✅ Successfully sent {successful_sends}/{len(batch)} posts")
                    
                    # Send batch completion message
                    if successful_sends > 0:
                        try:
                            bot.send_message(USER_CHAT_ID, 
                                           f"📢 Batch complete. {successful_sends} signals processed.")
                        except Exception as e:
                            print(f"Failed to send completion message: {e}")
                    
                    time.sleep(BATCH_SEND_INTERVAL)
                else:
                    # Buffer empty, wait longer
                    time.sleep(60)
                    
        except Exception as e:
            print(f"Batch sender error: {e}")
            time.sleep(60)

# ------------------- STATUS LOOP -------------------
def status_loop():
    """Send periodic status updates"""
    while True:
        time.sleep(STATUS_INTERVAL)
        try:
            with buffer_lock:
                buffer_size = len(semi_fetch_buffer)
            
            status_msg = f"📘 THOT STATUS\nActive feeds: 4\nBuffer: {buffer_size} posts\nLast update: {datetime.now().strftime('%H:%M')}"
            bot.send_message(USER_CHAT_ID, status_msg)
            print("📊 Status update sent")
        except Exception as e:
            print(f"Status error: {e}")

# ------------------- FLASK APP -------------------
app = Flask(__name__)
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL_BASE = "https://mintrox-bot-jp7h.onrender.com"
WEBHOOK_URL_PATH = f"/{TELEGRAM_TOKEN}"

@app.route("/")
def home():
    with buffer_lock:
        buffer_size = len(semi_fetch_buffer)
    return {
        "status": "online", 
        "buffer_size": buffer_size,
        "active_feeds": 4,
        "service": "THOT RSS Bot"
    }

@app.route("/health")
def health():
    """Health check endpoint"""
    with buffer_lock:
        buffer_size = len(semi_fetch_buffer)
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "buffer": buffer_size,
        "version": "1.0"
    }

@app.route(WEBHOOK_URL_PATH, methods=["POST"])
def webhook():
    """Telegram webhook"""
    json_string = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "OK"

# ------------------- INITIALIZATION -------------------
def initialize_bot():
    """Initialize the bot"""
    try:
        # Set webhook
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH)
        
        # Send startup message
        startup_msg = """📘 THOT is online
✅ Monitoring 4 verified feeds:
• TechCrunch AI
• Techmeme  
• NY Times Tech
• BBC Tech
Signal flow initiated."""
        bot.send_message(USER_CHAT_ID, startup_msg)
        
        # Initial fetch
        print("Performing initial fetch...")
        initial_posts = fetch_rss_posts()
        if initial_posts:
            with buffer_lock:
                semi_fetch_buffer.extend(initial_posts)
            print(f"✅ Initial fetch: {len(initial_posts)} posts")
        else:
            print("ℹ️ No initial posts found")
            
    except Exception as e:
        print(f"Initialization error: {e}")

# ------------------- MAIN -------------------
if __name__ == "__main__":
    print("🚀 Starting THOT RSS Bot...")
    
    initialize_bot()

    # Start background threads
    threading.Thread(target=adaptive_fetcher, daemon=True, name="Fetcher").start()
    threading.Thread(target=send_batch, daemon=True, name="Sender").start()
    threading.Thread(target=status_loop, daemon=True, name="Status").start()
    
    print("🎉 THOT Bot is running with 4 verified RSS feeds!")
    print("📡 Monitoring: TechCrunch, Techmeme, NY Times, BBC")
    
    # Run Flask app
    app.run(host="0.0.0.0", port=PORT, debug=False)
