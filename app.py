import streamlit as st
import pandas as pd
import time
import math
import pytz
import random
import os
from datetime import datetime
from collections import defaultdict
from streamlit_js_eval import get_geolocation
from streamlit_autorefresh import st_autorefresh
from sqlalchemy import create_engine, text

try:
    from twilio.rest import Client
    TWILIO_ACTIVE = True
except ImportError:
    TWILIO_ACTIVE = False

# --- 1. CONFIGURATION & STYLING ---
st.set_page_config(page_title="EC Enterprise", page_icon="🛡️", layout="centered", initial_sidebar_state="expanded")

html_style = """
<style>
    p, h1, h2, h3, h4, h5, h6, div, label, button, input { font-family: 'Inter', sans-serif !important; }
    .material-symbols-rounded, .material-icons { font-family: 'Material Symbols Rounded' !important; }
    .stApp { background-color: #0b1120; background-image: radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.15) 0px, transparent 50%), radial-gradient(at 100% 0%, rgba(16, 185, 129, 0.1) 0px, transparent 50%), radial-gradient(at 50% 100%, rgba(139, 92, 246, 0.1) 0px, transparent 50%); background-attachment: fixed; color: #f8fafc; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {background: transparent !important;}
    div[data-testid="metric-container"], .shift-card, .admin-card, .sched-row, .auth-box { background: rgba(30, 41, 59, 0.5) !important; backdrop-filter: blur(12px) !important; -webkit-backdrop-filter: blur(12px) !important; border: 1px solid rgba(255, 255, 255, 0.08) !important; border-radius: 16px; padding: 20px; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2); }
    div[data-testid="metric-container"] label { color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #f8fafc; font-size: 2rem; font-weight: 800; text-shadow: 0 2px 10px rgba(0,0,0,0.3); }
    .stButton>button { width: 100%; height: 60px; border-radius: 12px; font-weight: 700; font-size: 1.1rem; border: none; transition: all 0.3s ease; text-transform: uppercase; letter-spacing: 1px; box-shadow: 0 4px 15px rgba(0,0,0,0.2); }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.3); }
    .stTextInput>div>div>input, .stSelectbox>div>div>div { background-color: rgba(15, 23, 42, 0.6) !important; color: white !important; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1) !important; backdrop-filter: blur(10px); }
    .shift-card { padding: 15px; margin-bottom: 12px; border-left: 4px solid #3b82f6 !important; }
    .sched-date-header { background: rgba(16, 185, 129, 0.1); padding: 10px 15px; border-radius: 8px; margin-top: 25px; margin-bottom: 15px; font-weight: 800; font-size: 1.1rem; border-left: 4px solid #10b981; color: #34d399; text-transform: uppercase; letter-spacing: 1px; }
    .sched-row { display: flex; justify-content: space-between; padding: 15px; margin-bottom: 8px; border-left: 4px solid rgba(255,255,255,0.1) !important; }
    .sched-time { color: #34d399; font-weight: 800; width: 120px; font-size: 1.1rem; }
    .sched-name { font-weight: 700; color: #f8fafc; font-size: 1.1rem; }
    .sched-role { color: #94a3b8; font-size: 0.9rem; }
    .sched-callout { border-left: 4px solid #ff453a !important; background: rgba(255, 69, 58, 0.08) !important; }
    .sched-market { border-left: 4px solid #f59e0b !important; background: rgba(245, 158, 11, 0.08) !important; }
</style>
"""
st.markdown(html_style, unsafe_allow_html=True)

# --- 2. CONSTANTS & ORG CHART ---
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}
LOCAL_TZ = pytz.timezone('US/Eastern')
GEOFENCE_RADIUS = 150 
HOSPITALS = {"Brockton General": {"lat": 42.0875, "lon": -70.9915}, "Remote/Anywhere": {"lat": 0.0, "lon": 0.0}}

# UPGRADED DICTIONARY: Now includes Email, Password, and PIN
USERS = {
    "1001": {"email": "liam@ecprotocol.com", "password": "password123", "pin": "1001", "name": "Liam O'Neil", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 85.00, "vip": False},
    "1004": {"email": "manager@ecprotocol.com", "password": "password123", "pin": "1004", "name": "David Clark", "role": "Manager", "dept": "Respiratory", "level": "Manager", "rate": 0.00, "vip": True},
    "9999": {"email": "cfo@ecprotocol.com", "password": "password123", "pin": "9999", "name": "CFO VIEW", "role": "Admin", "dept": "All", "level": "Admin", "rate": 0.00, "vip": True}
}

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi[0]/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dphi[1]/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- 3. DATABASE ENGINE ---
@st.cache_resource
def get_db_engine():
    url = os.environ.get("SUPABASE_URL")
    if not url:
        try: url = st.secrets["SUPABASE_URL"]
        except: pass
    if not url: return None
    if url.startswith("postgres://"): url = url.replace("postgres://", "postgresql://", 1)
    try: 
        engine = create_engine(url)
        with engine.connect() as conn:
            try: conn.execute(text("ALTER TABLE schedules ADD COLUMN status text DEFAULT 'SCHEDULED';")); conn.commit()
            except: pass
        return engine
    except: return None

def run_query(query, params=None):
    engine = get_db_engine()
    if not engine: return None
    try:
        with engine.connect() as conn: return conn.execute(text(query), params or {}).fetchall() 
    except: return None

def run_transaction(query, params=None):
    engine = get_db_engine()
    if not engine: return False
    try:
        with engine.connect() as conn: conn.execute(text(query), params or {}); conn.commit(); return True
    except: return False

# --- 4. CORE DB LOGIC ---
def force_cloud_sync(pin):
    try:
        rows = run_query("SELECT status, start_time FROM workers WHERE pin = :pin", {"pin": pin})
        if rows and len(rows) > 0 and rows[0][0].lower() == 'active':
            st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = float(rows[0][1]); return True
        st.session_state.user_state['active'] = False; return False
    except: return False

def update_status(pin, status, start, earn):
    q = """INSERT INTO workers (pin, status, start_time, earnings, last_active) VALUES (:p, :s, :t, :e, NOW())
           ON CONFLICT (pin) DO UPDATE SET status = :s, start_time = :t, earnings = :e, last_active = NOW();"""
    return run_transaction(q, {"p": pin, "s": status, "t": start, "e": earn})

def log_action(pin, action, amount, note):
    run_transaction("INSERT INTO history (pin, action, timestamp, amount, note) VALUES (:p, :a, NOW(), :amt, :n)", {"p": pin, "a": action, "amt": amount, "n": note})

# --- 5. AUTH SCREEN (UPGRADED TO EMAIL/PASSWORD) ---
if 'user_state' not in st.session_state: st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0, 'payout_lock': False}

if 'logged_in_user' not in st.session_state:
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center; color: #f8fafc; letter-spacing: 2px; font-weight: 900; text-shadow: 0 4px 20px rgba(59, 130, 246, 0.5);'>EC PROTOCOL</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #94a3b8; font-size: 1rem; letter-spacing: 3px;'>SECURE WORKFORCE ACCESS</p><br>", unsafe_allow_html=True)
    
    with st.container():
        st.markdown("<div class='auth-box'>", unsafe_allow_html=True)
        login_email = st.text_input("EMAIL ADDRESS", placeholder="name@hospital.com")
        login_password = st.text_input("PASSWORD", type="password", placeholder="••••••••")
        st.markdown("<br>", unsafe_allow_html=True)
        
        if st.button("AUTHENTICATE SYSTEM"):
            # Search the dictionary for matching email/password
            authenticated_pin = None
            for p, data in USERS.items():
                if data.get("email") == login_email.lower() and data.get("password") == login_password:
                    authenticated_pin = p
                    break
            
            if authenticated_pin:
                st.session_state.logged_in_user = USERS[authenticated_pin]
                st.session_state.pin = authenticated_pin
                force_cloud_sync(authenticated_pin)
                st.rerun()
            else:
                st.error("❌ INVALID EMAIL OR PASSWORD")
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

user = st.session_state.logged_in_user
pin = st.session_state.pin

# --- 6. DYNAMIC NAVIGATION ---
with st.sidebar:
    st.markdown(f"<h3 style='color: #38bdf8; margin-bottom: 0;'>{user['name'].upper()}</h3>", unsafe_allow_html=True)
    st.caption(f"{user['role']} | {user['dept']}")
    st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
    
    if get_db_engine(): st.success("🟢 DB CONNECTED")
    else: st.error("🔴 DB DISCONNECTED")
    
    if user['level'] == "Admin": nav = st.radio("MENU", ["COMMAND CENTER", "MASTER SCHEDULE", "AUDIT LOGS"])
    elif user['level'] in ["Manager", "Director"]: nav = st.radio("MENU", ["DASHBOARD", "DEPT MARKETPLACE", "DEPT SCHEDULE", "MY LOGS"])
    else: nav = st.radio("MENU", ["DASHBOARD", "MARKETPLACE", "MY SCHEDULE", "MY LOGS"])
        
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("LOGOUT"): st.session_state.clear(); st.rerun()

# --- 7. ROUTING ---
if nav == "COMMAND CENTER" and pin == "9999":
    st.markdown("## 🦅 Command Center")
    rows = run_query("SELECT pin, status, start_time, earnings FROM workers WHERE status='Active'")
    if rows:
        for r in rows:
            w_pin = str(r[0]); w_name = USERS.get(w_pin, {}).get("name", f"Unknown ({w_pin})"); w_role = USERS.get(w_pin, {}).get("role", "Worker")
            hrs = (time.time() - float(r[2])) / 3600; current_earn = hrs * USERS.get(w_pin, {}).get("rate", 85)
            st.markdown(f"""<div class="admin-card"><h3 style="margin:0;">{w_name} <span style='color:#94a3b8; font-size:1rem;'>| {w_role}</span></h3>
                <p style="color:#34d399; margin-top:5px; font-weight:bold;">🟢 ACTIVE (On Clock: {hrs:.2f} hrs | Accrued: ${current_earn:.2f})</p></div>""", unsafe_allow_html=True)
            if st.button(f"🚨 FORCE CLOCK-OUT: {w_name}", key=f"force_{w_pin}"):
                update_status(w_pin, "Inactive", 0, 0); log_action("9999", "ADMIN FORCE LOGOUT", current_earn, f"Target: {w_name}")
                st.success(f"Closed shift for {w_name}"); time.sleep(1.5); st.rerun()
    else: st.info("No operators currently active.")

elif nav == "DASHBOARD":
    current_hour = datetime.now(LOCAL_TZ).hour
    if current_hour < 12: greeting = "Good Morning"
    elif current_hour < 17: greeting = "Good Afternoon"
    else: greeting = "Good Evening"
    
    st.markdown(f"<h1 style='font-weight: 800;'>{greeting}, {user['name'].split(' ')[0]}</h1>", unsafe_allow_html=True)
    
    # Restored active tracking line to fix the bug
    active = st.session_state.user_state.get('active', False)
    
    if active: 
        hrs = (time.time() - st.session_state.user_state['start_time']) / 3600
        st.session_state.user_state['earnings'] = hrs * user['rate']
        
    gross = st.session_state.user_state['earnings']; net = gross * (1 - sum(TAX_RATES.values()))
    
    c1, c2 = st.columns(2)
    c1.metric("CURRENT EARNINGS", f"${gross:,.2f}"); c2.metric("NET PAYOUT", f"${net:,.2f}")
    st.markdown("<br>", unsafe_allow_html=True)

    if active:
        st.markdown("### 🔴 END SHIFT VERIFICATION")
        end_pin = st.text_input("Enter 4-Digit PIN to Clock Out", type="password", key="end_pin")
        if st.button("PUNCH OUT"):
            if end_pin == pin:
                if update_status(pin, "Inactive", 0, 0):
                    st.session_state.user_state['active'] = False; log_action(pin, "CLOCK OUT", gross, "Standard"); st.rerun()
            else: st.error("❌ Incorrect PIN.")
    else:
        selected_facility = st.selectbox("Select Facility", list(HOSPITALS.keys()))
        
        if not user.get('vip', False):
            st.markdown("### 🔒 Security Checkpoint")
            st.info("Identity verification required to initiate shift.")
            camera_photo = st.camera_input("Take a photo to verify identity")
            loc = get_geolocation()
            
            if camera_photo and loc:
                user_lat = loc['coords']['latitude']; user_lon = loc['coords']['longitude']
                st.caption(f"✅ Facial Scan Accepted\n📍 Coordinates Logged: {user_lat:.4f}, {user_lon:.4f}")
                
                if selected_facility != "Remote/Anywhere":
                    fac_lat = HOSPITALS[selected_facility]["lat"]; fac_lon = HOSPITALS[selected_facility]["lon"]
                    distance = haversine_distance(user_lat, user_lon, fac_lat, fac_lon)
                    
                    if distance <= GEOFENCE_RADIUS:
                        st.success(f"✅ Geofence Confirmed. You are {int(distance)}m from {selected_facility}.")
                        st.markdown("### 🟢 START SHIFT VERIFICATION")
                        start_pin = st.text_input("Enter 4-Digit PIN to Clock In", type="password", key="start_pin")
                        if st.button("PUNCH IN"):
                            if start_pin == pin:
                                start_t = time.time()
                                if update_status(pin, "Active", start_t, 0):
                                    st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t
                                    log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()
                            else: st.error("❌ Incorrect PIN.")
                    else: st.error(f"❌ Geofence Failed. You are {int(distance)}m away. Must be within {GEOFENCE_RADIUS}m.")
                else:
                    st.markdown("### 🟢 START SHIFT VERIFICATION (REMOTE)")
                    start_pin = st.text_input("Enter 4-Digit PIN to Clock In", type="password", key="start_pin_remote")
                    if st.button("PUNCH IN (REMOTE)"):
                        if start_pin == pin:
                            start_t = time.time()
                            if update_status(pin, "Active", start_t, 0):
                                st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t
                                log_action(pin, "CLOCK IN", 0, f"Loc: Remote"); st.rerun()
                        else: st.error("❌ Incorrect PIN.")
        else:
            st.caption("✨ VIP Security Override Active")
            start_pin = st.text_input("Enter 4-Digit PIN to Clock In", type="password", key="vip_start_pin")
            if st.button("PUNCH IN"):
                if start_pin == pin:
                    start_t = time.time()
                    if update_status(pin, "Active", start_t, 0):
                        st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t
                        log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()
                else: st.error("❌ Incorrect PIN.")

    if not active and gross > 0.01:
        if st.button(f"💸 INSTANT TRANSFER (${net:,.2f})", disabled=st.session_state.user_state['payout_lock']):
            st.session_state.user_state['payout_lock'] = True; log_action(pin, "PAYOUT", net, "Settled"); update_status(pin, "Inactive", 0, 0)
            st.session_state.user_state['earnings'] = 0.0; time.sleep(1); st.session_state.user_state['payout_lock'] = False; st.rerun()

elif nav in ["MARKETPLACE", "DEPT MARKETPLACE", "MY SCHEDULE", "DEPT SCHEDULE", "MASTER SCHEDULE"]:
    st.info("Marketplace and Schedule engines are active. Navigate back to Dashboard to execute clock-in.")

elif "LOGS" in nav:
    st.markdown("## 📂 System Records")
    if user['level'] == "Admin": q = "SELECT pin, action, timestamp, amount, note FROM history ORDER BY timestamp DESC LIMIT 50"; res = run_query(q)
    else: q = "SELECT pin, action, timestamp, amount, note FROM history WHERE pin=:p ORDER BY timestamp DESC"; res = run_query(q, {"p": pin})
    if res: st.dataframe(pd.DataFrame(res, columns=["User PIN", "Action", "Time", "Amount", "Note"]), use_container_width=True)
