import streamlit as st
import requests
import pandas as pd
import sqlite3
import time
import schedule
from datetime import datetime
import json

# Load config from file
with open("config.json", "r") as f:
    config = json.load(f)

# Constants
DEXSCREENER_API_URL = config["dex_screener_api_url"]
POCKET_UNIVERSE_API_URL = config["pocket_universe_api_url"]
POCKET_UNIVERSE_API_KEY = config["pocket_universe_api_key"]
RUGCHECK_API_URL = config["rugcheck_api_url"]
BONKBOT_API_URL = config["bonkbot_api_url"]
BONKBOT_API_KEY = config["bonkbot_api_key"]
TELEGRAM_BOT_TOKEN = config["telegram_bot_token"]
TELEGRAM_CHAT_ID = config["telegram_chat_id"]
DATABASE_NAME = config["database_name"]
TABLE_NAME = config["table_name"]
MIN_VOLUME_USD = config["filters"]["min_volume_usd"]
MIN_LIQUIDITY_USD = config["filters"]["min_liquidity_usd"]
MIN_MARKET_CAP_USD = config["filters"]["min_market_cap_usd"]
MAX_FAKE_VOLUME_PERCENTAGE = config["filters"]["max_fake_volume_percentage"]
BUNDLED_SUPPLY_THRESHOLD = config["filters"]["bundled_supply_threshold"]
COIN_BLACKLIST = set(config["blacklist"]["coins"])
DEV_BLACKLIST = set(config["blacklist"]["devs"])

# Initialize SQLite database
def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_address TEXT,
            price_usd REAL,
            volume_usd REAL,
            liquidity_usd REAL,
            market_cap_usd REAL,
            dev_address TEXT,
            fake_volume_percentage REAL,
            rugcheck_status TEXT,
            is_bundled_supply BOOLEAN,
            timestamp DATETIME
        )
    """)
    conn.commit()
    conn.close()

# Fetch data from DexScreener
def fetch_token_data(token_address):
    url = f"{DEXSCREENER_API_URL}{token_address}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get('pairs', [])
    else:
        st.error(f"Failed to fetch data for token {token_address}")
        return []

# Check if token or dev is blacklisted
def is_blacklisted(token_address, dev_address):
    return token_address in COIN_BLACKLIST or dev_address in DEV_BLACKLIST

# Analyze token using RugCheck API
def check_rugcheck(token_address):
    url = f"{RUGCHECK_API_URL}/{token_address}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get("status", "Unknown"), data.get("supply_distribution", {})
    else:
        st.error(f"Failed to fetch RugCheck data for token {token_address}")
        return "Unknown", {}

# Check if supply is bundled
def is_bundled_supply(supply_distribution):
    if not supply_distribution:
        return False
    top_wallets = list(supply_distribution.values())[:3]  # Check top 3 wallets
    total_supply_percentage = sum(top_wallets)
    return total_supply_percentage > BUNDLED_SUPPLY_THRESHOLD

# Analyze token transactions using Pocket Universe API
def analyze_fake_volume(token_address):
    headers = {
        "Authorization": f"Bearer {POCKET_UNIVERSE_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "token_address": token_address,
        "analysis_type": "volume_analysis"
    }
    response = requests.post(POCKET_UNIVERSE_API_URL, headers=headers, json=payload)
    if response.status_code == 200:
        data = response.json()
        return data.get("fake_volume_percentage", 0)
    else:
        st.error(f"Failed to analyze fake volume for token {token_address}")
        return 0

# Execute trade via BonkBot
def execute_trade(token_address, action):
    headers = {
        "Authorization": f"Bearer {BONKBOT_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "token_address": token_address,
        "action": action
    }
    response = requests.post(BONKBOT_API_URL, headers=headers, json=payload)
    if response.status_code == 200:
        st.success(f"Trade executed: {action} {token_address}")
        return True
    else:
        st.error(f"Failed to execute trade: {action} {token_address}")
        return False

# Send Telegram notification
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        st.success(f"Telegram notification sent: {message}")
    else:
        st.error(f"Failed to send Telegram notification: {message}")

# Save data to database
def save_to_db(token_address, price, volume, liquidity, market_cap, dev_address, fake_volume_percentage, rugcheck_status, is_bundled_supply):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute(f"""
        INSERT INTO {TABLE_NAME} (token_address, price_usd, volume_usd, liquidity_usd, market_cap_usd, dev_address, fake_volume_percentage, rugcheck_status, is_bundled_supply, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (token_address, price, volume, liquidity, market_cap, dev_address, fake_volume_percentage, rugcheck_status, is_bundled_supply, datetime.now()))
    conn.commit()
    conn.close()

# Analyze data for patterns
def analyze_data():
    conn = sqlite3.connect(DATABASE_NAME)
    df = pd.read_sql_query(f"SELECT * FROM {TABLE_NAME}", conn)
    conn.close()

    # Example: Detect rug pulls (sudden price drop and liquidity removal)
    rug_pulls = df.groupby('token_address').apply(
        lambda x: (x['price_usd'].iloc[-1] < x['price_usd'].max() * 0.5) and
                  (x['liquidity_usd'].iloc[-1] < x['liquidity_usd'].max() * 0.1)
    )
    rug_pulls = rug_pulls[rug_pulls].index.tolist()
    if rug_pulls:
        st.warning(f"Potential rug pulls detected for tokens: {rug_pulls}")
        send_telegram_message(f"🚨 Potential rug pulls detected for tokens: {rug_pulls}")

    # Example: Detect pumps (rapid price increase)
    pumps = df.groupby('token_address').apply(
        lambda x: (x['price_usd'].iloc[-1] > x['price_usd'].max() * 2) and
                  (x['volume_usd'].iloc[-1] > x['volume_usd'].mean() * 10)
    )
    pumps = pumps[pumps].index.tolist()
    if pumps:
        st.success(f"Potential pumps detected for tokens: {pumps}")
        send_telegram_message(f"🚀 Potential pumps detected for tokens: {pumps}")

# Main function to fetch and save data
def fetch_and_save_data():
    tokens = ["TOKEN_ADDRESS_1", "TOKEN_ADDRESS_2"]  # Add token addresses here
    for token in tokens:
        if token in COIN_BLACKLIST:
            st.warning(f"Skipping blacklisted token: {token}")
            continue

        pairs = fetch_token_data(token)
        for pair in pairs:
            dev_address = pair.get('devAddress', '')  # Assuming DexScreener provides dev address
            if is_blacklisted(token, dev_address):
                st.warning(f"Skipping blacklisted token or dev: {token}, {dev_address}")
                continue

            volume = pair['volume']['usd']
            liquidity = pair['liquidity']['usd']
            market_cap = pair['fdv']

            # Apply filters
            if volume < MIN_VOLUME_USD or liquidity < MIN_LIQUIDITY_USD or market_cap < MIN_MARKET_CAP_USD:
                st.warning(f"Skipping token {token} due to filter criteria")
                continue

            # Check RugCheck status and supply distribution
            rugcheck_status, supply_distribution = check_rugcheck(token)
            if rugcheck_status != "Good":
                st.warning(f"Skipping token {token} due to RugCheck status: {rugcheck_status}")
                COIN_BLACKLIST.add(token)
                DEV_BLACKLIST.add(dev_address)
                continue

            # Check for bundled supply
            if is_bundled_supply(supply_distribution):
                st.warning(f"Skipping token {token} due to bundled supply")
                COIN_BLACKLIST.add(token)
                DEV_BLACKLIST.add(dev_address)
                continue

            # Analyze fake volume
            fake_volume_percentage = analyze_fake_volume(token)
            if fake_volume_percentage > MAX_FAKE_VOLUME_PERCENTAGE:
                st.warning(f"Skipping token {token} due to high fake volume: {fake_volume_percentage}%")
                continue

            # Save data to database
            save_to_db(
                token_address=token,
                price=pair['priceUsd'],
                volume=volume,
                liquidity=liquidity,
                market_cap=market_cap,
                dev_address=dev_address,
                fake_volume_percentage=fake_volume_percentage,
                rugcheck_status=rugcheck_status,
                is_bundled_supply=is_bundled_supply(supply_distribution)
            )

            # Execute trade and send notification
            if execute_trade(token, "buy"):
                send_telegram_message(f"✅ Buy order executed for token: {token}")
    analyze_data()

# Streamlit UI
def main():
    st.title("Crypto Trading Bot")
    st.sidebar.header("Settings")

    # Start/Stop Bot
    if st.sidebar.button("Start Bot"):
        st.session_state.bot_running = True
        st.success("Bot started!")
        while st.session_state.bot_running:
            fetch_and_save_data()
            time.sleep(300)  # Run every 5 minutes

    if st.sidebar.button("Stop Bot"):
        st.session_state.bot_running = False
        st.warning("Bot stopped!")

    # View Token Data
    if st.sidebar.button("View Token Data"):
        conn = sqlite3.connect(DATABASE_NAME)
        df = pd.read_sql_query(f"SELECT * FROM {TABLE_NAME}", conn)
        conn.close()
        st.dataframe(df)

    # Update Config
    st.sidebar.header("Update Config")
    new_min_volume = st.sidebar.number_input("Minimum Volume (USD)", value=MIN_VOLUME_USD)
    new_min_liquidity = st.sidebar.number_input("Minimum Liquidity (USD)", value=MIN_LIQUIDITY_USD)
    new_min_market_cap = st.sidebar.number_input("Minimum Market Cap (USD)", value=MIN_MARKET_CAP_USD)
    if st.sidebar.button("Update Filters"):
        config["filters"]["min_volume_usd"] = new_min_volume
        config["filters"]["min_liquidity_usd"] = new_min_liquidity
        config["filters"]["min_market_cap_usd"] = new_min_market_cap
        with open("config.json", "w") as f:
            json.dump(config, f)
        st.success("Filters updated!")

# Run the app
if __name__ == "__main__":
    main()
