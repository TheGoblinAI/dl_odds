import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
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
    "player_pass_yds_alternate",
    "player_receptions_alternate",
    "player_reception_yds_alternate",
    "player_rush_yds_alternate",
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
# Step 1 – Fetch upcoming NFL games (for selection)
# --------------------------------------------------------
def get_upcoming_games():
    API_KEY = load_api_key()
    events_url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events?apiKey={API_KEY}&regions={REGION}"

    try:
        events_resp = requests.get(events_url, timeout=15)
    except requests.exceptions.RequestException as e:
        st.error(f"🌐 Network error: {e}")
        return []

    if events_resp.status_code != 200:
        try:
            err_json = events_resp.json()
            err_message = err_json.get("message", "Unknown API error")
        except Exception:
            err_message = events_resp.text
        st.error(f"❌ API error {events_resp.status_code}: {err_message}")
        return []

    try:
        events = events_resp.json()
    except Exception as e:
        st.error(f"⚠️ Failed to parse API response: {e}")
        return []

    now_utc = datetime.now(timezone.utc)
    time_limit = now_utc + timedelta(hours=HOURS_AHEAD)
    eastern_tz = pytz.timezone("US/Eastern")

    games = []
    for e in events:
        try:
            # ✅ Parse kickoff time as UTC-aware
            utc_dt = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)

            if utc_dt <= time_limit:
                est_dt = utc_dt.astimezone(eastern_tz)
                games.append({
                    "id": e["id"],
                    "game": f"{e['home_team']} vs {e['away_team']}",
                    "date_est": est_dt.strftime("%m-%d-%Y"),
                    "time_est": est_dt.strftime("%I:%M %p"),
                    "datetime_est": est_dt.strftime("%m-%d-%Y %I:%M %p")
                })
        except Exception as ex:
            print(f"Skipping event parse error: {ex}")
            continue

    if not games:
        st.warning("⚠️ No upcoming NFL games found in the next 48 hours. (Time conversion fixed — check key or API limits.)")
    return games


# --------------------------------------------------------
# Step 2 – Fetch odds only for selected games
# --------------------------------------------------------
def fetch_odds(selected_games):
    API_KEY = load_api_key()
    all_props = []

    progress = st.progress(0)
    for idx, game in enumerate(selected_games):
        event_id = game["id"]
        event_name = game["game"]
        date_est = game["date_est"]
        time_est = game["time_est"]
        formatted_est = game["datetime_est"]

        odds_url = (
            f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{event_id}/odds/"
            f"?apiKey={API_KEY}&regions={REGION}&markets={','.join(MARKETS)}"
        )

        try:
            resp = requests.get(odds_url, timeout=15)
            if resp.status_code == 422:
                continue
            if resp.status_code != 200:
                try:
                    err_json = resp.json()
                    st.warning(f"⚠️ API {resp.status_code} for {event_name}: {err_json.get('message','Unknown error')}")
                except Exception:
                    st.warning(f"⚠️ API {resp.status_code} for {event_name}: {resp.text}")
                continue
            game_data = resp.json()
        except requests.exceptions.RequestException as e:
            st.warning(f"⚠️ Network error fetching {event_name}: {e}")
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
                        "date_est": date_est,
                        "time_est": time_est,
                        "bookmaker": bookmaker.get("title"),
                        "market": market_key,
                        "player": outcome.get("description"),
                        "over_under": outcome.get("point"),
                        "side": outcome.get("name"),
                        "odds_american": american_odds
                    })

        progress.progress((idx + 1) / len(selected_games))

    df = pd.DataFrame(all_props)
    if df.empty:
        st.warning("⚠️ No FanDuel player prop odds available for selected games.")
        return pd.DataFrame()

    if "side" in df.columns:
        df = df[df["side"] == "Over"]

    return df


# --------------------------------------------------------
# Streamlit UI
# --------------------------------------------------------
st.title("🏈 FanDuel NFL Player Prop Odds Fetcher")
st.markdown("Fetch player prop odds for **specific NFL games** from FanDuel within the next 48 hours.")
st.divider()

# Step 1: Show upcoming games
st.header("📅 Select NFL Games to Fetch Odds For")
games = get_upcoming_games()

if not games:
    st.stop()

# Display list
games_df = pd.DataFrame(games)
st.dataframe(games_df[["game", "date_est", "time_est"]], use_container_width=True)

# Let user pick
selected_game_names = st.multiselect(
    "Select one or more games:",
    options=[g["game"] for g in games],
    help="Choose which games you want to download odds for."
)

selected_games = [g for g in games if g["game"] in selected_game_names]

st.divider()

# Step 2: Fetch odds for selected
if st.button("🚀 **Fetch FanDuel Odds for Selected Games**", use_container_width=True, type="primary"):
    if not selected_games:
        st.warning("⚠️ Please select at least one game before fetching odds.")
        st.stop()

    with st.spinner("Fetching FanDuel player prop odds..."):
        df = fetch_odds(selected_games)

    if not df.empty:
        st.success(f"✅ Retrieved {len(df)} odds entries across {len(selected_games)} selected games.")
        st.dataframe(df.head(25), use_container_width=True)

        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)

        # 🔴 Red styled download button
        red_button_style = """
        <style>
        div[data-testid="stDownloadButton"] button {
            background-color: #ff4b4b;
            color: white;
            font-weight: bold;
            border-radius: 8px;
            border: 1px solid #b30000;
        }
        div[data-testid="stDownloadButton"] button:hover {
            background-color: #e60000;
            border: 1px solid #660000;
        }
        </style>
        """

        st.markdown(red_button_style, unsafe_allow_html=True)
        st.download_button(
            label="⬇️ Download odds.csv",
            data=csv_buffer.getvalue(),
            file_name="odds.csv",
            mime="text/csv",
            use_container_width=True
        )
    else:
        st.error("❌ No data returned for the selected games.")
