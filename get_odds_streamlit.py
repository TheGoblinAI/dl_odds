import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz
import io
import os

# --------------------------------------------------------
# CONFIG
# --------------------------------------------------------
st.set_page_config(page_title="FanDuel NFL Odds Fetcher", layout="wide")

SPORT = "americanfootball_nfl"
REGION = "us"
HOURS_AHEAD = 48
MARKETS = [
    "player_pass_attempts",
    "player_pass_rush_yds",
    "player_rush_yds",
    "player_pass_tds",
    "player_pass_yds",
    "player_receptions",
    "player_reception_yds",
    "player_rush_tds",
]

# --------------------------------------------------------
# Helper: Load API key
# --------------------------------------------------------
def load_api_key():
    key_path = "key.txt"
    if not os.path.exists(key_path):
        st.error("❌ Missing key.txt file. Please upload your Odds API key.")
        st.stop()
    with open(key_path, "r") as f:
        key = f.read().strip()
    if not key:
        st.error("❌ key.txt is empty. Please add your Odds API key.")
        st.stop()
    return key


# --------------------------------------------------------
# Helper: Convert odds to American
# --------------------------------------------------------
def to_american_odds(odds_value):
    try:
        if isinstance(odds_value, int) or (isinstance(odds_value, float) and abs(odds_value) > 100):
            return int(odds_value)
        decimal_odds = float(odds_value)
        if decimal_odds >= 2.0:
            return int((decimal_odds - 1) * 100)
        else:
            return int(-100 / (decimal_odds - 1))
    except Exception:
        return None


# --------------------------------------------------------
# Core logic: Fetch odds
# --------------------------------------------------------
def fetch_odds():
    API_KEY = load_api_key()
    events_url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events?apiKey={API_KEY}&regions={REGION}"
    try:
        events_resp = requests.get(events_url)
        events_resp.raise_for_status()
        events = events_resp.json()
    except Exception as e:
        st.error(f"❌ Failed to fetch events: {e}")
        return pd.DataFrame()

    now = datetime.utcnow()
    time_limit = now + timedelta(hours=HOURS_AHEAD)
    upcoming_events = [
        e for e in events
        if datetime.fromisoformat(e["commence_time"].replace("Z", "")) <= time_limit
    ]
    if not upcoming_events:
        st.warning("⚠️ No upcoming NFL games found in the next 48 hours.")
        return pd.DataFrame()

    all_props = []
    eastern_tz = pytz.timezone("US/Eastern")

    progress = st.progress(0)
    for idx, event in enumerate(upcoming_events):
        event_id = event["id"]
        event_name = f"{event.get('home_team')} vs {event.get('away_team')}"
        commence_time_utc = event.get("commence_time")

        # Convert UTC → Eastern
        try:
            utc_dt = datetime.fromisoformat(commence_time_utc.replace("Z", "+00:00"))
            est_dt = utc_dt.astimezone(eastern_tz)
            formatted_est = est_dt.strftime("%m-%d-%Y %H:%M")
        except Exception:
            formatted_est = "N/A"

        odds_url = (
            f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{event_id}/odds/"
            f"?apiKey={API_KEY}&regions={REGION}&markets={','.join(MARKETS)}"
        )

        try:
            resp = requests.get(odds_url)
            if resp.status_code == 422:
                continue
            resp.raise_for_status()
            game_data = resp.json()
        except Exception:
            continue

        for bookmaker in game_data.get("bookmakers", []):
            title = bookmaker.get("title", "").lower()
            if "fanduel" not in title:
                continue

            for market_item in bookmaker.get("markets", []):
                market_key = market_item.get("key")
                for outcome in market_item.get("outcomes", []):
                    american_odds = to_american_odds(outcome.get("price"))
                    all_props.append({
                        "game": event_name,
                        "date_time_est": formatted_est,
                        "bookmaker": bookmaker.get("title"),
                        "market": market_key,
                        "player": outcome.get("description"),
                        "over_under": outcome.get("point"),
                        "side": outcome.get("name"),
                        "odds_american": american_odds
                    })

        progress.progress((idx + 1) / len(upcoming_events))

    df = pd.DataFrame(all_props)
    if df.empty:
        st.warning("⚠️ No FanDuel player prop odds available for selected markets.")
        return pd.DataFrame()

    if "side" in df.columns:
        df = df[df["side"] == "Over"]

    return df


# --------------------------------------------------------
# Streamlit UI
# --------------------------------------------------------
st.title("🏈 FanDuel NFL Player Prop Odds Fetcher")
st.markdown("Fetch player prop odds for upcoming NFL games (FanDuel, next 48 hours).")

st.divider()

# Big button
if st.button("🚀 **Get Odds**", use_container_width=True, type="primary"):
    with st.spinner("Fetching latest FanDuel player prop odds..."):
        df = fetch_odds()

    if not df.empty:
        st.success(f"✅ Retrieved {len(df)} odds entries.")
        st.dataframe(df.head(20), use_container_width=True)

        # Prepare CSV for download
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        st.download_button(
            label="⬇️ Download odds.csv",
            data=csv_buffer.getvalue(),
            file_name="odds.csv",
            mime="text/csv",
            use_container_width=True
        )
    else:
        st.error("❌ No data returned. Try again later.")
