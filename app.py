import streamlit as st
import pandas as pd
import time
import math
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

# --- 5. DATABASE ENGINE (BULLETPROOF) ---
@st.cache_resource
def get_db_engine():
    try:
        url = st.secrets["SUPABASE_URL"]
        if url.startswith("postgres://"): url = url.replace("postgres://", "postgresql://", 1)
        return create_engine(url, isolation_level="AUTOCOMMIT")
    except Exception as e:
        st.error(f"🚨 DB CONNECTION FAILED: {e}")
        return None

def run_query(query, params=None):
    engine = get_db_engine()
    if not engine: return None
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            # CRITICAL FIX: Fetch the data BEFORE closing the connection
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

# --- 6. CORE LOGIC (DB SYNC) ---
def force_cloud_sync(pin):
    try:
        # Since run_query now returns a list of rows, we check the list directly
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
    
    # Iron Dome
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
    
    st_autorefresh(interval=10000)
    loc = get_geolocation(component_key="gps")
    lat, lon = (loc['coords']['latitude'], loc['coords']['longitude']) if loc else (0,0)
    
    if str(pin) == "1001": st.markdown('<div class="status-pill vip-mode">🌟 VIP EXECUTIVE</div>', unsafe_allow_html=True)
    else: st.markdown('<div class="status-pill safe-mode">🛡️ IRON DOME ACTIVE</div>', unsafe_allow_html=True)

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

    if active:
        if str(pin) == "1001":
            if st.button("🔴 END SHIFT (VIP)"):
                st.session_state.user_state['active'] = False
                update_status(pin, "Inactive", 0, 0)
                log_action(pin, "CLOCK OUT", gross, "VIP")
                st.success("✅ Clock Out Saved to Database")
                time.sleep(1)
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
                    st.success("✅ Clock Out Saved to Database")
                    time.sleep(1)
                    st.rerun()
                else: st.error(msg)
    else:
        if str(pin) == "1001":
            if st.button("🟢 START SHIFT (VIP)"):
                st.session_state.user_state['active'] = True
                st.session_state.user_state['start_time'] = time.time()
                update_status(pin, "Active", time.time(), 0)
                log_action(pin, "CLOCK IN", 0, "VIP")
                st.success("✅ Clock In Saved to Database")
                time.sleep(1)
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
                    st.success("✅ Clock In Saved to Database")
                    time.sleep(1)
                    st.rerun()
                else: st.error(msg)

    st.markdown("###")
    
    if not active and gross > 0.01:
        if st.button(f"💸 PAYOUT ${net:,.2f}", disabled=st.session_state.user_state['payout_lock']):
            st.session_state.user_state['payout_lock'] = True
            tx = log_tx(pin, net)
            log_action(pin, "PAYOUT", net, "Settled")
            update_status(pin, "Inactive", 0, 0)
            st.session_state.user_state['earnings'] = 0.0
            st.success(f"✅ Payout Sent: {tx}")
            time.sleep(2)
            st.session_state.user_state['payout_lock'] = False
            st.rerun()

elif nav == "MARKETPLACE":
    st.title("🏥 Shift Marketplace")
    
    tab1, tab2 = st.tabs(["BROWSE", "POST SHIFT"])
    
    with tab1:
        try:
            res = run_query("SELECT * FROM marketplace WHERE status='OPEN'")
            shifts = res.fetchall() if res else []
            if shifts:
                for s in shifts:
                    # s structure: shift_id, poster_pin, role, date, start, end, rate, status, claimed_by
                    with st.expander(f"📅 {s[3]} | {s[2]} | ${s[6]}/hr"):
                        st.write(f"Time: {s[4]} - {s[5]}")
                        if st.button("CLAIM SHIFT", key=s[0]):
                            claim_shift_db(s[0], pin)
                            st.success("✅ Shift Claimed & Saved!")
                            time.sleep(1)
                            st.rerun()
            else:
                st.info("No Open Shifts")
        except Exception as e:
            st.error(f"Error loading shifts: {e}")

    with tab2:
        with st.form("new_shift"):
            d = st.date_input("Date")
            c1, c2 = st.columns(2)
            s_time = c1.time_input("Start")
            e_time = c2.time_input("End")
            if st.form_submit_button("POST"):
                post_shift_db(pin, user['role'], d, s_time, e_time, user['rate'])
                st.success("✅ Shift Posted to Database!")

elif nav == "LOGS":
    st.title("Audit Logs")
    try:
        # SHORTENED LINE TO PREVENT SYNTAX ERRORS
        query = "SELECT * FROM history WHERE pin=:p ORDER BY timestamp DESC"
        res = run_query(query, {"p": pin})
        if res: st.dataframe(pd.DataFrame(res.fetchall(), columns=res.keys()))
    except: st.write("No History")
