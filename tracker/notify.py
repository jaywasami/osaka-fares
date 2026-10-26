import os

import requests


def send(text: str) -> bool:
    """Push a Telegram message. Returns False (and prints why) instead of raising,
    so a notification problem never loses the day's price data."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[telegram] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set; message not sent:\n" + text)
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30,
                          json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True})
    except requests.RequestException as e:
        print(f"[telegram] send failed: {e}")
        return False
    if r.status_code != 200:
        print(f"[telegram] HTTP {r.status_code}: {r.text[:200]}")
        return False
    return True
