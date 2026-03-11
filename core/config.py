import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
HUB_URL = os.getenv("HUB_URL", "https://hub.ag3nts.org")
VERIFY_URL = f"{HUB_URL}/verify"
PROXY_PORT = int(os.getenv("PROXY_PORT", "5100"))
