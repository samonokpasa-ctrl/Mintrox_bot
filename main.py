    print("🔬 TESTING RSS FEEDS")
    print("="*60)
    
    working_feeds = []
    
    for feed_url in TEST_FEEDS:
        print(f"\n📡 Testing: {feed_url}")
        try:
            # Test if URL is accessible
            response = requests.get(feed_url, timeout=10)
            print(f"   HTTP Status: {response.status_code}")
            
            if response.status_code != 200:
                print(f"   ❌ HTTP Error: {response.status_code}")
                continue
                
            # Parse feed
            feed = feedparser.parse(feed_url)
            
            if hasattr(feed, 'bozo') and feed.bozo:
                print(f"   ❌ Feed parsing error: {feed.bozo_exception}")
                continue
                
            if not feed.entries:
                print(f"   ⚠️  No entries found")
                continue
                
            print(f"   ✅ SUCCESS: Found {len(feed.entries)} entries")
            print(f"   📰 Sample: '{feed.entries[0].title[:80]}...'")
            print(f"   🔗 Link: {feed.entries[0].link[:100]}...")
            
            working_feeds.append(feed_url)
            
        except requests.RequestException as e:
            print(f"   ❌ Network error: {e}")
        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
    
    print("\n" + "="*60)
    print(f"📊 RESULTS: {len(working_feeds)}/{len(TEST_FEEDS)} feeds working")
    print("="*60)
    
    return working_feeds

# ------------------- WORKING FEEDS SETUP -------------------
def get_working_feeds():
    """Get only working feeds"""
    working = test_feeds()
    
    RSS_FEEDS_PRIORITY = {
        "Working Feeds": working
    }
    
    return RSS_FEEDS_PRIORITY

# ------------------- SIMPLE BOT -------------------
semi_fetch_buffer = []
buffer_lock = threading.Lock()

def fetch_rss_posts():
    """Fetch posts from working feeds"""
    print(f"\n🔄 [{datetime.now().strftime('%H:%M:%S')}] Fetching posts...")
    all_posts = []
    
    feeds_config = get_working_feeds()
    
    for category, feeds in feeds_config.items():
        for url in feeds:
            try:
                feed = feedparser.parse(url)
                
                for entry in feed.entries[:10]:  # Only recent 10
                    link = entry.get("link")
                    title = entry.get("title", "No Title")
                    
                    if link:
                        # Simple check - don't use database for testing
                        post = {
                            "title": title,
                            "link": link,
                            "category": category
                        }
                        all_posts.append(post)
                        print(f"   ✅ Found: {title[:60]}...")
                        
            except Exception as e:
                print(f"   ❌ Error with {url}: {e}")
    
    print(f"📥 Total new posts: {len(all_posts)}")
    return all_posts

def send_telegram_message(chat_id, text):
    """Send message to Telegram"""
    try:
        bot.send_message(chat_id, text, parse_mode="Markdown")
        print(f"✅ Sent: {text[:50]}...")
        return True
    except Exception as e:
        print(f"❌ Send failed: {e}")
        return False

def simple_fetcher():
    """Simple fetcher that runs every 2 minutes"""
    while True:
        try:
            with buffer_lock:
                if len(semi_fetch_buffer) < 5:  # Keep buffer filled
                    new_posts = fetch_rss_posts()
                    if new_posts:
                        semi_fetch_buffer.extend(new_posts)
                        print(f"📦 Buffer now has {len(semi_fetch_buffer)} posts")
        except Exception as e:
            print(f"Fetcher error: {e}")
        
        time.sleep(120)  # 2 minutes

def simple_sender():
    """Simple sender that sends every minute"""
    while True:
        try:
            with buffer_lock:
                if semi_fetch_buffer:
                    post = semi_fetch_buffer.pop(0)
                    msg = f"📘 **TEST POST**\n**{post['title']}**\n{post['link']}"
                    send_telegram_message(USER_CHAT_ID, msg)
                    print(f"📤 Sent post, buffer left: {len(semi_fetch_buffer)}")
                else:
                    print("😴 Buffer empty, waiting...")
        except Exception as e:
            print(f"Sender error: {e}")
        
        time.sleep(60)  # 1 minute

# ------------------- FLASK APP -------------------
app = Flask(__name__)
PORT = int(os.environ.get("PORT", 10000))

@app.route("/")
def home():
    with buffer_lock:
        buffer_size = len(semi_fetch_buffer)
    return {
        "status": "online", 
        "buffer": buffer_size,
        "message": "Debug bot running"
    }

@app.route("/test")
def test_feeds_route():
    """Test feeds via web request"""
    working_feeds = test_feeds()
    return {"working_feeds": working_feeds}

@app.route("/fetch_now")
def fetch_now():
    """Manual fetch"""
    new_posts = fetch_rss_posts()
    with buffer_lock:
        semi_fetch_buffer.extend(new_posts)
    return {"added": len(new_posts), "total_buffer": len(semi_fetch_buffer)}

@app.route("/send_now")
def send_now():
    """Manual send"""
    with buffer_lock:
        if semi_fetch_buffer:
            post = semi_fetch_buffer.pop(0)
            msg = f"📘 **MANUAL TEST**\n**{post['title']}**\n{post['link']}"
            success = send_telegram_message(USER_CHAT_ID, msg)
            return {"sent": success, "buffer_left": len(semi_fetch_buffer)}
        return {"sent": False, "error": "Buffer empty"}

# ------------------- MAIN -------------------
if __name__ == "__main__":
    print("🚀 Starting Debug RSS Bot...")
    
    # Send startup message
    send_telegram_message(USER_CHAT_ID, "🔧 Debug bot started. Testing feeds...")
    
    # Test feeds on startup
    working_feeds = test_feeds()
    
    # Initial fetch
    initial_posts = fetch_rss_posts()
    with buffer_lock:
        semi_fetch_buffer.extend(initial_posts)
    
    # Start threads
    threading.Thread(target=simple_fetcher, daemon=True).start()
    threading.Thread(target=simple_sender, daemon=True).start()
    
    print("🎉 Debug bot running! Use /test, /fetch_now, /send_now endpoints")
    
    app.run(host="0.0.0.0", port=PORT, debug=False)
