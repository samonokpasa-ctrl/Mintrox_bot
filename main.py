import time
import threading
from datetime import datetime, timezone
import feedparser
import telebot
from supabase import create_client
from flask import Flask, request
import os

# ------------------- CONFIG -------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8374495248:AAECvxzEgHxYRV3VhKC2LpH8rlNVBktRf6Q")
USER_CHAT_ID = int(os.environ.get("USER_CHAT_ID", "1168907278"))
BATCH_SIZE = 2  # Reduced for testing
BATCH_SEND_INTERVAL = 30  # 30 seconds for testing
PULSE_DELAY = 3  # Reduced for testing
BUFFER_LOW_THRESHOLD = 3  # Reduced for testing
STATUS_INTERVAL = 300  # 5 minutes for testing
FETCH_INTERVAL = 60  # 1 minute for testing

# ------------------- SUPABASE SETUP -------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://nbyzjrrgmgfvgkhftydv.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5ieXpqcnJnbWdmdmdraGZ0eWR2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM5OTQwMTAsImV4cCI6MjA3OTU3MDAxMH0.BUs7AgjjBtq1vDNClvqAjUZRMLjbrfNOAGpA0UPtyWk")
TABLE_NAME = "sent_posts"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ------------------- TELEGRAM BOT -------------------
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ------------------- SUPABASE HELPERS -------------------
def link_sent(chat_id, url):
    try:
        result = supabase.table(TABLE_NAME).select("*") \
            .eq("chat_id", chat_id).eq("url", url).execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"Database error in link_sent: {e}")
        return False

def mark_sent(chat_id, url):
    try:
        supabase.table(TABLE_NAME).insert({"chat_id": chat_id, "url": url}).execute()
        print(f"✓ Marked as sent in DB: {url[:50]}...")
    except Exception as e:
        print(f"✗ Database error in mark_sent: {e}")

# ------------------- RSS FEEDS -------------------
RSS_FEEDS_PRIORITY = {
    "AI News": [
        "https://venturebeat.com/category/ai/feed/",
        "https://techcrunch.com/tag/artificial-intelligence/feed/",
    ],
    "Tech News": [
        "https://www.techmeme.com/feed.xml",
        "https://www.theverge.com/tech/rss/index.xml",
    ]
}

# ------------------- BUFFER -------------------
semi_fetch_buffer = []
buffer_lock = threading.Lock()

# ------------------- TRACK DEAD FEEDS -------------------
dead_feeds = {}

# ------------------- IMPROVED FETCHER -------------------
def fetch_rss_posts():
    """Fetch posts from all feeds"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n=== [{now}] FETCHING NEW POSTS ===")
    all_posts = []

    for category, feeds in RSS_FEEDS_PRIORITY.items():
        print(f"📡 Scanning {category}...")
        
        for url in feeds:
            if url in dead_feeds and time.time() - dead_feeds[url] < 3600:
                continue
                
            try:
                print(f"   🔍 Checking: {url}")
                feed = feedparser.parse(url)
                
                if not feed.entries:
                    print(f"   ⚠️  No entries found")
                    continue
                    
                new_count = 0
                for entry in feed.entries[:5]:  # Only check recent 5
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
                        new_count += 1
                        print(f"   ✅ NEW: {title[:60]}...")
                        
                if new_count > 0:
                    print(f"   📥 Found {new_count} new posts")
                    
            except Exception as e:
                print(f"   ❌ Feed failed: {e}")
                dead_feeds[url] = time.time()

    all_posts.sort(key=lambda x: x["published_parsed"], reverse=True)
    print(f"=== FETCH COMPLETE: {len(all_posts)} new posts found ===\n")
    return all_posts

# ------------------- IMPROVED MESSAGE SENDING -------------------
def send_telegram_message(chat_id, text, parse_mode=None):
    """Send message to Telegram with detailed error handling"""
    try:
        print(f"📤 Attempting to send message to Telegram...")
        if parse_mode:
            bot.send_message(chat_id, text, parse_mode=parse_mode)
        else:
            bot.send_message(chat_id, text)
        print(f"✅ Message sent successfully!")
        return True
    except telebot.apihelper.ApiException as e:
        print(f"❌ Telegram API Error: {e}")
        print(f"   Status code: {e.error_code}")
        print(f"   Description: {e.description}")
        return False
    except Exception as e:
        print(f"❌ Unexpected send error: {e}")
        return False

# ------------------- FIXED BATCH SENDER -------------------
def send_batch():
    """Send posts in batches with comprehensive logging"""
    print("🔄 Batch sender started...")
    
    while True:
        try:
            with buffer_lock:
                buffer_size = len(semi_fetch_buffer)
                print(f"📊 Buffer size: {buffer_size}")
                
                if semi_fetch_buffer:
                    batch_size = min(BATCH_SIZE, len(semi_fetch_buffer))
                    batch = semi_fetch_buffer[:batch_size]
                    semi_fetch_buffer[:batch_size] = []
                    
                    print(f"🚀 SENDING BATCH OF {len(batch)} POSTS")
                    
                    for i, post in enumerate(batch):
                        print(f"   📨 Sending post {i+1}/{len(batch)}: {post['title'][:50]}...")
                        
                        msg = f"📘 **THOT SIGNAL** - {post['category']}\n**{post['title']}**\n{post['link']}"
                        
                        if send_telegram_message(USER_CHAT_ID, msg, parse_mode="Markdown"):
                            mark_sent(USER_CHAT_ID, post["link"])
                            print(f"   ✅ Successfully sent and recorded")
                        else:
                            print(f"   ❌ Failed to send, re-adding to buffer")
                            with buffer_lock:
                                semi_fetch_buffer.append(post)
                        
                        if i < len(batch) - 1:
                            print(f"   ⏳ Waiting {PULSE_DELAY} seconds...")
                            time.sleep(PULSE_DELAY)
                    
                    # Send batch completion message
                    completion_msg = f"📢 Batch complete. {len(batch)} signals processed. Next update in {BATCH_SEND_INTERVAL} seconds."
                    send_telegram_message(USER_CHAT_ID, completion_msg)
                    
                    print(f"✅ Batch sent. Waiting {BATCH_SEND_INTERVAL} seconds for next batch\n")
                    time.sleep(BATCH_SEND_INTERVAL)
                else:
                    print("😴 Buffer empty, waiting 30 seconds...")
                    time.sleep(30)
                    
        except Exception as e:
            print(f"💥 Critical error in send_batch: {e}")
            time.sleep(30)

# ------------------- ADAPTIVE FETCHER -------------------
def adaptive_fetcher():
    """Continuous fetcher"""
    print("🔄 Adaptive fetcher started...")
    
    while True:
        try:
            with buffer_lock:
                current_buffer_size = len(semi_fetch_buffer)
            
            print(f"📊 Fetcher check - Buffer: {current_buffer_size}, Threshold: {BUFFER_LOW_THRESHOLD}")
            
            if current_buffer_size < BUFFER_LOW_THRESHOLD:
                print("🔍 Buffer low, fetching new posts...")
                new_posts = fetch_rss_posts()
                
                if new_posts:
                    with buffer_lock:
                        semi_fetch_buffer.extend(new_posts)
                    print(f"📥 Added {len(new_posts)} posts to buffer")
                else:
                    print("ℹ️ No new posts found")
            else:
                print(f"💤 Buffer sufficient ({current_buffer_size}), skipping fetch")
                
        except Exception as e:
            print(f"💥 Error in adaptive_fetcher: {e}")
            
        print(f"⏰ Waiting {FETCH_INTERVAL} seconds until next fetch check\n")
        time.sleep(FETCH_INTERVAL)

# ------------------- STATUS LOOP -------------------
def status_loop():
    print("🔄 Status monitor started...")
    while True:
        time.sleep(STATUS_INTERVAL)
        try:
            with buffer_lock:
                buffer_size = len(semi_fetch_buffer)
            
            status_msg = f"📘 THOT STATUS:\nBuffer: {buffer_size} posts\nLast check: {datetime.now().strftime('%H:%M:%S')}\nSystem: Operational"
            send_telegram_message(USER_CHAT_ID, status_msg)
            print("📊 Status update sent")
        except Exception as e:
            print(f"❌ Status update failed: {e}")

# ------------------- AUTO START -------------------
def send_start_message():
    try:
        msg = "📘 THOT is online.\nCore systems calibrated.\nSignal flow initiated.\nContinuous monitoring enabled."
        send_telegram_message(USER_CHAT_ID, msg)
        print("✅ Start message sent")
    except Exception as e:
        print(f"❌ Failed to send start message: {e}")

# ------------------- FLASK SERVER -------------------
app = Flask(__name__)
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL_BASE = "https://mintrox-bot-jp7h.onrender.com"
WEBHOOK_URL_PATH = f"/{TELEGRAM_TOKEN}"

@app.route("/")
def home():
    with buffer_lock:
        buffer_size = len(semi_fetch_buffer)
    status = {
        "status": "online",
        "buffer_size": buffer_size,
        "timestamp": datetime.now().isoformat()
    }
    return status

@app.route("/debug")
def debug():
    with buffer_lock:
        buffer_info = {
            "buffer_size": len(semi_fetch_buffer),
            "buffer_titles": [post["title"][:50] + "..." for post in semi_fetch_buffer[:5]],
            "dead_feeds": len(dead_feeds),
            "threads_alive": [t.name for t in threading.enumerate()]
        }
    return buffer_info

@app.route("/force_fetch")
def force_fetch():
    """Manual trigger to fetch posts"""
    new_posts = fetch_rss_posts()
    with buffer_lock:
        semi_fetch_buffer.extend(new_posts)
    return {"action": "force_fetch", "added_posts": len(new_posts), "total_buffer": len(semi_fetch_buffer)}

@app.route(WEBHOOK_URL_PATH, methods=["POST"])
def webhook():
    json_string = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "OK"

# ------------------- INITIAL SETUP -------------------
def initialize_bot():
    """Initialize bot with error handling"""
    try:
        print("🚀 Initializing bot...")
        send_start_message()
        
        print("🔍 Performing initial fetch...")
        initial_posts = fetch_rss_posts()
        if initial_posts:
            with buffer_lock:
                semi_fetch_buffer.extend(initial_posts)
            print(f"✅ Initial fetch added {len(initial_posts)} posts to buffer")
        else:
            print("ℹ️ No posts in initial fetch")
            
    except Exception as e:
        print(f"❌ Initialization error: {e}")

# ------------------- MAIN -------------------
if __name__ == "__main__":
    # Webhook setup
    try:
        print("🔧 Setting up webhook...")
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH)
        print("✅ Webhook set successfully")
    except Exception as e:
        print(f"❌ Webhook setup error: {e}")

    # Initialize bot
    initialize_bot()

    # Start background threads
    print("👥 Starting background threads...")
    threading.Thread(target=adaptive_fetcher, daemon=True, name="Fetcher").start()
    threading.Thread(target=send_batch, daemon=True, name="Sender").start() 
    threading.Thread(target=status_loop, daemon=True, name="Status").start()
    
    print("🎉 All systems started! Bot is now running...")
    print("=" * 50)
    
    # Run Flask server
    app.run(host="0.0.0.0", port=PORT, debug=False)
