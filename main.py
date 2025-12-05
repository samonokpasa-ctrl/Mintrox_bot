import time
import threading
import traceback
from datetime import datetime
import feedparser
import telebot
from supabase import create_client
from flask import Flask, request
import os
import json
import requests

# ------------------- CONFIG -------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8374495248:AAECvxzEgHxYRV3VhKC2LpH8rlNVBktRf6Q")
USER_CHAT_ID = int(os.environ.get("USER_CHAT_ID", "1168907278"))
BATCH_SIZE = 5
BATCH_SEND_INTERVAL = 600  # 10 minutes
PULSE_DELAY = 7
BUFFER_LOW_THRESHOLD = 10
STATUS_INTERVAL = 1800
FETCH_INTERVAL = 300  # 5 minutes

# Render API for nuclear restart
RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "rnd_H1Sh4StDCRty0NVx2TxPrt0JBmC6")
RENDER_SERVICE_ID = os.environ.get("RENDER_SERVICE_ID", "srv-d4iaoeeuk2gs7385nmk0")

# ------------------- SUPABASE SETUP -------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://nbyzjrrgmgfvgkhftydv.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5ieXpqcnJnbWdmdmdraGZ0eWR2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM5OTQwMTAsImV4cCI6MjA3OTU3MDAxMH0.BUs7AgjjBtq1vDNClvqAjUZRMLjbrfNOAGpA0UPtyWk")
TABLE_NAME = "sent_posts"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# ------------------- RSS FEEDS -------------------
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

# ------------------- GLOBAL STATE -------------------
semi_fetch_buffer = []
buffer_lock = threading.Lock()
running = True
start_time = time.time()
restart_cooldown = {}
RESTART_COOLDOWN_MINUTES = 10

# ------------------- NUCLEAR RESTART MANAGER -------------------
class NuclearRestartManager:
    def __init__(self):
        self.api_key = RENDER_API_KEY
        self.service_id = RENDER_SERVICE_ID
        self.api_url = f"https://api.render.com/v1/services/{self.service_id}/restart"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        self.restart_flag_file = "/tmp/thot_nuclear_restart.txt"
        
    def trigger_nuclear_restart(self, chat_id):
        """Trigger Render service restart via API"""
        try:
            # Create restart flag for detection after restart
            with open(self.restart_flag_file, "w") as f:
                json.dump({
                    "triggered_at": time.time(),
                    "triggered_by": chat_id,
                    "link_count_before": self.get_sent_link_count()
                }, f)
            
            print(f"🔄 Nuclear restart triggered by {chat_id}")
            
            # Call Render API
            response = requests.post(self.api_url, headers=self.headers, timeout=10)
            
            if response.status_code == 201:
                return True, "✅ Nuclear restart initiated! Service will restart in 30-45 seconds."
            else:
                if os.path.exists(self.restart_flag_file):
                    os.remove(self.restart_flag_file)
                error_msg = f"API Error {response.status_code}: {response.text}"
                return False, error_msg
                
        except requests.exceptions.Timeout:
            if os.path.exists(self.restart_flag_file):
                os.remove(self.restart_flag_file)
            return False, "⚠️ Render API timeout. Service may still restart."
        except Exception as e:
            if os.path.exists(self.restart_flag_file):
                os.remove(self.restart_flag_file)
            return False, f"❌ Error: {str(e)}"
    
    def check_restart_flag(self):
        """Check if we just completed a nuclear restart"""
        if os.path.exists(self.restart_flag_file):
            try:
                with open(self.restart_flag_file, "r") as f:
                    data = json.load(f)
                os.remove(self.restart_flag_file)
                return data
            except:
                if os.path.exists(self.restart_flag_file):
                    os.remove(self.restart_flag_file)
        return None
    
    def get_sent_link_count(self):
        """Get count of sent links from Supabase"""
        try:
            result = supabase.table(TABLE_NAME).select("id", count="exact").execute()
            return result.count if hasattr(result, 'count') else 0
        except:
            return 0
    
    def get_manual_restart_link(self):
        """Generate direct link to restart service in Render dashboard"""
        return f"https://dashboard.render.com/redir/{self.service_id}/restart"
    
    def send_smart_restart_completion(self, restart_data):
        """Send smart completion message after nuclear restart"""
        try:
            link_count = self.get_sent_link_count()
            feed_count = sum(len(feeds) for feeds in RSS_FEEDS_PRIORITY.values())
            
            with buffer_lock:
                buffer_size = len(semi_fetch_buffer)
            
            message = f"""✅ **THOT Nuclear Restart Complete** 
⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

📊 **Status:**
• Sent links preserved: {link_count:,} ✓
• RSS feeds: {feed_count} monitoring ✓  
• Buffer: {buffer_size} posts
• Uptime: 0 minutes (fresh start)

🔄 RSS monitoring resumed...
"""
            
            bot.send_message(USER_CHAT_ID, message, parse_mode="Markdown")
            print(f"📤 Sent restart completion to {USER_CHAT_ID}")
            
        except Exception as e:
            print(f"Error sending restart completion: {e}")
    
    def send_error_with_manual_link(self, error_msg, chat_id):
        """Send error message with manual restart option"""
        manual_link = self.get_manual_restart_link()
        
        message = f"""❌ **Nuclear Restart Failed** 
`{error_msg[:200]}`

🔧 **Quick Fix Options:**

1. **Automatic Retry** - Wait 1 minute and try `/restart` again
2. **Manual Restart** - [Click here to restart manually]({manual_link}) (opens Render dashboard)

📞 **Need Help?** Check [Render Status](https://status.render.com)
"""
        
        try:
            bot.send_message(chat_id, message, parse_mode="Markdown", disable_web_page_preview=True)
        except:
            simple_msg = f"❌ Restart failed: {error_msg}\nManual restart: {manual_link}"
            bot.send_message(chat_id, simple_msg)

# Initialize restart manager
restart_manager = NuclearRestartManager()

# ------------------- SUPABASE HELPERS -------------------
def link_sent(chat_id, url):
    try:
        result = supabase.table(TABLE_NAME).select("*").eq("chat_id", chat_id).eq("url", url).execute()
        return len(result.data) > 0
    except Exception as e:
        print(f"Error checking link: {e}")
        return False

def mark_sent(chat_id, url):
    try:
        supabase.table(TABLE_NAME).insert({"chat_id": chat_id, "url": url}).execute()
    except Exception as e:
        print(f"Error marking sent: {e}")

# ------------------- FETCHER -------------------
def fetch_rss_posts():
    all_posts = []
    
    for category, feeds in RSS_FEEDS_PRIORITY.items():
        for url in feeds:
            try:
                feed = feedparser.parse(url)
                
                for entry in feed.entries[:10]:
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
                        
            except Exception as e:
                print(f"Error fetching feed {url}: {e}")
                continue
    
    all_posts.sort(key=lambda x: x["published_parsed"], reverse=True)
    print(f"Fetched {len(all_posts)} new posts")
    return all_posts

# ------------------- ADAPTIVE FETCHER -------------------
def adaptive_fetcher():
    fetch_count = 0
    while running:
        try:
            with buffer_lock:
                if len(semi_fetch_buffer) < BUFFER_LOW_THRESHOLD:
                    new_posts = fetch_rss_posts()
                    if new_posts:
                        semi_fetch_buffer.extend(new_posts)
                        fetch_count += 1
                        
                        if fetch_count % 10 == 0:
                            print(f"[Fetcher] Completed {fetch_count} fetch cycles")
                            
        except Exception as e:
            print(f"[Fetcher Error]: {e}")
            
        time.sleep(FETCH_INTERVAL)

# ------------------- BATCH SENDER -------------------
def send_batch():
    send_count = 0
    while running:
        try:
            with buffer_lock:
                if semi_fetch_buffer:
                    batch = semi_fetch_buffer[:BATCH_SIZE]
                    del semi_fetch_buffer[:BATCH_SIZE]
                    
                    for post in batch:
                        msg = f"📘 **THOT SIGNAL** - {post['category']}\n**{post['title']}**\n{post['link']}"
                        try:
                            bot.send_message(USER_CHAT_ID, msg, parse_mode="Markdown")
                            mark_sent(USER_CHAT_ID, post["link"])
                            send_count += 1
                            print(f"Sent post: {post['title'][:50]}...")
                        except Exception as e:
                            print(f"Error sending message: {e}")
                        
                        time.sleep(PULSE_DELAY)
                    
                    time.sleep(BATCH_SEND_INTERVAL)
                else:
                    time.sleep(60)
                    
        except Exception as e:
            print(f"[Sender Error]: {e}")
            time.sleep(60)

# ------------------- STATUS LOOP -------------------
def status_loop():
    status_count = 0
    while running:
        time.sleep(STATUS_INTERVAL)
        try:
            with buffer_lock:
                buffer_size = len(semi_fetch_buffer)
            
            uptime_hours = (time.time() - start_time) // 3600
            status_msg = f"📘 THOT STATUS: {buffer_size} posts in buffer\n"
            status_msg += f"Uptime: {int(uptime_hours)} hours\n"
            status_msg += f"Last check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            bot.send_message(USER_CHAT_ID, status_msg)
            status_count += 1
            print(f"[Status] Sent status #{status_count}")
            
        except Exception as e:
            print(f"[Status Error]: {e}")

# ------------------- HEALTH MONITOR -------------------
def health_monitor():
    """Simple health monitor that logs every 5 minutes"""
    while running:
        try:
            with buffer_lock:
                buffer_size = len(semi_fetch_buffer)
            print(f"[Health] Buffer: {buffer_size}, Uptime: {(time.time() - start_time)/3600:.1f}h")
        except:
            pass
        time.sleep(300)

# ------------------- FLASK APP -------------------
app = Flask(__name__)
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL_BASE = os.environ.get("WEBHOOK_URL", "https://mintrox-bot-jp7h.onrender.com")
WEBHOOK_URL_PATH = f"/{TELEGRAM_TOKEN}"

@app.route("/")
def home():
    with buffer_lock:
        buffer_size = len(semi_fetch_buffer)
    
    uptime = int(time.time() - start_time)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60
    seconds = uptime % 60
    
    return f"""
    <html>
        <head>
            <title>📘 THOT RSS Bot</title>
            <meta http-equiv="refresh" content="30">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                .container {{ max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                h1 {{ color: #333; border-bottom: 3px solid #4CAF50; padding-bottom: 10px; }}
                .status {{ background: #e8f5e9; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .stat {{ margin: 10px 0; padding: 8px; background: #f9f9f9; border-left: 4px solid #4CAF50; }}
                .online {{ color: #4CAF50; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📘 THOT RSS Bot</h1>
                <div class="status">
                    <p>Status: <span class="online">✅ ONLINE</span></p>
                    <div class="stat">Buffer: <strong>{buffer_size}</strong> posts</div>
                    <div class="stat">Uptime: <strong>{hours}h {minutes}m {seconds}s</strong></div>
                    <div class="stat">Links sent: <strong>{restart_manager.get_sent_link_count():,}</strong></div>
                    <div class="stat">Last update: <strong>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</strong></div>
                </div>
                <p><a href="/health">Health Check</a> | Auto-refresh every 30s</p>
                <p><small>Service ID: {RENDER_SERVICE_ID}</small></p>
            </div>
        </body>
    </html>
    """

@app.route("/health")
def health():
    return "OK", 200

@app.route(WEBHOOK_URL_PATH, methods=["POST"])
def webhook():
    try:
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK"
    except Exception as e:
        print(f"Webhook error: {e}")
        return "ERROR", 500

# ------------------- TELEGRAM COMMANDS -------------------
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, 
        "📘 **THOT RSS Bot**\n\n"
        "**Commands:**\n"
        "/status - Check bot status\n"
        "/stats - Show statistics\n"
        "/restart - 🔥 Nuclear restart (admin only)\n\n"
        "**Note:** /restart triggers full service restart via Render API (30-45s downtime)"
    )

@bot.message_handler(commands=['status'])
def status_command(message):
    with buffer_lock:
        buffer_size = len(semi_fetch_buffer)
    
    uptime = int(time.time() - start_time)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60
    
    bot.reply_to(message, 
        f"📊 **THOT Status**\n"
        f"• Buffer: {buffer_size} posts\n"
        f"• Uptime: {hours}h {minutes}m\n"
        f"• Running: ✅\n"
        f"• Links sent: {restart_manager.get_sent_link_count():,}"
    )

@bot.message_handler(commands=['stats'])
def stats_command(message):
    with buffer_lock:
        buffer_size = len(semi_fetch_buffer)
    
    uptime = int(time.time() - start_time)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60
    feeds_count = sum(len(feeds) for feeds in RSS_FEEDS_PRIORITY.values())
    
    stats = f"""📊 **THOT Statistics**
• Posts in buffer: {buffer_size}
• Uptime: {hours}h {minutes}m
• Feeds monitored: {feeds_count}
• Links sent: {restart_manager.get_sent_link_count():,}
• Last check: {datetime.now().strftime('%H:%M:%S')}
"""
    bot.reply_to(message, stats)

@bot.message_handler(commands=['restart'])
def restart_command(message):
    """Nuclear restart command - triggers Render service restart"""
    user_id = str(message.chat.id)
    
    # Check authorization
    if user_id != str(USER_CHAT_ID):
        bot.reply_to(message, "❌ Unauthorized. This command is admin-only.")
        return
    
    # Check cooldown (10 minutes)
    current_time = time.time()
    if user_id in restart_cooldown:
        time_since_last = current_time - restart_cooldown[user_id]
        if time_since_last < RESTART_COOLDOWN_MINUTES * 60:
            minutes_left = int((RESTART_COOLDOWN_MINUTES * 60 - time_since_last) / 60) + 1
            bot.reply_to(message, 
                f"⏳ Cooldown active. Please wait {minutes_left} minute(s) before another nuclear restart."
            )
            return
    
    # Update cooldown
    restart_cooldown[user_id] = current_time
    
    # Send initial response
    init_msg = bot.reply_to(message, 
        "🚀 **Triggering Nuclear Restart...**\n"
        "• Service will restart in 30-45 seconds\n"
        "• All sent links preserved ✓\n"
        "• RSS monitoring will resume automatically\n\n"
        "_Processing..._"
    )
    
    # Trigger nuclear restart
    success, result = restart_manager.trigger_nuclear_restart(user_id)
    
    if success:
        # Edit the original message with success
        try:
            bot.edit_message_text(
                "✅ **Nuclear Restart Initiated!**\n"
                "• Render service restarting... (30-45s)\n"
                "• Bot will auto-resume with fresh state\n"
                "• You'll get a completion message shortly",
                chat_id=message.chat.id,
                message_id=init_msg.message_id
            )
        except:
            pass
    else:
        # Edit with error and manual option
        try:
            bot.edit_message_text(
                "❌ **Restart Failed**\n"
                f"Error: {result[:100]}...\n\n"
                "Try manual restart via Render dashboard.",
                chat_id=message.chat.id,
                message_id=init_msg.message_id
            )
        except:
            pass
        
        # Send detailed error with manual link
        restart_manager.send_error_with_manual_link(result, user_id)

# ------------------- INITIALIZATION -------------------
def initialize_bot():
    """Initialize bot and check for nuclear restart completion"""
    try:
        # Check if we just completed a nuclear restart
        restart_data = restart_manager.check_restart_flag()
        
        if restart_data:
            print(f"✅ Detected nuclear restart completion (triggered at {restart_data.get('triggered_at')})")
            # Send smart completion message
            time.sleep(3)  # Wait for everything to initialize
            restart_manager.send_smart_restart_completion(restart_data)
        else:
            # Normal startup message
            bot.send_message(USER_CHAT_ID, 
                "📘 **THOT is online and monitoring RSS feeds**\n"
                f"• Links preserved: {restart_manager.get_sent_link_count():,}\n"
                f"• Feeds: {sum(len(feeds) for feeds in RSS_FEEDS_PRIORITY.values())}\n"
                f"• Service: {RENDER_SERVICE_ID}"
            )
        
        # Set up webhook
        bot.remove_webhook()
        time.sleep(1)
        
        webhook_url = f"{WEBHOOK_URL_BASE}{WEBHOOK_URL_PATH}"
        print(f"Setting webhook to: {webhook_url}")
        bot.set_webhook(url=webhook_url)
        
        # Load initial posts
        initial_posts = fetch_rss_posts()
        if initial_posts:
            with buffer_lock:
                semi_fetch_buffer.extend(initial_posts)
            print(f"Loaded {len(initial_posts)} initial posts")
        
        print("✅ Bot initialized successfully")
                
    except Exception as e:
        print(f"Initialization error: {e}")
        traceback.print_exc()

# ------------------- START BACKGROUND THREADS -------------------
def start_background_threads():
    """Start all background threads as daemons"""
    threads = [
        threading.Thread(target=adaptive_fetcher, daemon=True, name="Fetcher"),
        threading.Thread(target=send_batch, daemon=True, name="Sender"),
        threading.Thread(target=status_loop, daemon=True, name="Status"),
        threading.Thread(target=health_monitor, daemon=True, name="Health")
    ]
    
    for thread in threads:
        thread.start()
        print(f"Started: {thread.name}")
    
    return threads

# ------------------- MAIN -------------------
if __name__ == "__main__":
    print(f"🚀 Starting THOT RSS Bot v2.0")
    print(f"📞 User Chat ID: {USER_CHAT_ID}")
    print(f"🔧 Render Service: {RENDER_SERVICE_ID}")
    print(f"🌐 Port: {PORT}")
    print(f"⏰ Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # Initialize bot
        initialize_bot()
        
        # Start background threads (daemon mode - won't block Flask)
        start_background_threads()
        
        print(f"✅ All systems started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📡 Starting Flask server on port {PORT}")
        print("🔧 Nuclear restart command: /restart")
        print("=" * 50)
        
        # Start Flask app - THIS MUST BE THE LAST LINE
        # Render will detect this port and mark service as healthy
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
        
    except KeyboardInterrupt:
        print("\n🛑 Received shutdown signal")
    except Exception as e:
        print(f"❌ Critical error: {e}")
        traceback.print_exc()
        if USER_CHAT_ID:
            try:
                bot.send_message(USER_CHAT_ID, f"❌ Critical error: {str(e)[:100]}")
            except:
                pass
