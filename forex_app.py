"""
FOREX ALERT SYSTEM - ULTIMATE PROFESSIONAL EDITION v7.0
=======================================================
✅ Multi-user email support (everyone gets notifications)
✅ No cold starts with health check endpoint
✅ Localhost and Render files stay separate
✅ PERFECT countdown timer - NEVER freezes
✅ Enhanced with SL/TP, MT5/cTrader sections, R:R ratio

Version: 7.0 - FINAL PERFECT EDITION
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

# API Configuration
API_UPDATE_INTERVAL = 480  # 8 minutes
TWELVE_DATA_API_KEY = "b13108325be841eeb15c911c2f57fad7"

# Pakistan timezone offset (UTC+5)
PKT_OFFSET = timedelta(hours=5)

def get_pkt_now():
    """Get current time in Pakistan timezone (UTC+5)"""
    utc_now = datetime.now(timezone.utc)
    return utc_now + PKT_OFFSET

def get_pkt_midnight():
    """Get next midnight in Pakistan timezone"""
    pkt_now = get_pkt_now()
    next_midnight = pkt_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return next_midnight

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
    stop_loss: float = 0.0
    take_profit: float = 0.0
    baseline_price: float = 0.0
    current_price: float = 0.0
    direction: str = ""
    risk_reward_ratio: str = ""
    mt5_entry: float = 0.0
    mt5_sl: float = 0.0
    mt5_tp: float = 0.0
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
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = get_pkt_now().strftime("%Y-%m-%d %H:%M:%S")
        
        if self.baseline_price > 0 and self.direction == "":
            if self.target_price > self.baseline_price:
                self.direction = "up"
            else:
                self.direction = "down"
        
        if self.target_price > 0 and self.stop_loss > 0 and self.take_profit > 0:
            risk = abs(self.target_price - self.stop_loss)
            reward = abs(self.take_profit - self.target_price)
            if risk > 0:
                rr = reward / risk
                self.risk_reward_ratio = f"1:{rr:.2f}"
            else:
                self.risk_reward_ratio = "N/A"
        
        self.mt5_entry = self.target_price
        self.mt5_sl = self.stop_loss
        self.mt5_tp = self.take_profit
        
        self.ctrader_entry_pips = self.target_price
        self.ctrader_sl_pips = ForexAlert.calculate_pippettes_from_entry(self.target_price, self.stop_loss, self.pair)
        self.ctrader_tp_pips = ForexAlert.calculate_pippettes_from_entry(self.target_price, self.take_profit, self.pair)
    
    @staticmethod
    def calculate_pippettes_from_entry(entry_price, target_price, pair):
        diff = abs(target_price - entry_price)
        
        if 'JPY' in pair:
            pippettes = round(diff * 1000)
        else:
            pippettes = round(diff * 100000)
        
        return pippettes

class EmailNotifier:
    """IMPROVED: Supports multiple email addresses"""
    def __init__(self):
        self.email_list: List[Dict[str, str]] = []  # List of {email, password, name}
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
        # Check if email already exists
        for email_config in self.email_list:
            if email_config['email'] == sender_email:
                # Update existing
                email_config['password'] = sender_password
                email_config['name'] = name
                self.save_config()
                logging.info(f"✅ Updated email: {sender_email}")
                return True
        
        # Add new email
        self.email_list.append({
            'email': sender_email,
            'password': sender_password,
            'name': name or sender_email.split('@')[0]
        })
        self.enabled = True
        self.save_config()
        logging.info(f"✅ Added new email: {sender_email}")
        return True
    
    def send_alert(self, alert: ForexAlert):
        """Send alert to ALL configured emails"""
        if not self.enabled or not self.email_list:
            logging.warning("Email not sent - no emails configured")
            return False
        
        success_count = 0
        
        for email_config in self.email_list:
            try:
                sender_email = email_config['email']
                sender_password = email_config['password']
                sender_name = email_config.get('name', 'Trader')
                
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

💼 METATRADER 5 (MT5) PRICES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Entry Price:      {alert.mt5_entry:.5f}
Stop Loss:        {alert.mt5_sl:.5f} 🛡️
Take Profit:      {alert.mt5_tp:.5f} 🎯
Current Price:    {alert.current_price:.5f} ✅

📊 cTRADER PIPPETTES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Entry (Decimal):   {alert.ctrader_entry_pips:.5f}
Stop Loss:         {alert.ctrader_sl_pips} pippettes 🛡️
Take Profit:       {alert.ctrader_tp_pips} pippettes 🎯

⚖️ RISK MANAGEMENT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Risk:Reward Ratio: {alert.risk_reward_ratio}
Time Triggered:    {get_pkt_now().strftime("%Y-%m-%d %H:%M:%S")} PKT

{('📝 Notes: ' + alert.notes if alert.notes else '')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Best regards,
Forex Alert System v7.0
Created by Ali Musharaf
                """
                
                message = MIMEMultipart()
                message['From'] = f"Forex Alerts <{sender_email}>"
                message['To'] = sender_email
                message['Subject'] = subject
                message.attach(MIMEText(body, 'plain'))
                
                with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
                    server.starttls()
                    server.login(sender_email, sender_password)
                    server.send_message(message)
                
                success_count += 1
                logging.info(f"✅ Email sent to {sender_email}")
                
            except Exception as e:
                logging.error(f"❌ Failed to send to {email_config.get('email', 'unknown')}: {e}")
        
        return success_count > 0

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
        self.api_calls_today = 0
        self.api_calls_reset_time = get_pkt_midnight()
        self.is_updating = False
        self.current_update_pair = ""
        
        logging.info(f"🕐 API calls will reset at midnight PKT: {self.api_calls_reset_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    def get_price_twelvedata(self, pair: str) -> Optional[float]:
        try:
            url = f"https://api.twelvedata.com/price"
            params = {'symbol': pair, 'apikey': TWELVE_DATA_API_KEY}
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if 'price' in data:
                    price = float(data['price'])
                    self.api_calls_today += 1
                    logging.info(f"✅ 12data API: {pair} = {price:.5f} (Call #{self.api_calls_today})")
                    return price
                else:
                    logging.error(f"12data API error: {data}")
            else:
                logging.error(f"12data API HTTP {response.status_code}")
                
        except Exception as e:
            logging.error(f"12data API error for {pair}: {e}")
        
        return None
    
    def fetch_initial_price(self, pair: str) -> Optional[float]:
        logging.info(f"🔍 Fetching initial baseline price for {pair}...")
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
    
    def add_alert(self, pair: str, target_price: float, stop_loss: float = 0.0, 
                  take_profit: float = 0.0, notes: str = "") -> Optional[ForexAlert]:
        if pair not in FOREX_PAIRS:
            return None
        
        baseline_price = self.fetch_initial_price(pair)
        
        if baseline_price is None:
            logging.error(f"❌ Cannot create alert - failed to fetch baseline price")
            return None
        
        alert = ForexAlert(
            pair=pair,
            target_price=target_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            baseline_price=baseline_price,
            current_price=baseline_price,
            notes=notes
        )
        
        alert.last_price_update = get_pkt_now().strftime("%Y-%m-%d %H:%M:%S")
        
        self.alerts.append(alert)
        self.save_alerts()
        
        logging.info(f"✅ Alert added: {alert.pair}")
        
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
        logging.info(f"📊 API Limit: 800 calls/day | Update Interval: 8 minutes")
        logging.info(f"🕐 Timezone: Pakistan Time (PKT - UTC+5)\n")
        
        while self.running:
            try:
                pkt_now = get_pkt_now()
                if pkt_now >= self.api_calls_reset_time:
                    self.api_calls_today = 0
                    self.api_calls_reset_time = get_pkt_midnight()
                    logging.info(f"🔄 API counter reset at {pkt_now.strftime('%Y-%m-%d %H:%M:%S')} PKT")
                
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
        try:
            with open(self.alerts_file, 'w') as f:
                json.dump([asdict(alert) for alert in self.alerts], f, indent=4)
        except Exception as e:
            logging.error(f"Error saving alerts: {e}")
    
    def load_alerts(self):
        try:
            if os.path.exists(self.alerts_file):
                with open(self.alerts_file, 'r') as f:
                    data = json.load(f)
                    self.alerts = [ForexAlert(**item) for item in data]
                    logging.info(f"📂 Loaded {len(self.alerts)} alerts")
        except Exception as e:
            logging.error(f"Error loading alerts: {e}")

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
            'stop_loss': alert.stop_loss,
            'take_profit': alert.take_profit,
            'current_price': alert.current_price,
            'direction': alert.direction,
            'risk_reward_ratio': alert.risk_reward_ratio,
            'mt5_entry': alert.mt5_entry,
            'mt5_sl': alert.mt5_sl,
            'mt5_tp': alert.mt5_tp,
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
    data = request.json
    alert = monitor.add_alert(
        data['pair'],
        float(data['target_price']),
        float(data.get('stop_loss', 0)),
        float(data.get('take_profit', 0)),
        data.get('notes', '')
    )
    if alert:
        return jsonify({
            'success': True,
            'message': 'Alert added! Monitoring started!',
            'baseline_price': alert.baseline_price,
            'direction': alert.direction,
            'risk_reward_ratio': alert.risk_reward_ratio,
            'ctrader_entry_pips': alert.ctrader_entry_pips,
            'ctrader_sl_pips': alert.ctrader_sl_pips,
            'ctrader_tp_pips': alert.ctrader_tp_pips
        })
    return jsonify({'success': False, 'message': 'Failed to fetch baseline price'}), 400

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
    
    return jsonify({
        'running': monitor.running,
        'alert_count': len(monitor.alerts),
        'active_alerts': sum(1 for a in monitor.alerts if not a.triggered),
        'email_configured': monitor.email_notifier.enabled,
        'email_count': len(monitor.email_notifier.email_list),
        'api_calls_today': monitor.api_calls_today,
        'api_limit': 800,
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
        'app': 'Forex Alert System v7.0',
        'running': monitor.running,
        'alerts': len(monitor.alerts),
        'active_alerts': sum(1 for a in monitor.alerts if not a.triggered),
        'uptime': 'always_on'
    })

if __name__ == '__main__':
    os.makedirs('templates', exist_ok=True)
    
    if monitor.alerts:
        monitor.start_monitoring()
        print("✅ Auto-started monitoring")
    
    print("\n" + "="*80)
    print("💱 FOREX ALERT SYSTEM - FINAL PERFECT EDITION v7.0")
    print("="*80)
    print("🌐 Server starting...")
    print("📧 Multi-email support enabled")
    print("⏱️  API Updates: Every 8 minutes per pair")
    print("📊 API Limit: 800 calls/day (12data)")
    print("⚡ No cold starts with /health endpoint")
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
