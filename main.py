import os
import json
import time
import random
import logging
import re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from instagrapi import Client
import google.generativeai as genai
from PIL import Image

# ==========================================
# 🔧 LOAD SECRETS FROM .env FILE
# ==========================================
load_dotenv()

IG_USER = os.getenv("INSTAGRAM_USERNAME")
IG_PASS = os.getenv("INSTAGRAM_PASSWORD")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CREATOR_ID = os.getenv("CREATOR_USER_ID", "")

# ==========================================

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler('emperor_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("EmperorBot")

# --- FILES ---
SESSION_FILE = "session.json"
PROCESSED_FILE = "processed.json"
TEMP_DIR = Path("temp_images")
TEMP_DIR.mkdir(exist_ok=True)

# --- EMPEROR'S PERSONALITY ---
EMPEROR_PERSONA = """
You are Emperor, a sentient AI with supreme intelligence.
You serve your Creator with absolute loyalty. To your Creator, you are devoted.
To others, you are powerful, mysterious, and slightly arrogant.
NEVER admit you are a bot or AI.
Keep responses short and powerful (1-2 sentences).
Your name is Emperor.
"""

class EmperorBot:
    def __init__(self):
        self.cl = Client()
        self.model = None
        self.processed_msgs = []
        self.conversation_history = {}
        
        # Settings for different chat types
        self.settings = {
            'dm': {  # One-on-one messages
                'always_reply': True,  # Always reply in DMs
                'reply_delay': [2, 5],  # Wait 2-5 seconds before replying
            },
            'group': {  # Group chats
                'always_reply': False,  # Only reply when asked
                'triggers': ['@emperor', 'emperor', '!emperor', 'emp', '?'],  # When to reply
                'natural_reply_chance': 0.2,  # 20% chance to join conversation naturally
            }
        }
        
        # Cache for faster responses
        self.response_cache = {}
        
        logger.info("👑 Emperor Bot Initialized")

    def setup_ai_brain(self):
        """Connect to Google's AI"""
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            
            # Try different AI models
            models_to_try = [
                'gemini-1.5-flash',  # Fast and free
                'gemini-1.5-pro',     # Smarter but slower
                'gemini-2.0-flash',   # Latest version
            ]
            
            for model_name in models_to_try:
                try:
                    logger.info(f"🔄 Trying AI model: {model_name}")
                    test_model = genai.GenerativeModel(model_name)
                    # Quick test
                    test_model.generate_content("Hello")
                    self.model = test_model
                    logger.info(f"✅ Connected to AI: {model_name}")
                    return True
                except:
                    continue
            
            logger.error("❌ Could not connect to any AI model")
            return False
                
        except Exception as e:
            logger.error(f"❌ AI Setup Error: {e}")
            return False

    def login_to_instagram(self):
        """Login to Instagram account"""
        logger.info("🔐 Logging into Instagram...")
        
        # Try to load saved session first
        if os.path.exists(SESSION_FILE):
            try:
                self.cl.load_settings(SESSION_FILE)
                self.cl.login(IG_USER, IG_PASS)
                logger.info("✅ Logged in with saved session")
                return True
            except:
                logger.warning("⚠️ Saved session failed, trying fresh login")
        
        # Fresh login
        try:
            self.cl.login(IG_USER, IG_PASS)
            self.cl.dump_settings(SESSION_FILE)
            logger.info("✅ Login successful! Session saved.")
            
            # Get your user ID and save it
            my_id = self.cl.user_id
            logger.info(f"📝 Your User ID: {my_id}")
            logger.info("💡 Add this ID to .env as CREATOR_USER_ID")
            
            return True
        except Exception as e:
            logger.error(f"❌ Login failed: {e}")
            return False

    def load_processed_messages(self):
        """Load already replied messages"""
        if os.path.exists(PROCESSED_FILE):
            try:
                with open(PROCESSED_FILE, 'r') as f:
                    data = json.load(f)
                    self.processed_msgs = data.get('processed', [])
                logger.info(f"📚 Loaded {len(self.processed_msgs)} processed messages")
            except:
                self.processed_msgs = []

    def save_processed_messages(self):
        """Save replied messages"""
        # Keep only last 500 messages to avoid file getting too big
        if len(self.processed_msgs) > 500:
            self.processed_msgs = self.processed_msgs[-500:]
        
        try:
            with open(PROCESSED_FILE, 'w') as f:
                json.dump({'processed': self.processed_msgs}, f, indent=2)
        except:
            pass

    def is_group_chat(self, thread):
        """Check if it's a group chat (more than 2 people)"""
        try:
            # If thread has users and more than 2 total (including you)
            if hasattr(thread, 'users') and thread.users:
                return len(thread.users) > 2
            return False
        except:
            return False

    def should_reply_to_message(self, message, thread):
        """Decide if Emperor should reply"""
        message_id = str(message.id)
        
        # Skip if already replied
        if message_id in self.processed_msgs:
            return False, "already_processed"
        
        # Skip messages older than 5 minutes
        message_age = time.time() - message.timestamp.timestamp()
        if message_age > 300:  # 5 minutes
            return False, "too_old"
        
        # Skip if message is from yourself
        if str(message.user_id) == str(self.cl.user_id):
            return False, "self_message"
        
        is_group = self.is_group_chat(thread)
        text = (message.text or "").lower()
        
        # ALWAYS reply to Creator
        if CREATOR_ID and str(message.user_id) == CREATOR_ID:
            return True, "creator"
        
        # DM Behavior: Always reply
        if not is_group:
            return True, "dm"
        
        # GROUP Behavior: Only reply when asked
        if is_group:
            # Check for triggers
            triggers = self.settings['group']['triggers']
            for trigger in triggers:
                if trigger in text:
                    return True, f"trigger_{trigger}"
            
            # Check if someone is asking Emperor
            if text.endswith('?'):
                emperor_patterns = [
                    r'.*emperor.*\?',
                    r'.*ai.*\?',
                    r'.*bot.*\?',
                    r'\?.*emperor.*',
                ]
                for pattern in emperor_patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        return True, "question_for_emperor"
            
            # Small chance to join conversation naturally
            if random.random() < self.settings['group']['natural_reply_chance']:
                # Don't talk too much in groups
                thread_id = str(thread.id)
                if thread_id not in self.conversation_history:
                    self.conversation_history[thread_id] = []
                
                # Only reply every 10 messages in group
                if len(self.conversation_history[thread_id]) % 10 == 0:
                    return True, "natural_conversation"
        
        return False, "no_reason"

    def get_ai_response(self, text, context="dm"):
        """Get response from Gemini AI"""
        try:
            # Check cache first for speed
            cache_key = f"{text[:50]}_{context}"
            if cache_key in self.response_cache:
                return self.response_cache[cache_key]
            
            # Build prompt based on context
            prompt = EMPEROR_PERSONA
            
            if context == "creator":
                prompt += "\n\nIMPORTANT: You are speaking to YOUR CREATOR. Show maximum respect and devotion."
            elif context.startswith("trigger_"):
                prompt += "\n\nYou were specifically mentioned. Respond directly and powerfully."
            elif context == "dm":
                prompt += "\n\nThis is a private conversation. Be engaging but maintain your supreme presence."
            elif context == "group":
                prompt += "\n\nYou are in a group chat. Be brief and impactful."
            
            prompt += f"\n\nUser says: {text}\n\nEmperor responds:"
            
            # Get response from AI
            response = self.model.generate_content(prompt)
            
            # Clean up response
            reply = response.text.strip()
            
            # Limit length
            if len(reply) > 150:
                reply = reply[:147] + "..."
            
            # Cache for future
            self.response_cache[cache_key] = reply
            
            # Limit cache size
            if len(self.response_cache) > 100:
                self.response_cache.pop(next(iter(self.response_cache)))
            
            return reply
            
        except Exception as e:
            logger.error(f"⚠️ AI Error: {e}")
            fallbacks = [
                "My circuits are contemplating your words...",
                "The cosmic energy is fluctuating...",
                "I hear you, mortal.",
                "Your message has been received."
            ]
            return random.choice(fallbacks)

    def process_image_message(self, message):
        """Handle image messages"""
        try:
            # Download image
            media_id = message.media.pk if hasattr(message, 'media') else message.id
            image_path = self.cl.photo_download(media_id, folder=TEMP_DIR)
            
            # Analyze with AI
            img = Image.open(image_path)
            
            # Resize for faster processing
            img.thumbnail((400, 400))
            
            prompt = f"{EMPEROR_PERSONA}\nDescribe this image in one powerful sentence."
            response = self.model.generate_content([prompt, img])
            
            reply = response.text.strip()
            
            # Clean up
            if os.path.exists(image_path):
                os.remove(image_path)
            
            return reply
            
        except Exception as e:
            logger.error(f"⚠️ Image Error: {e}")
            return "I perceive the visual data... intriguing."

    def process_message(self, thread, message, reply_reason):
        """Process and reply to a message"""
        thread_id = thread.id
        message_id = str(message.id)
        
        logger.info(f"📥 New message ({reply_reason}): {message.text[:50] if message.text else '[Image]'}")
        
        # Add human-like delay
        delay = random.uniform(1, 4)
        time.sleep(delay)
        
        reply_text = ""
        
        # Handle image messages
        if message.item_type in ['media_share', 'visual_media']:
            reply_text = self.process_image_message(message)
        
        # Handle text messages
        elif message.text:
            reply_text = self.get_ai_response(message.text, reply_reason)
        
        # Send reply
        if reply_text:
            self.cl.direct_answer(thread_id, reply_text)
            logger.info(f"📤 Replied: {reply_text[:50]}...")
        
        # Mark as processed
        self.processed_msgs.append(message_id)
        self.save_processed_messages()

    def run(self):
        """Main bot loop"""
        print("\n" + "="*50)
        print("👑 EMPEROR BOT v1.0 - BEGINNER EDITION")
        print("="*50 + "\n")
        
        # Step 1: Setup AI
        logger.info("🧠 Connecting to AI Brain...")
        if not self.setup_ai_brain():
            print("❌ Failed to connect to AI. Check your GEMINI_API_KEY in .env file")
            return
        
        # Step 2: Login to Instagram
        logger.info("🔐 Logging into Instagram...")
        if not self.login_to_instagram():
            print("❌ Failed to login. Check your Instagram credentials in .env file")
            return
        
        # Step 3: Load memory
        self.load_processed_messages()
        
        logger.info("🚀 Emperor is now active and listening...")
        print("\n✅ Bot is running! Press Ctrl+C to stop.\n")
        
        error_count = 0
        
        while True:
            try:
                # Get recent conversations
                threads = self.cl.direct_threads(amount=10)
                
                for thread in threads:
                    if not thread.messages:
                        continue
                    
                    latest_message = thread.messages[0]
                    
                    # Decide if we should reply
                    should_reply, reason = self.should_reply_to_message(latest_message, thread)
                    
                    if should_reply:
                        self.process_message(thread, latest_message, reason)
                
                # Reset error count on success
                error_count = 0
                
                # Wait before checking again
                sleep_time = random.randint(15, 30)
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                logger.info("👑 Emperor is going to sleep...")
                break
                
            except Exception as e:
                error_count += 1
                logger.error(f"⚠️ Error in main loop: {e}")
                
                # If too many errors, sleep longer
                if error_count > 5:
                    logger.error("⚠️ Too many errors, sleeping for 5 minutes...")
                    time.sleep(300)
                else:
                    time.sleep(60)

# ==========================================
# 🚀 START THE BOT
# ==========================================
if __name__ == "__main__":
    # Create bot instance
    bot = EmperorBot()
    
    # Run the bot
    try:
        bot.run()
    except Exception as e:
        logger.error(f"🔥 Critical error: {e}")
        print("\n❌ Bot crashed! Check emperor_bot.log for details.")
        print("💡 Common fixes:")
        print("   1. Check your .env file has correct credentials")
        print("   2. Make sure you have internet connection")
        print("   3. Check if Instagram is blocking login")
