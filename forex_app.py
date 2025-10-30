"""
FOREX ALERT SYSTEM - ULTIMATE PROFESSIONAL EDITION v7.1
=======================================================
✅ DUAL API KEY SYSTEM - 1600 calls/day (800+800)
✅ Automatic instant fallback between API keys
✅ Reduced update interval: 6 minutes (was 8 minutes)
✅ Perfect smooth countdown timer
✅ Multi-user email support
✅ No cold starts with health check endpoint
✅ Enhanced with SL/TP, MT5/cTrader sections, R:R ratio

Version: 7.1 - DUAL API ENHANCED EDITION
Created by: Ali Musharaf
"""

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import json
import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dataclasses import dataclass, asdict
import logging
import os

try:
    import winsound
    SOUND_AVAILABLE = True
except ImportError:
    SOUND_AVAILABLE = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('forex_alerts.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

app = Flask(__name__)
CORS(app)

# API Configuration - DUAL API SYSTEM
API_UPDATE_INTERVAL = 360  # 6 minutes (reduced from 8 minutes)
TWELVE_DATA_API_KEY_PRIMARY = "b13108325be841eeb15c911c2f57fad7"
TWELVE_DATA_API_KEY_SECONDARY = "804b18fa137d4f03b2db55c353463bcc"

# Pakistan timezone offset (UTC+5)
PKT_OFFSET = timedelta(hours=5)

def get_pkt_now():
    """Get current time in Pakistan timezone (UTC+5)"""
    utc_now = datetime.now(timezone.utc)
    return utc_now + PKT_OFFSET

def get_next_5am_pkt():
    """Get next 5 AM PKT - TwelveData API reset time"""
    pkt_now = get_pkt_now()
    next_5am = pkt_now.replace(hour=5, minute=0, second=0, microsecond=0)
    
    # If current time is past 5 AM today, get tomorrow's 5 AM
    if pkt_now.hour >= 5:
        next_5am += timedelta(days=1)
    
    return next_5am

# Supported Forex Pairs
FOREX_PAIRS = {
    'EUR/USD': 'EUR/USD', 'GBP/USD': 'GBP/USD', 'USD/JPY': 'USD/JPY',
    'USD/CHF': 'USD/CHF', 'AUD/USD': 'AUD/USD', 'NZD/USD': 'NZD/USD',
    'USD/CAD': 'USD/CAD', 'EUR/GBP': 'EUR/GBP', 'EUR/JPY': 'EUR/JPY',
    'GBP/JPY': 'GBP/JPY', 'AUD/JPY': 'AUD/JPY', 'NZD/JPY': 'NZD/JPY',
    'EUR/CHF': 'EUR/CHF', 'GBP/CHF': 'GBP/CHF', 'CAD/JPY': 'CAD/JPY',
    'EUR/AUD': 'EUR/AUD', 'EUR/CAD': 'EUR/CAD', 'GBP/AUD': 'GBP/AUD',
    'AUD/NZD': 'AUD/NZD', 'CHF/JPY': 'CHF/JPY'
}

@dataclass
class ForexAlert:
    pair: str
    target_price: float
    stop_loss_pips: int = 0  # NOW STORES PIPPETTES
    take_profit_pips: int = 0  # NOW STORES PIPPETTES
    baseline_price: float = 0.0
    current_price: float = 0.0
    direction: str = ""
    risk_reward_ratio: str = ""
    mt5_entry: float = 0.0
    mt5_sl: float = 0.0  # CALCULATED FROM PIPPETTES
    mt5_tp: float = 0.0  # CALCULATED FROM PIPPETTES
    ctrader_entry_pips: float = 0.0
    ctrader_sl_pips: int = 0
    ctrader_tp_pips: int = 0
    sound_frequency: int = 1500
    sound_duration: int = 800
    triggered: bool = False
    last_triggered: str = ""
    created_at: str = ""
    last_price_update: str = ""
    notes: str = ""
    
    # BACKWARD COMPATIBILITY - Accept old field names
    stop_loss: float = 0.0  # DEPRECATED
    take_profit: float = 0.0  # DEPRECATED
    
    def __post_init__(self):
        # BACKWARD COMPATIBILITY: Convert old format to new format
        if self.stop_loss > 0 and self.stop_loss_pips == 0:
            # Old alert loaded - convert price to pippettes
            self.stop_loss_pips = ForexAlert.calculate_pippettes_from_entry(
                self.target_price, self.stop_loss, self.pair
            )
        
        if self.take_profit > 0 and self.take_profit_pips == 0:
            # Old alert loaded - convert price to pippettes
            self.take_profit_pips = ForexAlert.calculate_pippettes_from_entry(
                self.target_price, self.take_profit, self.pair
            )
        
        if not self.created_at:
            self.created_at = get_pkt_now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Determine direction FIRST
        if self.baseline_price > 0 and self.direction == "":
            if self.target_price > self.baseline_price:
                self.direction = "up"  # LONG position
            else:
                self.direction = "down"  # SHORT position
        
        # CRITICAL: Calculate MT5 prices based on DIRECTION
        self.mt5_entry = self.target_price
        
        if self.stop_loss_pips > 0:
            if self.direction == "up":
                # LONG: SL is BELOW entry (subtract pips)
                self.mt5_sl = ForexAlert.calculate_price_from_pippettes(
                    self.target_price, self.stop_loss_pips, self.pair, subtract=True
                )
            else:
                # SHORT: SL is ABOVE entry (add pips)
                self.mt5_sl = ForexAlert.calculate_price_from_pippettes(
                    self.target_price, self.stop_loss_pips, self.pair, subtract=False
                )
        
        if self.take_profit_pips > 0:
            if self.direction == "up":
                # LONG: TP is ABOVE entry (add pips)
                self.mt5_tp = ForexAlert.calculate_price_from_pippettes(
                    self.target_price, self.take_profit_pips, self.pair, subtract=False
                )
            else:
                # SHORT: TP is BELOW entry (subtract pips)
                self.mt5_tp = ForexAlert.calculate_price_from_pippettes(
                    self.target_price, self.take_profit_pips, self.pair, subtract=True
                )
        
        # Calculate Risk:Reward ratio
        if self.mt5_entry > 0 and self.mt5_sl > 0 and self.mt5_tp > 0:
            risk = abs(self.mt5_entry - self.mt5_sl)
            reward = abs(self.mt5_tp - self.mt5_entry)
            if risk > 0:
                rr = reward / risk
                self.risk_reward_ratio = f"1:{rr:.2f}"
            else:
                self.risk_reward_ratio = "N/A"
        
        # cTrader values (same as entered)
        self.ctrader_entry_pips = self.target_price
        self.ctrader_sl_pips = self.stop_loss_pips
        self.ctrader_tp_pips = self.take_profit_pips
    
    @staticmethod
    def calculate_price_from_pippettes(entry_price: float, pippettes: int, pair: str, subtract: bool = False) -> float:
        """
        Convert pippettes to actual price - DIRECTION-AWARE
        
        Args:
            entry_price: The target/entry price
            pippettes: Number of pippettes (cTrader format)
            pair: Currency pair
            subtract: True to subtract, False to add
        
        Returns:
            Calculated price point
        """
        # Check if pair contains JPY
        if 'JPY' in pair.upper():
            # JPY pairs: 1 pippette = 0.001
            price_difference = pippettes * 0.001
        else:
            # Non-JPY pairs: 1 pippette = 0.00001
            price_difference = pippettes * 0.00001
        
        if subtract:
            calculated_price = entry_price - price_difference
        else:
            calculated_price = entry_price + price_difference
        
        # Round to appropriate decimal places
        if 'JPY' in pair.upper():
            return round(calculated_price, 3)  # JPY: 3 decimals
        else:
            return round(calculated_price, 5)  # Others: 5 decimals
    
    @staticmethod
    def calculate_pippettes_from_entry(entry_price, target_price, pair):
        """Calculate pippettes from price difference - PERFECT CALCULATION"""
        diff = abs(target_price - entry_price)
        
        if 'JPY' in pair.upper():
            # JPY pairs: divide by 0.001
            pippettes = round(diff / 0.001)
        else:
            # Non-JPY pairs: divide by 0.00001
            pippettes = round(diff / 0.00001)
        
        return pippettes

class EmailNotifier:
    """IMPROVED: Supports multiple email addresses"""
    def __init__(self):
        self.email_list: List[Dict[str, str]] = []
        self.enabled = False
        self.load_config()
    
    def load_config(self):
        try:
            if os.path.exists('email_config.json'):
                with open('email_config.json', 'r') as f:
                    config = json.load(f)
                    self.email_list = config.get('email_list', [])
                    self.enabled = config.get('enabled', False)
                    if self.enabled and self.email_list:
                        logging.info(f"📧 Loaded {len(self.email_list)} email(s) for notifications")
        except Exception as e:
            logging.error(f"Error loading email config: {e}")
    
    def save_config(self):
        try:
            config = {
                'email_list': self.email_list,
                'enabled': self.enabled
            }
            with open('email_config.json', 'w') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving email config: {e}")
    
    def add_email(self, sender_email: str, sender_password: str, name: str = ""):
        """Add a new email to the notification list"""
        for email_config in self.email_list:
            if email_config['email'] == sender_email:
                email_config['password'] = sender_password
                email_config['name'] = name
                self.save_config()
                logging.info(f"✅ Updated email: {sender_email}")
                return True
        
        self.email_list.append({
            'email': sender_email,
            'password': sender_password,
            'name': name or sender_email.split('@')[0]
        })
        self.enabled = True
        self.save_config()
        logging.info(f"✅ Added new email: {sender_email}")
        return True
    
    def remove_email(self, email_to_remove: str):
        """Remove an email from the notification list"""
        original_count = len(self.email_list)
        self.email_list = [e for e in self.email_list if e['email'] != email_to_remove]
        
        if len(self.email_list) < original_count:
            if len(self.email_list) == 0:
                self.enabled = False
            self.save_config()
            logging.info(f"🗑️ Removed email: {email_to_remove}")
            return True
        return False
    
    def send_alert(self, alert: ForexAlert):
        """Send alert to ALL configured emails"""
        if not self.enabled or not self.email_list:
            logging.warning("⚠️ Email not sent - no emails configured")
            return False
        
        success_count = 0
        
        for email_config in self.email_list:
            try:
                sender_email = email_config['email']
                sender_password = email_config['password']
                sender_name = email_config.get('name', 'Trader')
                
                logging.info(f"📧 Attempting to send email to: {sender_email}")
                
                subject = f"🚨💰 FOREX ALERT: {alert.pair} Target Reached!"
                
                body = f"""
╔═══════════════════════════════════════════════════════════╗
║          🎯 FOREX PRICE ALERT TRIGGERED! 🎯               ║
║              💰 TRADING OPPORTUNITY 💰                     ║
╚═══════════════════════════════════════════════════════════╝

Hi {sender_name},

📊 TRADE DETAILS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Forex Pair:       {alert.pair}
Direction:        {alert.direction.upper()} {('📈' if alert.direction == 'up' else '📉')}

💼 METATRADER 5 (MT5) EXACT PRICES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Entry Price:      {alert.mt5_entry:.5f} 🎯
Stop Loss:        {alert.mt5_sl:.5f} 🛡️
Take Profit:      {alert.mt5_tp:.5f} 💰
Current Price:    {alert.current_price:.5f} ✅

📊 cTRADER PIPPETTES (Input Values):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Entry (Decimal):   {alert.ctrader_entry_pips:.5f}
Stop Loss:         {alert.ctrader_sl_pips} pippettes 🛡️
Take Profit:       {alert.ctrader_tp_pips} pippettes 💰

⚖️ RISK MANAGEMENT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Risk:Reward Ratio: {alert.risk_reward_ratio}
Time Triggered:    {get_pkt_now().strftime("%Y-%m-%d %H:%M:%S")} PKT

{('📝 Notes: ' + alert.notes if alert.notes else '')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 COPY MT5 PRICES DIRECTLY TO YOUR PLATFORM!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Best regards,
Forex Alert System v7.1 - Smart Pippette Edition
Created by Ali Musharaf
                """
                
                message = MIMEMultipart()
                message['From'] = f"Forex Alerts <{sender_email}>"
                message['To'] = sender_email
                message['Subject'] = subject
                message.attach(MIMEText(body, 'plain'))
                
                logging.info(f"📤 Connecting to Gmail SMTP server...")
                with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                    server.set_debuglevel(1)  # Enable debug output
                    logging.info(f"🔐 Starting TLS...")
                    server.starttls()
                    logging.info(f"🔑 Logging in as {sender_email}...")
                    server.login(sender_email, sender_password)
                    logging.info(f"📧 Sending email...")
                    server.send_message(message)
                
                success_count += 1
                logging.info(f"✅ EMAIL SENT SUCCESSFULLY to {sender_email}")
                
            except smtplib.SMTPAuthenticationError as e:
                logging.error(f"❌ AUTHENTICATION FAILED for {sender_email}: {e}")
                logging.error(f"   Check: 1) App Password correct? 2) 2-Step Verification enabled?")
            except smtplib.SMTPException as e:
                logging.error(f"❌ SMTP ERROR for {sender_email}: {e}")
            except Exception as e:
                logging.error(f"❌ GENERAL ERROR sending to {email_config.get('email', 'unknown')}: {e}")
                logging.error(f"   Error type: {type(e).__name__}")
        
        if success_count > 0:
            logging.info(f"✅ Total emails sent successfully: {success_count}/{len(self.email_list)}")
            return True
        else:
            logging.error(f"❌ NO EMAILS SENT! All {len(self.email_list)} attempt(s) failed")
            return False

class ForexPriceMonitor:
    def __init__(self):
        self.alerts: List[ForexAlert] = []
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.alerts_file = "forex_alerts.json"
        self.email_notifier = EmailNotifier()
        self.load_alerts()
        self.recent_notifications = []
        self.last_api_call: Dict[str, datetime] = {}
        
        # DUAL API SYSTEM
        self.api_calls_primary = 0
        self.api_calls_secondary = 0
        self.current_api_key = TWELVE_DATA_API_KEY_PRIMARY
        self.using_primary = True
        
        self.api_calls_reset_time = get_next_5am_pkt()
        self.is_updating = False
        self.current_update_pair = ""
        
        logging.info(f"🔑 DUAL API SYSTEM INITIALIZED")
        logging.info(f"   Primary API: {TWELVE_DATA_API_KEY_PRIMARY[:8]}... (800 calls)")
        logging.info(f"   Secondary API: {TWELVE_DATA_API_KEY_SECONDARY[:8]}... (800 calls)")
        logging.info(f"   Total Daily Limit: 1600 calls")
        logging.info(f"⏱️  Update Interval: 6 minutes per pair")
        logging.info(f"🕐 API calls will reset at 5:00 AM PKT: {self.api_calls_reset_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    def switch_to_secondary_api(self):
        """Switch to secondary API key"""
        if not self.using_primary:
            return False
        
        self.using_primary = False
        self.current_api_key = TWELVE_DATA_API_KEY_SECONDARY
        logging.info("=" * 80)
        logging.info("🔄 AUTOMATICALLY SWITCHED TO SECONDARY API KEY")
        logging.info(f"   Reason: Primary API exhausted or returned error")
        logging.info(f"   Primary calls made: {self.api_calls_primary}")
        logging.info(f"   Now using Secondary API: {self.api_calls_secondary}/800")
        logging.info("=" * 80)
        return True
    
    def reset_to_primary_api(self):
        """Reset to primary API at 5 AM"""
        self.using_primary = True
        self.current_api_key = TWELVE_DATA_API_KEY_PRIMARY
        self.api_calls_primary = 0
        self.api_calls_secondary = 0
        logging.info("=" * 80)
        logging.info("🌅 5:00 AM PKT - API CREDITS REFRESHED!")
        logging.info("   ✅ Primary API: Reset to 0/800")
        logging.info("   ✅ Secondary API: Reset to 0/800")
        logging.info("   🔑 Now using: PRIMARY API (fresh start)")
        logging.info("=" * 80)
    
    def get_current_api_calls(self):
        """Get current API call count"""
        return self.api_calls_primary if self.using_primary else self.api_calls_secondary
    
    def get_total_api_calls(self):
        """Get total API calls used today"""
        return self.api_calls_primary + self.api_calls_secondary
    
    def get_price_twelvedata(self, pair: str) -> Optional[float]:
        try:
            # Check if primary API counter reached 800 and switch if needed
            if self.using_primary and self.api_calls_primary >= 800:
                logging.warning(f"⚠️ Primary API counter reached {self.api_calls_primary}/800")
                self.switch_to_secondary_api()
            
            # Check if both APIs counter reached limits
            if self.api_calls_primary >= 800 and self.api_calls_secondary >= 800:
                logging.error("❌ BOTH API KEYS EXHAUSTED! Waiting for 5:00 AM PKT reset.")
                return None
            
            url = f"https://api.twelvedata.com/price"
            params = {'symbol': pair, 'apikey': self.current_api_key}
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # CRITICAL: Check for ANY error response (even without "status": "error")
                # TwelveData can return errors in multiple formats
                
                # Check Method 1: Standard error format
                if 'status' in data and data['status'] == 'error':
                    error_msg = data.get('message', '').lower()
                    
                    if 'limit' in error_msg or 'quota' in error_msg or 'usage' in error_msg or 'exceeded' in error_msg:
                        logging.error(f"⚠️ API ERROR (status:error): {data.get('message')}")
                        if self.using_primary:
                            logging.warning(f"🚨 PRIMARY API FAILED - SWITCHING NOW!")
                            self.switch_to_secondary_api()
                            return self._retry_with_secondary(pair)
                        else:
                            logging.error("❌ Secondary API also exhausted. Wait for 5 AM reset.")
                            return None
                
                # Check Method 2: Error code in response (no "status" field)
                if 'code' in data:
                    code = data.get('code')
                    message = data.get('message', '').lower()
                    
                    # Common error codes: 429 (rate limit), 403 (forbidden), 401 (unauthorized)
                    if code in [429, 403, 401] or 'limit' in message or 'quota' in message or 'exceeded' in message:
                        logging.error(f"⚠️ API ERROR (code {code}): {data.get('message')}")
                        if self.using_primary:
                            logging.warning(f"🚨 PRIMARY API FAILED - SWITCHING NOW!")
                            self.switch_to_secondary_api()
                            return self._retry_with_secondary(pair)
                        else:
                            logging.error("❌ Secondary API also exhausted. Wait for 5 AM reset.")
                            return None
                
                # Check Method 3: No price returned (indication of limit)
                if 'price' not in data:
                    logging.warning(f"⚠️ No price in response (possible limit): {data}")
                    
                    # If we're using primary and got no price, try secondary
                    if self.using_primary:
                        logging.warning(f"🚨 PRIMARY API returned no price - SWITCHING NOW!")
                        self.switch_to_secondary_api()
                        return self._retry_with_secondary(pair)
                    else:
                        logging.error(f"❌ Secondary API also failed: {data}")
                        return None
                
                # Success - got price
                if 'price' in data:
                    price = float(data['price'])
                    
                    # Increment the correct counter
                    if self.using_primary:
                        self.api_calls_primary += 1
                        api_status = f"Primary {self.api_calls_primary}/800"
                    else:
                        self.api_calls_secondary += 1
                        api_status = f"Secondary {self.api_calls_secondary}/800"
                    
                    total_calls = self.get_total_api_calls()
                    logging.info(f"✅ {pair} = {price:.5f} | {api_status} | Total: {total_calls}/1600")
                    return price
                    
            else:
                # HTTP error codes (404, 500, etc.)
                logging.error(f"⚠️ HTTP {response.status_code}: {response.text}")
                if self.using_primary and response.status_code in [429, 403, 401]:
                    logging.warning(f"🚨 PRIMARY API HTTP ERROR - SWITCHING NOW!")
                    self.switch_to_secondary_api()
                    return self._retry_with_secondary(pair)
                return None
                
        except Exception as e:
            logging.error(f"❌ Exception for {pair}: {e}")
            return None
        
        return None
    
    def _retry_with_secondary(self, pair: str) -> Optional[float]:
        """Retry the same request with secondary API"""
        try:
            url = f"https://api.twelvedata.com/price"
            params = {'symbol': pair, 'apikey': self.current_api_key}  # Already switched to secondary
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if 'price' in data:
                    price = float(data['price'])
                    self.api_calls_secondary += 1
                    logging.info(f"✅ RETRY SUCCESS with Secondary: {pair} = {price:.5f} | Secondary {self.api_calls_secondary}/800")
                    return price
            
            logging.error(f"❌ Secondary API retry failed for {pair}")
            return None
            
        except Exception as e:
            logging.error(f"❌ Secondary retry exception: {e}")
            return None
    
    def fetch_initial_price(self, pair: str) -> Optional[float]:
        """Fetch baseline price - NOW WITH INSTANT CACHE"""
        logging.info(f"🔍 Fetching baseline price for {pair}...")
        
        # Try to get cached recent price first (within last 10 minutes)
        if pair in self.last_api_call:
            time_since_last = (get_pkt_now() - self.last_api_call[pair]).total_seconds()
            if time_since_last < 600:  # Less than 10 minutes
                # Find current price from existing alerts
                for alert in self.alerts:
                    if alert.pair == pair and alert.current_price > 0:
                        logging.info(f"⚡ INSTANT: Using cached price for {pair} = {alert.current_price:.5f}")
                        return alert.current_price
        
        # Otherwise fetch new price
        price = self.get_price_twelvedata(pair)
        
        if price:
            self.last_api_call[pair] = get_pkt_now()
            logging.info(f"✅ Baseline price set: {pair} = {price:.5f}")
        else:
            logging.error(f"❌ Failed to fetch baseline price for {pair}")
        
        return price
    
    def should_update_price(self, pair: str) -> bool:
        if pair not in self.last_api_call:
            return True
        
        elapsed = (get_pkt_now() - self.last_api_call[pair]).total_seconds()
        return elapsed >= API_UPDATE_INTERVAL
    
    def get_seconds_until_next_update(self) -> int:
        if not self.last_api_call:
            return 0
        
        now = get_pkt_now()
        next_updates = []
        
        active_pairs = set()
        for alert in self.alerts:
            if not alert.triggered:
                active_pairs.add(alert.pair)
        
        for pair in active_pairs:
            if pair in self.last_api_call:
                last_call = self.last_api_call[pair]
                next_update_time = last_call + timedelta(seconds=API_UPDATE_INTERVAL)
                seconds_until = (next_update_time - now).total_seconds()
                
                if seconds_until < 0:
                    seconds_until = 0
                
                next_updates.append(seconds_until)
        
        if next_updates:
            earliest = min(next_updates)
            return max(0, int(earliest))
        
        return 0
    
    def update_all_prices(self):
        active_alerts = [a for a in self.alerts if not a.triggered]
        if not active_alerts:
            return
        
        pairs_to_update = []
        for alert in active_alerts:
            if self.should_update_price(alert.pair) and alert.pair not in pairs_to_update:
                pairs_to_update.append(alert.pair)
        
        if not pairs_to_update:
            return
        
        logging.info(f"📊 Starting price update cycle for {len(pairs_to_update)} pairs...")
        
        for pair in pairs_to_update:
            try:
                self.is_updating = True
                self.current_update_pair = pair
                
                logging.info(f"🔄 Fetching price for {pair}...")
                price = self.get_price_twelvedata(pair)
                
                if price:
                    self.last_api_call[pair] = get_pkt_now()
                    
                    for alert in active_alerts:
                        if alert.pair == pair:
                            old_price = alert.current_price
                            alert.current_price = price
                            alert.last_price_update = get_pkt_now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            logging.info(f"   📈 {pair}: {old_price:.5f} → {price:.5f}")
                            
                            if self.check_price_crossed(alert):
                                self.trigger_alert(alert)
                                logging.info(f"   ⚡ INSTANT TRIGGER: {alert.pair} triggered!")
                    
                    self.save_alerts()
                    time.sleep(0.5)
                
                else:
                    logging.warning(f"❌ Failed to fetch price for {pair}")
                
            except Exception as e:
                logging.error(f"Error updating {pair}: {e}")
            finally:
                self.current_update_pair = ""
        
        self.is_updating = False
        logging.info(f"✅ Price update cycle completed!\n")
    
    def check_price_crossed(self, alert: ForexAlert) -> bool:
        if alert.current_price == 0 or alert.baseline_price == 0:
            return False
        
        if alert.direction == "up":
            return alert.current_price >= alert.target_price
        elif alert.direction == "down":
            return alert.current_price <= alert.target_price
        
        return False
    
    def add_alert(self, pair: str, target_price: float, stop_loss_pips: int = 0, 
                  take_profit_pips: int = 0, notes: str = "") -> Optional[ForexAlert]:
        if pair not in FOREX_PAIRS:
            return None
        
        baseline_price = self.fetch_initial_price(pair)
        
        if baseline_price is None:
            logging.error(f"❌ Cannot create alert - failed to fetch baseline price")
            return None
        
        alert = ForexAlert(
            pair=pair,
            target_price=target_price,
            stop_loss_pips=stop_loss_pips,  # NOW PIPPETTES
            take_profit_pips=take_profit_pips,  # NOW PIPPETTES
            baseline_price=baseline_price,
            current_price=baseline_price,
            notes=notes
        )
        
        alert.last_price_update = get_pkt_now().strftime("%Y-%m-%d %H:%M:%S")
        
        self.alerts.append(alert)
        self.save_alerts()
        
        logging.info(f"✅ Alert added: {alert.pair}")
        logging.info(f"   Target: {alert.target_price:.5f}")
        logging.info(f"   SL Pips: {alert.stop_loss_pips} → MT5 Price: {alert.mt5_sl:.5f}")
        logging.info(f"   TP Pips: {alert.take_profit_pips} → MT5 Price: {alert.mt5_tp:.5f}")
        logging.info(f"   R:R: {alert.risk_reward_ratio}")
        
        if not self.running and len(self.alerts) > 0:
            self.start_monitoring()
            logging.info("🚀 Auto-started monitoring!")
        
        return alert
    
    def remove_alert(self, index: int) -> bool:
        if 0 <= index < len(self.alerts):
            removed = self.alerts.pop(index)
            self.save_alerts()
            logging.info(f"🗑️ Alert removed: {removed.pair}")
            return True
        return False
    
    def trigger_alert(self, alert: ForexAlert):
        alert.triggered = True
        alert.last_triggered = get_pkt_now().strftime("%Y-%m-%d %H:%M:%S")
        self.save_alerts()
        
        if SOUND_AVAILABLE:
            try:
                for _ in range(5):
                    winsound.Beep(alert.sound_frequency, alert.sound_duration)
                    time.sleep(0.1)
            except:
                pass
        
        notification = {
            'pair': alert.pair,
            'baseline_price': alert.baseline_price,
            'target_price': alert.target_price,
            'current_price': alert.current_price,
            'direction': alert.direction,
            'stop_loss': alert.stop_loss,
            'take_profit': alert.take_profit,
            'risk_reward_ratio': alert.risk_reward_ratio,
            'mt5_entry': alert.mt5_entry,
            'mt5_sl': alert.mt5_sl,
            'mt5_tp': alert.mt5_tp,
            'ctrader_entry_pips': alert.ctrader_entry_pips,
            'ctrader_sl_pips': alert.ctrader_sl_pips,
            'ctrader_tp_pips': alert.ctrader_tp_pips,
            'time': alert.last_triggered,
            'notes': alert.notes
        }
        self.recent_notifications.insert(0, notification)
        if len(self.recent_notifications) > 50:
            self.recent_notifications = self.recent_notifications[:50]
        
        self.email_notifier.send_alert(alert)
        
        logging.info(f"🚨 ALERT TRIGGERED: {alert.pair}")
    
    def monitor_prices(self):
        logging.info("▶️ Forex monitoring started")
        logging.info(f"📊 DUAL API System: 1600 calls/day (Primary 800 + Secondary 800)")
        logging.info(f"⏱️  Update Interval: 6 minutes per pair")
        logging.info(f"🕐 Timezone: Pakistan Time (PKT - UTC+5)")
        logging.info(f"🌅 API Reset Time: 5:00 AM PKT daily\n")
        
        while self.running:
            try:
                pkt_now = get_pkt_now()
                
                # Check if it's 5 AM PKT - API credits refresh
                if pkt_now >= self.api_calls_reset_time:
                    self.reset_to_primary_api()
                    self.api_calls_reset_time = get_next_5am_pkt()
                    logging.info(f"🔄 Next reset scheduled: {self.api_calls_reset_time.strftime('%Y-%m-%d %H:%M:%S')} PKT\n")
                
                self.update_all_prices()
                time.sleep(2)
                
            except Exception as e:
                logging.error(f"❌ Monitor error: {e}")
                time.sleep(3)
        
        logging.info("⏸️ Monitoring stopped")
    
    def start_monitoring(self):
        if self.running:
            return False
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitor_prices, daemon=True)
        self.monitor_thread.start()
        logging.info("🚀 Monitoring thread started!")
        return True
    
    def stop_monitoring(self):
        if not self.running:
            return False
        
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        return True
    
    def save_alerts(self):
        """Save alerts with AUTOMATIC BACKUP"""
        try:
            # Save main file
            with open(self.alerts_file, 'w') as f:
                json.dump([asdict(alert) for alert in self.alerts], f, indent=4)
            
            # CRITICAL: Create backup file
            backup_file = self.alerts_file.replace('.json', '_BACKUP.json')
            with open(backup_file, 'w') as f:
                json.dump([asdict(alert) for alert in self.alerts], f, indent=4)
            
            # CRITICAL: Create timestamped backup
            timestamp = get_pkt_now().strftime("%Y%m%d")
            daily_backup = f"forex_alerts_backup_{timestamp}.json"
            with open(daily_backup, 'w') as f:
                json.dump([asdict(alert) for alert in self.alerts], f, indent=4)
                
        except Exception as e:
            logging.error(f"Error saving alerts: {e}")
    
    def load_alerts(self):
        """Load alerts with AUTOMATIC RECOVERY"""
        try:
            # Try main file first
            if os.path.exists(self.alerts_file):
                with open(self.alerts_file, 'r') as f:
                    data = json.load(f)
                    self.alerts = [ForexAlert(**item) for item in data]
                    logging.info(f"📂 Loaded {len(self.alerts)} alerts from main file")
                    return
        except Exception as e:
            logging.error(f"⚠️ Error loading main file: {e}")
        
        # Try backup file
        try:
            backup_file = self.alerts_file.replace('.json', '_BACKUP.json')
            if os.path.exists(backup_file):
                with open(backup_file, 'r') as f:
                    data = json.load(f)
                    self.alerts = [ForexAlert(**item) for item in data]
                    logging.info(f"📂 RECOVERED {len(self.alerts)} alerts from BACKUP!")
                    # Restore main file
                    self.save_alerts()
                    return
        except Exception as e:
            logging.error(f"⚠️ Error loading backup: {e}")
        
        # Try daily backup
        try:
            timestamp = get_pkt_now().strftime("%Y%m%d")
            daily_backup = f"forex_alerts_backup_{timestamp}.json"
            if os.path.exists(daily_backup):
                with open(daily_backup, 'r') as f:
                    data = json.load(f)
                    self.alerts = [ForexAlert(**item) for item in data]
                    logging.info(f"📂 RECOVERED {len(self.alerts)} alerts from DAILY BACKUP!")
                    self.save_alerts()
                    return
        except Exception as e:
            logging.error(f"⚠️ Error loading daily backup: {e}")
        
        logging.warning("⚠️ No alerts found in any backup files")

monitor = ForexPriceMonitor()

# Flask Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/pairs')
def get_pairs():
    return jsonify(list(FOREX_PAIRS.keys()))

@app.route('/api/alerts')
def get_alerts():
    alerts_data = []
    for idx, alert in enumerate(monitor.alerts):
        alerts_data.append({
            'index': idx,
            'pair': alert.pair,
            'baseline_price': alert.baseline_price,
            'target_price': alert.target_price,
            'stop_loss_pips': alert.stop_loss_pips,  # PIPPETTES
            'take_profit_pips': alert.take_profit_pips,  # PIPPETTES
            'current_price': alert.current_price,
            'direction': alert.direction,
            'risk_reward_ratio': alert.risk_reward_ratio,
            'mt5_entry': alert.mt5_entry,
            'mt5_sl': alert.mt5_sl,  # CALCULATED PRICE
            'mt5_tp': alert.mt5_tp,  # CALCULATED PRICE
            'ctrader_entry_pips': alert.ctrader_entry_pips,
            'ctrader_sl_pips': alert.ctrader_sl_pips,
            'ctrader_tp_pips': alert.ctrader_tp_pips,
            'triggered': alert.triggered,
            'created_at': alert.created_at,
            'last_triggered': alert.last_triggered,
            'last_price_update': alert.last_price_update,
            'notes': alert.notes
        })
    return jsonify(alerts_data)

@app.route('/api/add_alert', methods=['POST'])
def add_alert():
    try:
        data = request.json
        logging.info(f"📥 Received alert request: {data}")
        
        pair = data.get('pair')
        target_price = data.get('target_price')
        stop_loss_pips = data.get('stop_loss_pips')
        take_profit_pips = data.get('take_profit_pips')
        notes = data.get('notes', '')
        
        # Validate inputs
        if not pair:
            return jsonify({'success': False, 'message': 'Pair is required'}), 400
        
        if not target_price:
            return jsonify({'success': False, 'message': 'Target price is required'}), 400
        
        # Convert to proper types
        try:
            target_price = float(target_price)
            stop_loss_pips = int(stop_loss_pips) if stop_loss_pips else 0
            take_profit_pips = int(take_profit_pips) if take_profit_pips else 0
        except (ValueError, TypeError) as e:
            logging.error(f"❌ Conversion error: {e}")
            return jsonify({'success': False, 'message': f'Invalid number format: {e}'}), 400
        
        logging.info(f"✅ Validated: {pair} @ {target_price}, SL: {stop_loss_pips}, TP: {take_profit_pips}")
        
        # Add alert
        alert = monitor.add_alert(pair, target_price, stop_loss_pips, take_profit_pips, notes)
        
        if alert:
            logging.info(f"✅ Alert created successfully")
            return jsonify({
                'success': True,
                'message': 'Alert added! MT5 prices calculated from pippettes!',
                'baseline_price': alert.baseline_price,
                'direction': alert.direction,
                'risk_reward_ratio': alert.risk_reward_ratio,
                'mt5_entry': alert.mt5_entry,
                'mt5_sl': alert.mt5_sl,
                'mt5_tp': alert.mt5_tp,
                'ctrader_entry_pips': alert.ctrader_entry_pips,
                'ctrader_sl_pips': alert.ctrader_sl_pips,
                'ctrader_tp_pips': alert.ctrader_tp_pips
            })
        else:
            logging.error(f"❌ Alert creation returned None")
            return jsonify({'success': False, 'message': 'Failed to fetch baseline price - API error'}), 400
            
    except Exception as e:
        logging.error(f"❌ EXCEPTION in add_alert: {type(e).__name__}: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'}), 500

@app.route('/api/remove_alert/<int:index>', methods=['DELETE'])
def remove_alert(index):
    if monitor.remove_alert(index):
        return jsonify({'success': True})
    return jsonify({'success': False}), 400

@app.route('/api/reset_alert/<int:index>', methods=['POST'])
def reset_alert(index):
    if 0 <= index < len(monitor.alerts):
        monitor.alerts[index].triggered = False
        monitor.save_alerts()
        return jsonify({'success': True})
    return jsonify({'success': False}), 400

@app.route('/api/start_monitoring', methods=['POST'])
def start_monitoring():
    if monitor.start_monitoring():
        return jsonify({'success': True, 'message': 'Monitoring started!'})
    return jsonify({'success': False, 'message': 'Already running'}), 400

@app.route('/api/stop_monitoring', methods=['POST'])
def stop_monitoring():
    if monitor.stop_monitoring():
        return jsonify({'success': True, 'message': 'Monitoring stopped!'})
    return jsonify({'success': False, 'message': 'Not running'}), 400

@app.route('/api/status')
def get_status():
    seconds_until_update = monitor.get_seconds_until_next_update()
    minutes = seconds_until_update // 60
    seconds = seconds_until_update % 60
    
    pkt_now = get_pkt_now()
    
    # Determine which API is active
    api_status = "Primary" if monitor.using_primary else "Secondary"
    primary_calls = monitor.api_calls_primary
    secondary_calls = monitor.api_calls_secondary
    total_calls = monitor.get_total_api_calls()
    
    return jsonify({
        'running': monitor.running,
        'alert_count': len(monitor.alerts),
        'active_alerts': sum(1 for a in monitor.alerts if not a.triggered),
        'email_configured': monitor.email_notifier.enabled,
        'email_count': len(monitor.email_notifier.email_list),
        'api_calls_today': total_calls,
        'api_limit': 1600,
        'api_calls_primary': primary_calls,
        'api_calls_secondary': secondary_calls,
        'api_status': api_status,
        'using_primary': monitor.using_primary,
        'next_update_seconds': seconds_until_update,
        'next_update_display': f"{minutes}m {seconds}s",
        'is_updating': monitor.is_updating,
        'current_update_pair': monitor.current_update_pair,
        'server_time_pkt': pkt_now.strftime("%Y-%m-%d %H:%M:%S"),
        'next_reset_time': monitor.api_calls_reset_time.strftime("%Y-%m-%d %H:%M:%S")
    })

@app.route('/api/configure_email', methods=['POST'])
def configure_email():
    data = request.json
    name = data.get('name', '')
    monitor.email_notifier.add_email(data['email'], data['password'], name)
    return jsonify({
        'success': True, 
        'message': f'Email added! Total: {len(monitor.email_notifier.email_list)} email(s) configured',
        'email_count': len(monitor.email_notifier.email_list)
    })

@app.route('/api/remove_email', methods=['POST'])
def remove_email():
    """Remove an email from the notification list"""
    data = request.json
    email_to_remove = data.get('email')
    if monitor.email_notifier.remove_email(email_to_remove):
        return jsonify({
            'success': True,
            'message': f'Email removed! Remaining: {len(monitor.email_notifier.email_list)} email(s)',
            'email_count': len(monitor.email_notifier.email_list)
        })
    return jsonify({'success': False, 'message': 'Email not found'}), 400

@app.route('/api/get_emails', methods=['GET'])
def get_emails():
    """Get list of all configured emails (without passwords)"""
    emails = [{'email': e['email'], 'name': e.get('name', 'Unknown')} 
              for e in monitor.email_notifier.email_list]
    return jsonify({'emails': emails, 'count': len(emails)})

@app.route('/api/notifications')
def get_notifications():
    return jsonify(monitor.recent_notifications[:10])

@app.route('/health')
def health_check():
    """Health check endpoint - prevents cold starts when pinged by UptimeRobot"""
    return jsonify({
        'status': 'healthy',
        'app': 'Forex Alert System v7.1 - DUAL API EDITION',
        'running': monitor.running,
        'alerts': len(monitor.alerts),
        'active_alerts': sum(1 for a in monitor.alerts if not a.triggered),
        'api_system': 'dual',
        'total_api_limit': 1600,
        'api_calls_primary': monitor.api_calls_primary,
        'api_calls_secondary': monitor.api_calls_secondary,
        'api_calls_total': monitor.get_total_api_calls(),
        'using_api': 'primary' if monitor.using_primary else 'secondary',
        'update_interval': '6 minutes',
        'uptime': 'always_on'
    })

if __name__ == '__main__':
    os.makedirs('templates', exist_ok=True)
    
    if monitor.alerts:
        monitor.start_monitoring()
        print("✅ Auto-started monitoring")
    
    print("\n" + "="*80)
    print("💱 FOREX ALERT SYSTEM - DUAL API ENHANCED EDITION v7.1")
    print("="*80)
    print("🌐 Server starting...")
    print("🔑 DUAL API SYSTEM:")
    print(f"   ├─ Primary API:   {TWELVE_DATA_API_KEY_PRIMARY[:8]}... (800 calls/day)")
    print(f"   └─ Secondary API: {TWELVE_DATA_API_KEY_SECONDARY[:8]}... (800 calls/day)")
    print("📊 Total Daily Limit: 1600 API calls")
    print("⏱️  Update Interval: 6 minutes per pair")
    print("🌅 API Reset Time: 5:00 AM PKT (TwelveData refresh)")
    print("📧 Multi-email support enabled")
    print("⚡ SMART ERROR-BASED INSTANT FALLBACK")
    print("   - Detects API errors in real-time")
    print("   - Switches immediately on quota errors")
    print("   - No disruption in monitoring")
    print("🎯 Perfect smooth countdown timer")
    print("🕐 Timezone: Pakistan Time (PKT - UTC+5)")
    print("="*80 + "\n")
    print("✅ Created by: Ali Musharaf")
    print("="*80 + "\n")
    
    # CRITICAL: Read PORT from environment for Render/Cloud deployment
    port = int(os.environ.get('PORT', 5000))
    print(f"🌐 Starting server on http://localhost:{port}")
    print(f"🌐 Also accessible at: http://127.0.0.1:{port}")
    print("="*80 + "\n")
    print("Press CTRL+C to stop\n")
    
    app.run(debug=False, host='0.0.0.0', port=port, use_reloader=False)
