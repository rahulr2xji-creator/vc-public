from flask import Flask, request, jsonify, json
import requests
from bs4 import BeautifulSoup
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
import hashlib
import random
import time
from typing import Dict, Any, Optional
import pytz

app = Flask(__name__)
# Configure JSON encoding to properly display emojis
app.config['JSON_AS_ASCII'] = False

# ============================================
# CONFIGURATION
# ============================================

COPYRIGHT_STRING = "API STORE "
DAILY_LIMIT = 3000  # 3000 requests per day
RESET_HOUR = 0      # 12 AM
RESET_MINUTE = 5    # 5 minutes (12:05 AM)
TIMEZONE = pytz.timezone('Asia/Kolkata')  # IST Timezone

# Desired order of keys in the output
DESIRED_ORDER = [
    "Owner Name", "Father's Name", "Owner Serial No", "Model Name", "Maker Model",
    "Vehicle Class", "Fuel Type", "Fuel Norms", "Registration Date", "Insurance Company",
    "Insurance No", "Insurance Expiry", "Insurance Upto", "Fitness Upto", "Tax Upto",
    "PUC No", "PUC Upto", "Financier Name", "Registered RTO", "Address", "City Name", "Phone"
]

# ============================================
# API KEY & RATE LIMIT MANAGEMENT
# ============================================

class APIKeyManager:
    """Manage API key and rate limiting"""
    
    def __init__(self):
        # Only one key - "GO"
        self.api_key = "GO"
        self.key_info = {
            "created_at": datetime.now(TIMEZONE).isoformat(),
            "status": "active",
            "daily_limit": DAILY_LIMIT
        }
        
        # Usage tracking
        self.usage_count = 0
        self.current_date = self.get_current_date()
        
        # Device fingerprints
        self.device_templates = [
            {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36',
                'platform': 'Windows'
            },
            {
                'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36',
                'platform': 'macOS'
            },
            {
                'user_agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/130.0.0.0 Mobile Safari/537.36',
                'platform': 'Android'
            },
            {
                'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1',
                'platform': 'iOS'
            },
            {
                'user_agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36',
                'platform': 'Linux'
            },
            {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
                'platform': 'Windows'
            },
            {
                'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.1 Safari/605.1.15',
                'platform': 'macOS'
            }
        ]
    
    def get_current_date(self) -> str:
        """Get current date in IST"""
        return datetime.now(TIMEZONE).date().isoformat()
    
    def get_reset_time(self) -> str:
        """Get next reset time in IST"""
        now = datetime.now(TIMEZONE)
        reset_time = now.replace(hour=RESET_HOUR, minute=RESET_MINUTE, second=0, microsecond=0)
        
        # If reset time has passed today, set to tomorrow
        if now >= reset_time:
            reset_time += timedelta(days=1)
        
        return reset_time.strftime('%I:%M %p')  # 12:05 AM format
    
    def should_reset(self) -> bool:
        """Check if usage should be reset"""
        current_date = self.get_current_date()
        if current_date != self.current_date:
            self.usage_count = 0
            self.current_date = current_date
            return True
        return False
    
    def get_random_device(self) -> Dict[str, str]:
        """Get random device fingerprint"""
        template = random.choice(self.device_templates)
        return {
            'user_agent': template['user_agent'],
            'platform': template['platform']
        }
    
    def validate_key(self, api_key: str) -> tuple[bool, str]:
        """
        Validate if API key is correct and active
        
        Returns: (is_valid, message)
        """
        if not api_key:
            return False, "API key required"
        
        if api_key != self.api_key:
            return False, "Invalid API key"
        
        if self.key_info['status'] != 'active':
            return False, "API key is inactive"
        
        return True, "Valid key"
    
    def check_and_increment(self) -> Dict[str, Any]:
        """
        Check rate limit and increment usage
        
        Returns: Dict with status and usage info
        """
        # Check if reset needed
        self.should_reset()
        
        current_count = self.usage_count
        limit = self.key_info['daily_limit']
        remaining = limit - current_count
        
        # Check if limit reached
        if current_count >= limit:
            return {
                'allowed': False,
                'message': f'Daily limit of {limit} requests reached',
                'count': current_count,
                'limit': limit,
                'remaining': 0,
                'reset_date': self.current_date,
                'reset_time': self.get_reset_time()
            }
        
        # Increment usage
        self.usage_count += 1
        
        return {
            'allowed': True,
            'message': 'Request allowed',
            'count': self.usage_count,
            'limit': limit,
            'remaining': limit - self.usage_count,
            'reset_date': self.current_date,
            'reset_time': self.get_reset_time()
        }


# Initialize key manager
key_manager = APIKeyManager()

# ============================================
# VEHICLE INFO FETCHER
# ============================================

def get_vehicle_details(rc_number: str, device: Dict[str, str]) -> dict:
    """
    Fetch vehicle details with device fingerprinting
    """
    rc = rc_number.strip().upper()
    url = f"https://vahanx.in/rc-search/{rc}"

    headers = {
        "Host": "vahanx.in",
        "Connection": "keep-alive",
        "sec-ch-ua": "\"Chromium\";v=\"130\", \"Google Chrome\";v=\"130\", \"Not?A_Brand\";v=\"99\"",
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": f"\"{device['platform']}\"",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": device['user_agent'],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": "https://vahanx.in/rc-search",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9"
    }

    # Add random delay to avoid rate limiting
    time.sleep(random.uniform(0.5, 1.5))

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
    except requests.exceptions.RequestException as e:
        return {"error": f"Network error: {e}"}
    except Exception as e:
        return {"error": str(e)}

    def get_value(label):
        try:
            div = soup.find("span", string=label).find_parent("div")
            return div.find("p").get_text(strip=True)
        except AttributeError:
            return None

    data = {
        "Owner Name": get_value("Owner Name"),
        "Father's Name": get_value("Father's Name"),
        "Owner Serial No": get_value("Owner Serial No"),
        "Model Name": get_value("Model Name"),
        "Maker Model": get_value("Maker Model"),
        "Vehicle Class": get_value("Vehicle Class"),
        "Fuel Type": get_value("Fuel Type"),
        "Fuel Norms": get_value("Fuel Norms"),
        "Registration Date": get_value("Registration Date"),
        "Insurance Company": get_value("Insurance Company"),
        "Insurance No": get_value("Insurance No"),
        "Insurance Expiry": get_value("Insurance Expiry"),
        "Insurance Upto": get_value("Insurance Upto"),
        "Fitness Upto": get_value("Fitness Upto"),
        "Tax Upto": get_value("Tax Upto"),
        "PUC No": get_value("PUC No"),
        "PUC Upto": get_value("PUC Upto"),
        "Financier Name": get_value("Financier Name"),
        "Registered RTO": get_value("Registered RTO"),
        "Address": get_value("Address"),
        "City Name": get_value("City Name"),
        "Phone": get_value("Phone")
    }
    return data

# ============================================
# API ROUTES
# ============================================

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "🚗 Vehicle Info API",
        "version": "3.0",
        "developer": COPYRIGHT_STRING,
        "api_key": key_manager.api_key,
        "daily_limit": DAILY_LIMIT,
        "reset_time": "12:05 AM IST",
        "timezone": "Asia/Kolkata (IST)",
        "endpoints": {
            "/lookup": "GET - Lookup vehicle details (requires ?rc= & ?key=GO)",
            "/reset": "POST - Force reset usage counter (admin only)"
        },
        "example": "/lookup?rc=MH01XX1234&key=GO"
    })

@app.route("/lookup", methods=["GET"])
def lookup_vehicle():
    """
    Lookup vehicle details
    Required params: rc=VEHICLE_NUMBER, key=GO
    """
    # Get parameters
    rc_number = request.args.get("rc")
    api_key = request.args.get("key")
    
    # Validate API key
    if not api_key:
        return jsonify({
            "error": "API key required",
            "message": "Please provide ?key=GO parameter",
            "valid_key": key_manager.api_key,
            "limit_info": {
                "Limit": f"{key_manager.usage_count}/{DAILY_LIMIT}",
                "Reset Time": key_manager.get_reset_time(),
                "Timezone": "Asia/Kolkata (IST)"
            },
            "copyright": COPYRIGHT_STRING
        }), 401
    
    # Check if API key is valid
    is_valid, message = key_manager.validate_key(api_key)
    if not is_valid:
        return jsonify({
            "error": message,
            "key": api_key,
            "valid_key": key_manager.api_key,
            "limit_info": {
                "Limit": f"{key_manager.usage_count}/{DAILY_LIMIT}",
                "Reset Time": key_manager.get_reset_time(),
                "Timezone": "Asia/Kolkata (IST)"
            },
            "copyright": COPYRIGHT_STRING
        }), 401
    
    # Check rate limit
    limit_check = key_manager.check_and_increment()
    if not limit_check['allowed']:
        return jsonify({
            "error": "Rate limit exceeded",
            "message": limit_check['message'],
            "limit_info": {
                "Limit": f"{limit_check['count']}/{limit_check['limit']}",
                "Reset Time": limit_check['reset_time'],
                "Timezone": "Asia/Kolkata (IST)"
            },
            "copyright": COPYRIGHT_STRING
        }), 429
    
    # Validate RC number
    if not rc_number:
        return jsonify({
            "error": "RC number required",
            "message": "Please provide ?rc= parameter",
            "key": api_key,
            "limit_info": {
                "Limit": f"{limit_check['count']}/{limit_check['limit']}",
                "Reset Time": limit_check['reset_time'],
                "Timezone": "Asia/Kolkata (IST)"
            },
            "copyright": COPYRIGHT_STRING
        }), 400
    
    # Get random device fingerprint
    device = key_manager.get_random_device()
    
    # Fetch vehicle details
    details = get_vehicle_details(rc_number, device)
    
    # Check for error
    if "error" in details:
        return jsonify({
            "error": details["error"],
            "key": api_key,
            "limit_info": {
                "Limit": f"{limit_check['count']}/{limit_check['limit']}",
                "Reset Time": limit_check['reset_time'],
                "Timezone": "Asia/Kolkata (IST)"
            },
            "copyright": COPYRIGHT_STRING
        }), 500
    
    # Create ordered response
    ordered_details = OrderedDict()
    
    # Add keys in desired order
    for key in DESIRED_ORDER:
        if key in details:
            ordered_details[key] = details[key]
    
    # Add limit info (exactly as requested)
    ordered_details["limit_info"] = {
        "Limit": f"{limit_check['count']}/{limit_check['limit']}",
        "Reset Time": limit_check['reset_time'],
        "Timezone": "Asia/Kolkata (IST)"
    }
    
    # Add copyright
    ordered_details["copyright"] = COPYRIGHT_STRING
    
    return jsonify(ordered_details)

@app.route("/reset", methods=["POST"])
def reset_usage():
    """
    Force reset usage counter (Admin only)
    """
    admin_secret = request.headers.get("X-Admin-Secret")
    if admin_secret != "ADMIN_SECRET_2026":
        return jsonify({
            "error": "Admin access required",
            "message": "Provide X-Admin-Secret header"
        }), 401
    
    old_count = key_manager.usage_count
    key_manager.usage_count = 0
    key_manager.current_date = key_manager.get_current_date()
    
    return jsonify({
        "message": "Usage counter reset successfully",
        "old_count": old_count,
        "new_count": 0,
        "reset_time": datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S IST'),
        "copyright": COPYRIGHT_STRING
    })

# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Endpoint not found",
        "message": "Please check the API documentation",
        "endpoints": ["/", "/lookup", "/reset"],
        "copyright": COPYRIGHT_STRING
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "error": "Internal server error",
        "message": "Please try again later",
        "copyright": COPYRIGHT_STRING
    }), 500

# ============================================
# RUN SERVER
# ============================================

if __name__ == "__main__":
    print("🚗 Vehicle Info API ")
    print("=" * 60)
    print(f"🔑 API Key: {key_manager.api_key}")
    print(f"📊 Daily Limit: {DAILY_LIMIT} requests/day")
    print(f"⏰ Reset Time: 12:05 AM IST")
    print(f"🌍 Timezone: Asia/Kolkata (IST)")
    print("=" * 60)
    print("📍 Local: http://localhost:5000")
    print("📥 Example: http://localhost:5000/lookup?rc=MH01XX1234&key={key}")
    print("=" * 60)
    print(f"🕐 Current IST Time: {datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🔄 Next Reset: {key_manager.get_reset_time()}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)