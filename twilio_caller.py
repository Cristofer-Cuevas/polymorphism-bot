import os
from twilio.rest import Client


def call_alert(tweet_category: str):
    """
    Makes a phone call via Twilio when Elon tweets.
    Uses TwiML <Say> to speak the alert message.
    Reads env vars at call time so load_dotenv() works before import.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER")
    to_number = os.getenv("TWILIO_TO_NUMBER")

    if not all([account_sid, auth_token, from_number, to_number]):
        print("⚠️ Twilio not configured — skipping phone call.")
        return

    try:
        client = Client(account_sid, auth_token)
        call = client.calls.create(
            to=to_number,
            from_=from_number,
            twiml=f'<Response><Say voice="alice" loop="3">Alert! Elon Musk just posted a {tweet_category} on X. Check Polymarket now.</Say></Response>'
        )
        print(f"📞 Twilio call initiated: {call.sid}")
    except Exception as e:
        print(f"❌ Twilio call failed: {e}")
