import streamlit as st
import pandas as pd
import time
import math
import requests
import pytz
import random
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
    initial_sidebar_state="expanded"
)

# --- 2. SMART LIBRARY LOADER (Prevents Crashes) ---
try:
    import face_recognition
    BIO_ENGINE_AVAILABLE = True
except ImportError:
    BIO_ENGINE_AVAILABLE = False # Automatically enables Simulation Mode

# --- 3. STYLING ---
st.markdown("""
    <head><meta name="apple-mobile-web-app-capable" content="yes"><meta name="theme-color" content="#0E1117"></head>
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;}
    .stApp { background: radial-gradient(circle at 50% -20%, #1c2331, #0E1117); color: #FFFFFF; font-family: 'Inter', sans-serif; }
    div[data-testid="stMap"] { border-radius: 16px; overflow: hidden; border: 1px solid rgba(255,255,255,0.2); }
    .status-pill { display: flex; align-items: center; justify-content: center; padding: 12px; border-radius: 50px; font-weight: 600; margin-bottom: 20px; backdrop-filter: blur(10px); }
    .safe-mode { background: rgba(28, 79, 46, 0.4); border: 1px solid #2e7d32; color: #4caf50; }
    .danger-mode { background: rgba(79, 28, 28, 0.4); border: 1px solid #c62828; color: #ff5252; }
    .vip-mode { background: rgba(255, 215, 0, 0.2); border: 1px solid #FFD700; color: #FFD700; }
    div[data-testid="metric-container"] { background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; }
    .stButton>button { width: 100%; height: 60px; border-radius: 12px; font-weight: 700; border: none; }
    .hero-header { text-align: center; padding: 30px 20px; background: linear-gradient(180deg, rgba(14,17,23,0) 0%, rgba(14,17,23,1) 100%), url("https://images.unsplash.com/photo-1550751827-4bd374c3f58b?q=80&w=2670&auto=format&fit=crop"); background-size: cover; border-radius: 0 0 24px 24px; margin-top: -60px; margin-bottom: 30px; }
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

# --- 5. SUPABASE CONNECTION ---
@st.cache_resource
def get_db_engine():
    try:
        url = st.secrets["SUPABASE_URL"]
        if url.startswith("postgres://"): url = url.replace("postgres://", "postgresql://", 1)
        return create_engine(url)
    except: return None

def run_query(query, params=None):
    engine = get_db_engine()
    if not engine: return None
    with engine.connect() as conn:
        return conn.execute(text(query), params or {})

def run_transaction(query, params=None):
    engine = get_db_engine()
    if not engine: return
    with engine.begin() as conn:
        conn.execute(text(query), params or {})

# --- 6. CORE LOGIC ---
def force_cloud_sync(pin):
    try:
        res = run_query("SELECT status, start_time, earnings FROM workers WHERE pin = :pin", {"pin": pin})
        row = res.fetchone()
        if row and row[0].lower() == 'active':
            st.session_state.user_state['active'] = True
            st.session_state.user_state['start_time'] = float(row[1])
            return True
        st.session_state.user_state['active'] = False
        return False
    except: return False

def update_status(pin, status, start, earn):
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

# --- 7. SECURITY GATES (LIGHTWEIGHT EDITION) ---
def verify_security(pin, lat, lon, ip, img):
    # VIP BYPASS (1001)
    if str(pin) == "1001": return True, "VIP ACCESS GRANTED"
    
    # IRON DOME CHECKS
    # 1. Geofence
    target_lat, target_lon = 42.0875, -70.9915
    R = 6371000
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2, lon2 = math.radians(target_lat), math.radians(target_lon)
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2) * math.sin((lon2-lon1)/2)**2
    dist = R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))
    
    # In Pilot/Dev mode, we might relax this or use a larger radius
    if dist > GEOFENCE_RADIUS: return False, f"GEOFENCE FAIL ({int(dist)}m)"
    
    # 2. Bio-Liveness (SIMULATION MODE)
    if not BIO_ENGINE_AVAILABLE: 
        # Since we removed the heavy library, we simulate the check
        time.sleep(1.5) # Simulate processing time
        return True, "BIO VERIFIED (SIMULATION)"
    
    # This part only runs if you reinstall the library later
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
    st.markdown("<h1 style='text-align: center;'>🛡️ EC PROTOCOL</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        pin = st.text_input("ACCESS CODE", type="password")
        if st.button("AUTHENTICATE"):
            if pin in USERS:
                st.session_state.logged_in_user = USERS[pin]
                st.session_state.pin = pin
                force_cloud_sync(pin)
                st.rerun()
            else: st.error("INVALID PIN")
    st.stop()

user = st.session_state.logged_in_user
pin = st.session_state.pin

# --- 10. MAIN APP ---
with st.sidebar:
    st.markdown("### 🧭 NAVIGATION")
    nav = st.radio("GO TO:", ["DASHBOARD", "MARKETPLACE", "LOGS"])
    if st.button("LOGOUT"): st.session_state.clear(); st.rerun()

if nav == "DASHBOARD":
    st.markdown(f"""<div class="hero-header"><h2>EC ENTERPRISE</h2><div>OPERATOR: {user['name'].upper()}</div></div>""", unsafe_allow_html=True)
    
    # PULSE & GEO
    st_autorefresh(interval=10000)
    loc = get_geolocation(component_key="gps")
    lat, lon = (loc['coords']['latitude'], loc['coords']['longitude']) if loc else (0,0)
    
    # VIP BADGE
    if str(pin) == "1001": st.markdown('<div class="status-pill vip-mode">🌟 VIP EXECUTIVE</div>', unsafe_allow_html=True)
    else: st.markdown('<div class="status-pill safe-mode">🛡️ IRON DOME ACTIVE</div>', unsafe_allow_html=True)

    # METRICS
    active = st.session_state.user_state['active']
    if active:
        hrs = (time.time() - st.session_state.user_state['start_time']) / 3600
        st.session_state.user_state['earnings'] = hrs * user['rate']
    
    gross = st.session_state.user_state['earnings']
    net = gross * (1 - sum(TAX_RATES.values()))
    
    c1, c2 = st.columns(2)
    c1.metric("GROSS", f"${gross:,.2f}")
    c2.metric("NET AVAIL", f"${net:,.2f}")

    st.markdown("###")

    # ACTIONS
    if active:
        # CLOCK OUT
        if str(pin) == "1001":
            if st.button("🔴 END SHIFT (VIP)"):
                st.session_state.user_state['active'] = False
                update_status(pin, "Inactive", 0, 0)
                log_action(pin, "CLOCK OUT", gross, "VIP")
                st.rerun()
        else:
            if not st.session_state.user_state['challenge']: 
                st.session_state.user_state['challenge'] = random.choice(LIVENESS_CHALLENGES)
            st.info(f"📸 ACTION: **{st.session_state.user_state['challenge']}**")
            img = st.camera_input("VERIFY")
            if img:
                ok, msg = verify_security(pin, lat, lon, "0.0.0.0", img)
                if ok:
                    st.session_state.user_state['active'] = False
                    st.session_state.user_state['challenge'] = None
                    update_status(pin, "Inactive", 0, 0)
                    log_action(pin, "CLOCK OUT", gross, "Verified")
                    st.rerun()
                else: st.error(msg)
    else:
        # CLOCK IN
        if str(pin) == "1001":
            if st.button("🟢 START SHIFT (VIP)"):
                st.session_state.user_state['active'] = True
                st.session_state.user_state['start_time'] = time.time()
                update_status(pin, "Active", time.time(), 0)
                log_action(pin, "CLOCK IN", 0, "VIP")
                st.rerun()
        else:
            if not st.session_state.user_state['challenge']: 
                st.session_state.user_state['challenge'] = random.choice(LIVENESS_CHALLENGES)
            st.info(f"📸 ACTION: **{st.session_state.user_state['challenge']}**")
            img = st.camera_input("VERIFY")
            if img:
                ok, msg = verify_security(pin, lat, lon, "0.0.0.0", img)
                if ok:
                    st.session_state.user_state['active'] = True
                    st.session_state.user_state['start_time'] = time.time()
                    st.session_state.user_state['challenge'] = None
                    update_status(pin, "Active", time.time(), 0)
                    log_action(pin, "CLOCK IN", 0, "Verified")
                    st.rerun()
                else: st.error(msg)

    st.markdown("###")
    
    # PAYOUT (ATOMIC)
    if not active and gross > 0.01:
        if st.button(f"💸 PAYOUT ${net:,.2f}", disabled=st.session_state.user_state['payout_lock']):
            st.session_state.user_state['payout_lock'] = True
            tx = log_tx(pin, net)
            log_action(pin, "PAYOUT", net, "Settled")
            update_status(pin, "Inactive", 0, 0)
            st.session_state.user_state['earnings'] = 0.0
            st.success(f"SENT: {tx}")
            time.sleep(2)
            st.session_state.user_state['payout_lock'] = False
            st.rerun()

elif nav == "MARKETPLACE":
    st.title("Marketplace")
    st.info("Connecting to Supabase...")

elif nav == "LOGS":
    st.title("Audit Logs")
    try:
        res = run_query("SELECT * FROM transactions WHERE pin=:p ORDER BY timestamp DESC", {"p": pin})
        if res: st.dataframe(pd.DataFrame(res.fetchall(), columns=res.keys()))
    except: st.write("No History")
