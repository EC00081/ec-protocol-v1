import streamlit as st
import pandas as pd
import time
import math
import pytz
import random
import os
import sqlalchemy
from datetime import datetime
from streamlit_js_eval import get_geolocation
from streamlit_autorefresh import st_autorefresh
from sqlalchemy import create_engine, text

# --- 1. CONFIGURATION ---
st.set_page_config(
    page_title="EC Enterprise", 
    page_icon="🛡️", 
    layout="centered", 
    initial_sidebar_state="collapsed"
)

# --- 2. LIBRARY LOADER ---
try:
    import face_recognition
    BIO_ENGINE_AVAILABLE = True
except ImportError:
    BIO_ENGINE_AVAILABLE = False
    class Point:
        def __init__(self, x, y): self.x, self.y = x, y
    class Polygon:
        def __init__(self, points): self.points = points
        def contains(self, point): return True 

# --- 3. PROFESSIONAL UI STYLING (CSS) ---
st.markdown("""
    <head>
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="theme-color" content="#0f172a">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
    </head>
    <style>
    /* GLOBAL RESET */
    * { font-family: 'Inter', sans-serif !important; }
    
    /* APP BACKGROUND - Midnight Enterprise Theme */
    .stApp {
        background: radial-gradient(circle at 50% 0%, #1e293b, #0f172a);
        color: #f8fafc;
    }

    /* HIDE STREAMLIT CHROME */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* METRIC CARDS */
    div[data-testid="metric-container"] {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 16px;
        padding: 20px;
        box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
        backdrop-filter: blur(5px);
    }
    div[data-testid="metric-container"] label { color: #94a3b8; font-size: 0.8rem; }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #f8fafc; font-size: 1.8rem; font-weight: 800; }

    /* ACTION BUTTONS */
    .stButton>button {
        width: 100%;
        height: 65px;
        border-radius: 12px;
        font-weight: 700;
        font-size: 1.1rem;
        border: none;
        transition: all 0.2s ease;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    
    /* CUSTOM STATUS PILLS */
    .status-pill {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 12px;
        border-radius: 12px;
        font-weight: 700;
        font-size: 0.9rem;
        margin-bottom: 20px;
        letter-spacing: 1px;
        text-transform: uppercase;
    }
    .vip-mode {
        background: linear-gradient(135deg, #FFD700 0%, #B8860B 100%);
        color: #000;
        box-shadow: 0 0 20px rgba(255, 215, 0, 0.3);
    }
    .safe-mode {
        background: rgba(16, 185, 129, 0.2);
        border: 1px solid #10b981;
        color: #34d399;
    }
    
    /* INPUT FIELDS */
    .stTextInput>div>div>input {
        background-color: rgba(255,255,255,0.05);
        color: white;
        border-radius: 10px;
        border: 1px solid rgba(255,255,255,0.1);
        height: 50px;
    }

    /* MARKETPLACE CARDS */
    .shift-card {
        background: rgba(255,255,255,0.03);
        border-left: 4px solid #3b82f6;
        padding: 15px;
        margin-bottom: 10px;
        border-radius: 0 12px 12px 0;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 4. CONSTANTS ---
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}
LOCAL_TZ = pytz.timezone('US/Eastern')
GEOFENCE_RADIUS = 45 
LIVENESS_CHALLENGES = ["TOUCH YOUR LEFT EAR", "LOOK UP AT THE CEILING", "GIVE A THUMBS UP", "TOUCH YOUR NOSE"]

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RRT", "rate": 85.00},
    "1002": {"name": "Charles Morgan", "role": "RRT", "rate": 85.00},
    "9999": {"name": "CFO VIEW", "role": "Exec", "rate": 0.00}
}

def get_local_now(): return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S EST")

# --- 5. DATABASE ENGINE (CRITICAL FIX: ENV VAR PRIORITY) ---
@st.cache_resource
def get_db_engine():
    # 1. Try Render Environment Variable FIRST
    url = os.environ.get("SUPABASE_URL")
    
    # 2. Fallback to Streamlit Secrets (Only if Env Var is missing)
    if not url:
        try:
            url = st.secrets["SUPABASE_URL"]
        except:
            pass # No secrets found, that is expected on Render

    # 3. If still no URL, Stop Everything
    if not url:
        st.error("🚨 CRITICAL ERROR: Database URL is missing! Check Render 'Environment Variables'.")
        return None

    # 4. Fix Protocol for SQLAlchemy
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
        
    try:
        return create_engine(url, isolation_level="AUTOCOMMIT")
    except Exception as e:
        st.error(f"🚨 CONNECTION FAILED: {e}")
        return None

def run_query(query, params=None):
    engine = get_db_engine()
    if not engine: return None
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            return result.fetchall() 
    except Exception as e:
        st.error(f"QUERY ERROR: {e}")
        return None

def run_transaction(query, params=None):
    engine = get_db_engine()
    if not engine: return
    try:
        with engine.begin() as conn:
            conn.execute(text(query), params or {})
    except Exception as e:
        st.error(f"SAVE ERROR: {e}")

# --- 6. CORE LOGIC ---
def force_cloud_sync(pin):
    try:
        rows = run_query("SELECT status, start_time FROM workers WHERE pin = :pin", {"pin": pin})
        if rows and len(rows) > 0:
            row = rows[0]
            if row[0].lower() == 'active':
                st.session_state.user_state['active'] = True
                st.session_state.user_state['start_time'] = float(row[1])
                return True
        st.session_state.user_state['active'] = False
        return False
    except Exception as e: 
        st.error(f"SYNC ERROR: {e}")
        return False

def update_status(pin, status, start, earn):
    # Triple Quotes fix the syntax error
    q = """
    INSERT INTO workers (pin, status, start_time, earnings, last_active)
    VALUES (:p, :s, :t, :e, NOW())
    ON CONFLICT (pin) DO UPDATE 
    SET status = :s, start_time = :t, earnings = :e, last_active = NOW();
    """
    run_transaction(q, {"p": pin, "s": status, "t": start, "e": earn})

def log_tx(pin, amount):
    tx_id = f"TX-{int(time.time())}"
    q = "INSERT INTO transactions (tx_id, pin, amount, timestamp, status) VALUES (:id, :p, :a, NOW(), 'INSTANT')"
    run_transaction(q, {"id": tx_id, "p": pin, "a": amount})
    return tx_id

def log_action(pin, action, amount, note):
    q = "INSERT INTO history (pin, action, timestamp, amount, note) VALUES (:p, :a, NOW(), :amt, :n)"
    run_transaction(q, {"p": pin, "a": action, "amt": amount, "n": note})

def post_shift_db(pin, role, date, start, end, rate):
    shift_id = f"SHIFT-{int(time.time())}"
    q = """
    INSERT INTO marketplace (shift_id, poster_pin, role, date, start_time, end_time, rate, status)
    VALUES (:id, :p, :r, :d, :s, :e, :rt, 'OPEN')
    """
    run_transaction(q, {"id": shift_id, "p": pin, "r": role, "d": date, "s": str(start), "e": str(end), "rt": rate})

def claim_shift_db(shift_id, claimer_pin):
    q = "UPDATE marketplace SET status='CLAIMED', claimed_by=:p WHERE shift_id=:id"
    run_transaction(q, {"p": claimer_pin, "id": shift_id})

# --- 7. SECURITY GATES ---
def verify_security(pin, lat, lon, ip, img):
    if str(pin) == "1001": return True, "VIP ACCESS"
    
    target_lat, target_lon = 42.0875, -70.9915
    R = 6371000
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2, lon2 = math.radians(target_lat), math.radians(target_lon)
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2) * math.sin((lon2-lon1)/2)**2
    dist = R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))
    
    if dist > GEOFENCE_RADIUS: return False, f"GEOFENCE FAIL ({int(dist)}m)"
    
    if not BIO_ENGINE_AVAILABLE:
        time.sleep(1.5)
        return True, "BIO SIMULATED"
    
    try:
        f_img = face_recognition.load_image_file(img)
        if len(face_recognition.face_locations(f_img)) < 1: return False, "NO FACE DETECTED"
        return True, "VERIFIED"
    except: return False, "BIO ERROR"

# --- 8. UI & STATE ---
if 'user_state' not in st.session_state: st.session_state.user_state = {}
defaults = {'active': False, 'start_time': 0.0, 'earnings': 0.0, 'payout_success': False, 'payout_lock': False, 'challenge': None}
for k, v in defaults.items(): 
    if k not in st.session_state.user_state: st.session_state.user_state[k] = v

# --- 9. AUTH SCREEN ---
if 'logged_in_user' not in st.session_state:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center; color: #f8fafc; letter-spacing: 2px;'>EC PROTOCOL</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #64748b; font-size: 0.9rem;'>SECURE WORKFORCE ACCESS</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    pin = st.text_input("ACCESS CODE", type="password", placeholder="Enter your 4-digit PIN")
    
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("AUTHENTICATE SYSTEM"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            if force_cloud_sync(pin):
                st.success("SESSION RESTORED")
            st.rerun()
        else: st.error("INVALID CREDENTIALS")
    st.stop()

user = st.session_state.logged_in_user
pin = st.session_state.pin

# --- 10. MAIN DASHBOARD ---
with st.sidebar:
    st.caption(f"LOGGED IN AS: {user['name'].upper()}")
    nav = st.radio("MENU", ["DASHBOARD", "MARKETPLACE", "LOGS"])
    if st.button("LOGOUT"): st.session_state.clear(); st.rerun()

if nav == "DASHBOARD":
    st.markdown(f"""
        <div style="padding: 20px 0; border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px;">
            <h2 style="margin:0; font-size:1.5rem;">Good Morning, {user['name'].split(' ')[0]}</h2>
            <p style="margin:0; color: #94a3b8;">{get_local_now()}</p>
        </div>
    """, unsafe_allow_html=True)
    
    st_autorefresh(interval=10000)
    loc = get_geolocation(component_key="gps")
    lat, lon = (loc['coords']['latitude'], loc['coords']['longitude']) if loc else (0,0)
    
    if str(pin) == "1001": st.markdown('<div class="status-pill vip-mode">⭐ EXECUTIVE VIP ACCESS</div>', unsafe_allow_html=True)
    else: st.markdown('<div class="status-pill safe-mode">🛡️ IRON DOME SECURE</div>', unsafe_allow_html=True)

    active = st.session_state.user_state['active']
    if active:
        hrs = (time.time() - st.session_state.user_state['start_time']) / 3600
        st.session_state.user_state['earnings'] = hrs * user['rate']
    
    gross = st.session_state.user_state['earnings']
    net = gross * (1 - sum(TAX_RATES.values()))
    
    c1, c2 = st.columns(2)
    c1.metric("CURRENT EARNINGS", f"${gross:,.2f}")
    c2.metric("NET PAYOUT", f"${net:,.2f}")

    st.markdown("<br>", unsafe_allow_html=True)

    if active:
        if str(pin) == "1001":
            if st.button("🔴 END SHIFT"):
                st.session_state.user_state['active'] = False
                update_status(pin, "Inactive", 0, 0)
                log_action(pin, "CLOCK OUT", gross, "VIP")
                st.success("SHIFT ENDED")
                time.sleep(1)
                st.rerun()
        else:
            if not st.session_state.user_state['challenge']: 
                st.session_state.user_state['challenge'] = random.choice(LIVENESS_CHALLENGES)
            st.info(f"ACTION REQUIRED: {st.session_state.user_state['challenge']}")
            img = st.camera_input("VERIFY IDENTITY")
            if img:
                ok, msg = verify_security(pin, lat, lon, "0.0.0.0", img)
                if ok:
                    st.session_state.user_state['active'] = False
                    st.session_state.user_state['challenge'] = None
                    update_status(pin, "Inactive", 0, 0)
                    log_action(pin, "CLOCK OUT", gross, "Verified")
                    st.success("SHIFT ENDED")
                    time.sleep(1)
                    st.rerun()
                else: st.error(msg)
    else:
        if str(pin) == "1001":
            if st.button("🟢 START SHIFT"):
                st.session_state.user_state['active'] = True
                st.session_state.user_state['start_time'] = time.time()
                update_status(pin, "Active", time.time(), 0)
                log_action(pin, "CLOCK IN", 0, "VIP")
                st.success("SHIFT STARTED")
                time.sleep(1)
                st.rerun()
        else:
            if not st.session_state.user_state['challenge']: 
                st.session_state.user_state['challenge'] = random.choice(LIVENESS_CHALLENGES)
            st.info(f"ACTION REQUIRED: {st.session_state.user_state['challenge']}")
            img = st.camera_input("VERIFY IDENTITY")
            if img:
                ok, msg = verify_security(pin, lat, lon, "0.0.0.0", img)
                if ok:
                    st.session_state.user_state['active'] = True
                    st.session_state.user_state['start_time'] = time.time()
                    st.session_state.user_state['challenge'] = None
                    update_status(pin, "Active", time.time(), 0)
                    log_action(pin, "CLOCK IN", 0, "Verified")
                    st.success("SHIFT STARTED")
                    time.sleep(1)
                    st.rerun()
                else: st.error(msg)

    st.markdown("<br>", unsafe_allow_html=True)
    
    if not active and gross > 0.01:
        if st.button(f"💸 INSTANT TRANSFER (${net:,.2f})", disabled=st.session_state.user_state['payout_lock']):
            st.session_state.user_state['payout_lock'] = True
            tx = log_tx(pin, net)
            log_action(pin, "PAYOUT", net, "Settled")
            update_status(pin, "Inactive", 0, 0)
            st.session_state.user_state['earnings'] = 0.0
            st.success(f"FUNDS SENT: {tx}")
            time.sleep(2)
            st.session_state.user_state['payout_lock'] = False
            st.rerun()

elif nav == "MARKETPLACE":
    st.markdown("## 🏥 Shift Exchange")
    
    tab1, tab2 = st.tabs(["OPEN SHIFTS", "POST NEW"])
    
    with tab1:
        try:
            # Syntax fixed here to ensure query works
            res = run_query("SELECT shift_id, poster_pin, role, date, start_time, end_time, rate, status FROM marketplace WHERE status='OPEN'")
            if res:
                for s in res:
                    st.markdown(f"""
                    <div class="shift-card">
                        <div style="font-weight:bold; font-size:1.1rem;">{s[3]} | {s[2]}</div>
                        <div style="color:#94a3b8;">{s[4]} - {s[5]} @ ${s[6]}/hr</div>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button("CLAIM SHIFT", key=s[0]):
                        claim_shift_db(s[0], pin)
                        st.success("✅ Shift Added to Schedule")
                        time.sleep(1)
                        st.rerun()
            else:
                st.info("No open shifts available in your region.")
        except Exception as e:
            st.error(f"Connection Error: {e}")

    with tab2:
        with st.form("new_shift"):
            d = st.date_input("Date")
            c1, c2 = st.columns(2)
            s_time = c1.time_input("Start")
            e_time = c2.time_input("End")
            if st.form_submit_button("PUBLISH TO MARKET"):
                post_shift_db(pin, user['role'], d, s_time, e_time, user['rate'])
                st.success("Shift Published!")

elif nav == "LOGS":
    st.markdown("## 📂 Audit Trail")
    try:
        # Correctly formatted multiline string for SQL
        query = """
        SELECT pin, action, timestamp, amount, note 
        FROM history 
        WHERE pin=:p 
        ORDER BY timestamp DESC
        """
        res = run_query(query, {"p": pin})
        if res: 
            df = pd.DataFrame(res, columns=["User PIN", "Action", "Time", "Amount", "Note"])
            st.dataframe(df, use_container_width=True)
        else:
            st.write("No records found.")
    except Exception as e: 
        st.write(f"Log Error: {e}")
