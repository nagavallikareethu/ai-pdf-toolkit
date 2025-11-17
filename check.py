# quota_checker.py
import requests
import json
from datetime import datetime

def check_quota_issues(api_key):
    """
    Check Gemini API quota status and provide solutions
    """
    print("🔍 ANALYZING YOUR API QUOTA ISSUE...")
    print("=" * 60)
    
    # Error 429 means: Rate Limited or Quota Exceeded
    print("""
❌ ERROR 429: QUOTA EXCEEDED
────────────────────────────
This means you've used up your available API quota.

POSSIBLE REASONS:
1. 📊 Monthly free tier limit reached (1M characters)
2. ⚡ Rate limit exceeded (60 requests/minute)  
3. 💰 No billing method set up
4. 🔄 New account not fully activated
5. 🚫 API key restrictions blocking access
""")

    # Check current date for monthly reset
    today = datetime.now()
    print(f"📅 Today's Date: {today.strftime('%Y-%m-%d')}")
    print("🔄 Free tier resets on the 1st of each month")
    
    # Manual check instructions
    print("""
🎯 HOW TO CHECK YOUR QUOTA MANUALLY:
────────────────────────────────────

1. VISIT USAGE DASHBOARD:
   🔗 https://aistudio.google.com/app/apikey

2. CHECK GOOGLE CLOUD CONSOLE:
   🔗 https://console.cloud.google.com/
   → Navigation Menu → "APIs & Services" → "Dashboard"
   → Find "Generative Language API" → Check "Quotas" tab

3. CHECK BILLING:
   🔗 https://console.cloud.google.com/billing
   → Select your project → Check "Reports" tab

4. USAGE BREAKDOWN:
   🔗 https://ai.dev/usage?tab=rate-limit
""")

    # Quota limits information
    print("""
📊 STANDARD FREE TIER LIMITS:
─────────────────────────────
• 📝 REQUESTS: 60 per minute
• 🔤 CHARACTERS: 1,000,000 per month
• 📁 REQUESTS: 1,000 per day
• 🕒 Resets: Monthly (1st of each month)

💳 PAID TIER LIMITS (with billing):
• 📝 REQUESTS: 1,500 per minute  
• 🔤 CHARACTERS: Unlimited (pay-per-use)
• 💰 Cost: ~$0.000125 per 1K characters (Gemini 1.5 Flash)
""")

def check_specific_solutions():
    """Provide specific solutions based on common issues"""
    
    print("\n🎯 IMMEDIATE SOLUTIONS:")
    print("=" * 40)
    
    solutions = [
        {
            "issue": "Monthly character limit reached",
            "solution": "Wait until 1st of next month OR add billing method",
            "action": "Visit: https://console.cloud.google.com/billing"
        },
        {
            "issue": "Rate limit (60 requests/minute)",
            "solution": "Wait 1 minute and try again",
            "action": "Implement rate limiting in your code"
        },
        {
            "issue": "No billing method set up",
            "solution": "Add credit card to enable paid tier",
            "action": "Go to: https://console.cloud.google.com/billing"
        },
        {
            "issue": "API key restricted",
            "solution": "Check API key restrictions",
            "action": "Visit: https://aistudio.google.com/app/apikey"
        },
        {
            "issue": "New account not activated",
            "solution": "Wait 24-48 hours for full activation",
            "action": "Try again tomorrow"
        }
    ]
    
    for i, sol in enumerate(solutions, 1):
        print(f"\n{i}. {sol['issue']}:")
        print(f"   💡 {sol['solution']}")
        print(f"   🎯 {sol['action']}")

def test_api_key_status(api_key):
    """Test if API key is fundamentally working"""
    print("\n🧪 TESTING API KEY STATUS...")
    print("=" * 40)
    
    try:
        # Simple test request
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        
        # Try to list models (low quota cost)
        models = genai.list_models()
        print("✅ API Key is VALID and can connect")
        print(f"✅ Available models: {len(list(models))}")
        
        return True
        
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg:
            print("❌ CONFIRMED: QUOTA EXCEEDED (Error 429)")
            print("   Your monthly free character limit is used up")
        elif "401" in error_msg or "403" in error_msg:
            print("❌ API KEY INVALID or RESTRICTED")
            print("   Check key permissions and restrictions")
        else:
            print(f"❌ OTHER ERROR: {error_msg}")
        
        return False

def get_quota_reset_date():
    """Calculate when quota resets"""
    today = datetime.now()
    if today.day == 1:
        reset_date = today
    else:
        # Next month 1st
        if today.month == 12:
            reset_date = datetime(today.year + 1, 1, 1)
        else:
            reset_date = datetime(today.year, today.month + 1, 1)
    
    days_until_reset = (reset_date - today).days
    return reset_date, days_until_reset

# Main execution
if __name__ == "__main__":
    API_KEY = "AIzaSyCEuHktM3VnfO5mayhq46z2BY3sCatsC5g"
    
    print("🎯 GEMINI API QUOTA DIAGNOSTIC TOOL")
    print("=" * 50)
    
    # Check quota issues
    check_quota_issues(API_KEY)
    
    # Test API key
    is_working = test_api_key_status(API_KEY)
    
    # Get reset information
    reset_date, days_left = get_quota_reset_date()
    print(f"\n📅 QUOTA RESET DATE: {reset_date.strftime('%Y-%m-%d')}")
    print(f"⏳ DAYS UNTIL RESET: {days_left} days")
    
    # Provide solutions
    check_specific_solutions()
    
    # Final recommendations
    print("\n🚀 RECOMMENDED ACTIONS:")
    print("=" * 30)
    
    if days_left <= 3:
        print("1. 🕒 WAIT: Reset is soon, wait for automatic reset")
    else:
        print("1. 💳 UPGRADE: Add billing for immediate access")
    
    print("2. 🔄 NEW KEY: Create new API key (may not help if project quota exceeded)")
    print("3. 📊 MONITOR: Check usage patterns to avoid future limits")
    print("4. ⚡ OPTIMIZE: Reduce request size and frequency")
    
    print(f"\n🔗 QUICK LINKS:")
    print("• Usage Dashboard: https://ai.dev/usage?tab=rate-limit")
    print("• Billing Setup: https://console.cloud.google.com/billing")
    print("• API Keys: https://aistudio.google.com/app/apikey")