import os

# Load environment variables from .env file if it exists
if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                parts = line.split("=", 1)
                os.environ[parts[0].strip()] = parts[1].strip().strip('"').strip("'")

# Telegram Bot Token (obtained from @BotFather)
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Telegram User ID of the owner/admin
OWNER_ID = int(os.getenv("OWNER_ID", "1234567890"))

# Target Group Chat ID (e.g., -100xxxxxxxxxx) where messages are tracked.
# If set to None, messages will be tracked in any group/supergroup the bot is in.
GROUP_ID = os.getenv("GROUP_ID")
if GROUP_ID:
    try:
        GROUP_ID = int(GROUP_ID)
    except ValueError:
        pass
else:
    GROUP_ID = None  # Tracks any group if not specified

# Link to the Telegram Group for the mandatory join check
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/GROUP_USERNAME")

# Link to the Telegram Channel for the mandatory join check
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/Gacha_Nexus_News")

# Target Channel Chat ID or username (e.g., @Gacha_Nexus_News or -100xxxxxxxxxx)
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Gacha_Nexus_News")
if CHANNEL_ID:
    try:
        CHANNEL_ID = int(CHANNEL_ID)
    except ValueError:
        pass

# Number of messages the referred user must write in the group to activate the referral
REFERRAL_REQUIRED_MESSAGES = int(os.getenv("REFERRAL_REQUIRED_MESSAGES", "20"))

# Number of messages required to earn 1 interaction point and maintain daily streak
INTERACTION_THRESHOLD = int(os.getenv("INTERACTION_THRESHOLD", "50"))

# Database configuration
DB_NAME = "bot_database.db"
