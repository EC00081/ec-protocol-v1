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

# --- NEW LIBRARIES ---
try:
    from twilio.rest import Client
    TWILIO_ACTIVE = True
except ImportError:
    TWILIO_ACTIVE = False

try:
    from fpdf import FPDF
    PDF_ACTIVE = True
except ImportError:
    PDF_ACTIVE = False

# --- 1. CONFIGURATION & STYLING ---
st.set_page_config(page_title="EC Enterprise", page_icon="🛡️", layout="centered", initial_sidebar_state="expanded")

html_style = """
<style>
    p, h1, h2, h3, h4, h5, h6, div, label, button, input { font-family: 'Inter', sans-serif !important; }
    .material-symbols-rounded, .material-icons { font-family: 'Material Symbols Rounded' !important; }
    
    .stApp { background: radial-gradient(circle at 50% 0%, #1e293b, #0f172a); color: #f8fafc; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {background: transparent !important;}
    div[data-testid="metric-container"] { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 16px; padding: 20px; box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1); backdrop-filter: blur(5px); }
    div[data-testid="metric-container"] label { color: #94a3b8; font-size: 0.8rem; }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #f8fafc; font-size: 1.8rem; font-weight: 800; }
    .stButton>button { width: 100%; height: 65px; border-radius: 12px; font-weight: 700; font-size: 1.1rem; border: none; transition: all 0.2s ease; text-transform: uppercase; letter-spacing: 1px; }
    .status-pill { display: flex; align-items: center; justify-content: center; padding: 12px; border-radius: 12px; font-weight: 700; font-size: 0.9rem; margin-bottom: 20px; letter-spacing: 1px; text-transform: uppercase; }
    .vip-mode { background: linear-gradient(135deg, #FFD700 0%, #B8860B 100%); color: #000; box-shadow: 0 0 20px rgba(255, 215, 0, 0.3); }
    .safe-mode { background: rgba(16, 185, 129, 0.2); border: 1px solid #10b981; color: #34d399; }
    .stTextInput>div>div>input { background-color: rgba(255,255,255,0.05); color: white; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); height: 50px; }
    .shift-card { background: rgba(255,255,255,0.03); border-left: 4px solid #3b82f6; padding: 15px; margin-bottom: 10px; border-radius: 0 12px 12px 0; }
    .admin-card { background: rgba(255, 69, 58, 0.1); border: 1px solid rgba(255, 69, 58, 0.3); padding: 20px; border-radius: 12px; margin-bottom: 15px; }
    .sched-date-header { background: rgba(255,255,255,0.1); padding: 10px 15px; border-radius: 8px; margin-top: 20px; margin-bottom: 10px; font-weight: 800; font-size: 1.2rem; border-left: 4px solid #10b981; }
    .sched-row { display: flex; justify-content: space-between; padding: 12px 15px; background: rgba(255,255,255,0.02); margin-bottom: 5px; border-radius: 6px; }
    .sched-time { color: #34d399; font-weight: 700; width: 120px; }
    .sched-name { font-weight: 600; color: #f8fafc; }
    .sched-role { color: #94a3b8; font-size: 0.85rem; }
</style>
"""
st.markdown(html_style, unsafe_allow_html=True)

# --- 2. CONSTANTS & ORG CHART ---
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}
LOCAL_TZ = pytz.timezone('US/Eastern')
GEOFENCE_RADIUS = 150 

HOSPITALS = {"Brockton General": {"lat": 42.0875, "lon": -70.9915}, "Remote/Anywhere": {"lat": "ANY", "lon": "ANY"}}

USERS = {
    # RESPIRATORY
    "1001": {"name": "Liam O'Neil", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 85.00, "phone": "+16175551234"},
    "1002": {"name": "Charles Morgan", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 85.00, "phone": None},
    "1003": {"name": "Sarah Jenkins", "role": "Charge RRT", "dept": "Respiratory", "level": "Supervisor", "rate": 90.00, "phone": None},
    "1004": {"name": "David Clark", "role": "Manager", "dept": "Respiratory", "level": "Manager", "rate": 0.00, "phone": None},
    "1005": {"name": "Dr. Alan Grant", "role": "Director", "dept": "Respiratory", "level": "Director", "rate": 0.00, "phone": None},
    # NURSING
    "2001": {"name": "Emma Watson", "role": "RN", "dept": "Nursing", "level": "Worker", "rate": 75.00, "phone": None},
    "2002": {"name": "John Doe", "role": "RN", "dept": "Nursing", "level": "Worker", "rate": 75.00, "phone": None},
    "2003": {"name": "Alice Smith", "role": "Charge RN", "dept": "Nursing", "level": "Supervisor", "rate": 80.00, "phone": None},
    "2004": {"name": "Robert Brown", "role": "Manager", "dept": "Nursing", "level": "Manager", "rate": 0.00, "phone": None},
    "2005": {"name": "Dr. Sattler", "role": "Director", "dept": "Nursing", "level": "Director", "rate": 0.00, "phone": None},
    # PCA
    "3001": {"name": "Mia Wong", "role": "PCA", "dept": "PCA", "level": "Worker", "rate": 35.00, "phone": None},
    "3002": {"name": "Carlos Ruiz", "role": "PCA", "dept": "PCA", "level": "Worker", "rate": 35.00, "phone": None},
    "3003": {"name": "James Lee", "role": "Lead PCA", "dept": "PCA", "level": "Supervisor", "rate": 40.00, "phone": None},
    "3004": {"name": "Linda Davis", "role": "Manager", "dept": "PCA", "level": "Manager", "rate": 0.00, "phone": None},
    "3005": {"name": "Dr. Malcolm", "role": "Director", "dept": "PCA", "level": "Director", "rate": 0.00, "phone": None},
    # ADMIN
    "9999": {"name": "CFO VIEW", "role": "Admin", "dept": "All", "level": "Admin", "rate": 0.00, "phone": None}
}

def get_local_now(): return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S EST")

# --- 3. DATABASE ENGINE ---
@st.cache_resource
def get_db_engine():
    url = os.environ.get("SUPABASE_URL")
    if not url:
        try: url = st.secrets["SUPABASE_URL"]
        except: pass
    if not url: return None
    if url.startswith("postgres://"): url = url.replace("postgres://", "postgresql://", 1)
    try: return create_engine(url)
    except: return None

def run_query(query, params=None):
    engine = get_db_engine()
    if not engine: return None
    try:
        with engine.connect() as conn:
            return conn.execute(text(query), params or {}).fetchall() 
    except: return None

def run_transaction(query, params=None):
    engine = get_db_engine()
    if not engine: return False
    try:
        with engine.connect() as conn:
            conn.execute(text(query), params or {})
            conn.commit() 
        return True
    except: return False

# --- 4. CORE DB LOGIC ---
def force_cloud_sync(pin):
    try:
        rows = run_query("SELECT status, start_time FROM workers WHERE pin = :pin", {"pin": pin})
        if rows and len(rows) > 0 and rows[0][0].lower() == 'active':
            st.session_state.user_state['active'] = True
            st.session_state.user_state['start_time'] = float(rows[0][1])
            return True
        st.session_state.user_state['active'] = False
        return False
    except: return False

def update_status(pin, status, start, earn):
    q = """INSERT INTO workers (pin, status, start_time, earnings, last_active) VALUES (:p, :s, :t, :e, NOW())
           ON CONFLICT (pin) DO UPDATE SET status = :s, start_time = :t, earnings = :e, last_active = NOW();"""
    return run_transaction(q, {"p": pin, "s": status, "t": start, "e": earn})

def log_tx(pin, amount):
    tx_id = f"TX-{int(time.time())}"
    run_transaction("INSERT INTO transactions (tx_id, pin, amount, timestamp, status) VALUES (:id, :p, :a, NOW(), 'INSTANT')", {"id": tx_id, "p": pin, "a": amount})
    return tx_id

def log_action(pin, action, amount, note):
    run_transaction("INSERT INTO history (pin, action, timestamp, amount, note) VALUES (:p, :a, NOW(), :amt, :n)", {"p": pin, "a": action, "amt": amount, "n": note})

# --- 5. AUTH SCREEN ---
if 'user_state' not in st.session_state: st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0, 'payout_lock': False, 'current_location': 'Remote/Anywhere'}

if 'logged_in_user' not in st.session_state:
    st.markdown("<br><br><br><h1 style='text-align: center; color: #f8fafc; letter-spacing: 2px;'>EC PROTOCOL</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #64748b; font-size: 0.9rem;'>SECURE WORKFORCE ACCESS</p><br>", unsafe_allow_html=True)
    pin = st.text_input("ACCESS CODE", type="password", placeholder="Enter your 4-digit PIN")
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("AUTHENTICATE SYSTEM"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            force_cloud_sync(pin)
            st.rerun()
        else: st.error("INVALID CREDENTIALS")
    st.stop()

user = st.session_state.logged_in_user
pin = st.session_state.pin

# --- 6. DYNAMIC NAVIGATION ---
with st.sidebar:
    st.caption(f"{user['name'].upper()} | {user['role']}")
    if get_db_engine(): st.success("🟢 DB CONNECTED")
    else: st.error("🔴 DB DISCONNECTED")
    
    if user['level'] == "Admin":
        nav = st.radio("MENU", ["COMMAND CENTER", "MASTER SCHEDULE", "AUDIT LOGS"])
    elif user['level'] in ["Manager", "Director"]:
        nav = st.radio("MENU", ["DASHBOARD", "DEPT MARKETPLACE", "DEPT SCHEDULE", "MY LOGS"])
    else:
        nav = st.radio("MENU", ["DASHBOARD", "MARKETPLACE", "MY SCHEDULE", "MY LOGS"])
        
    if st.button("LOGOUT"): st.session_state.clear(); st.rerun()

# --- 7. ROUTING ---
if nav == "COMMAND CENTER" and pin == "9999":
    st.markdown("## 🦅 Command Center")
    st.caption("Live Fleet Overview")
    rows = run_query("SELECT pin, status, start_time, earnings FROM workers WHERE status='Active'")
    if rows:
        for r in rows:
            w_pin = str(r[0])
            w_name = USERS.get(w_pin, {}).get("name", f"Unknown User ({w_pin})")
            w_role = USERS.get(w_pin, {}).get("role", "Worker")
            hrs = (time.time() - float(r[2])) / 3600
            current_earn = hrs * USERS.get(w_pin, {}).get("rate", 85)
            
            st.markdown(f"""
            <div class="admin-card">
                <h3 style="margin:0;">{w_name} <span style='color:#94a3b8; font-size:1rem;'>| {w_role}</span></h3>
                <p style="color:#ff453a; margin-top:5px; font-weight:bold;">🟢 ACTIVE (On Clock: {hrs:.2f} hrs | Accrued: ${current_earn:.2f})</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"🚨 FORCE CLOCK-OUT: {w_name}", key=f"force_{w_pin}"):
                update_status(w_pin, "Inactive", 0, 0)
                log_action("9999", "ADMIN FORCE LOGOUT", current_earn, f"Target: {w_name}")
                st.success(f"Successfully closed shift for {w_name}")
                time.sleep(1.5); st.rerun()
    else: st.info("No operators currently active.")

elif nav == "DASHBOARD":
    st.markdown(f"<h2>Good Morning, {user['name'].split(' ')[0]}</h2>", unsafe_allow_html=True)
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
        if st.button("🔴 END SHIFT"):
            if update_status(pin, "Inactive", 0, 0):
                st.session_state.user_state['active'] = False
                log_action(pin, "CLOCK OUT", gross, "Standard")
                st.rerun()
    else:
        selected_facility = st.selectbox("Select Facility", list(HOSPITALS.keys()))
        if st.button("🟢 START SHIFT"):
            start_t = time.time()
            if update_status(pin, "Active", start_t, 0):
                st.session_state.user_state['active'] = True
                st.session_state.user_state['start_time'] = start_t
                log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}")
                st.rerun()

    if not active and gross > 0.01:
        if st.button(f"💸 INSTANT TRANSFER (${net:,.2f})", disabled=st.session_state.user_state['payout_lock']):
            st.session_state.user_state['payout_lock'] = True
            tx = log_tx(pin, net)
            log_action(pin, "PAYOUT", net, "Settled")
            update_status(pin, "Inactive", 0, 0)
            st.session_state.user_state['earnings'] = 0.0
            time.sleep(1); st.session_state.user_state['payout_lock'] = False; st.rerun()

elif nav in ["MARKETPLACE", "DEPT MARKETPLACE"]:
    st.markdown(f"## 🏥 {user['dept']} Shift Exchange")
    tab1, tab2 = st.tabs(["OPEN SHIFTS", "POST NEW"])
    with tab1:
        q = f"SELECT shift_id, poster_pin, role, date, start_time, end_time, rate FROM marketplace WHERE status='OPEN' AND role LIKE '%%{user['dept']}%%'"
        res = run_query(q)
        if res:
            for s in res:
                poster_name = USERS.get(str(s[1]), {}).get("name", "Unknown Poster")
                st.markdown(f"""<div class="shift-card"><div style="font-weight:bold; font-size:1.1rem;">{s[3]} | {s[2]}</div>
                    <div style="color:#94a3b8;">{s[4]} - {s[5]} @ ${s[6]}/hr</div>
                    <div style="color:#64748b; font-size:0.8rem; margin-top:5px;">Posted by: {poster_name}</div></div>""", unsafe_allow_html=True)
                if user['level'] in ["Worker", "Supervisor"] and st.button("CLAIM", key=s[0]):
                    run_transaction("UPDATE marketplace SET status='CLAIMED', claimed_by=:p WHERE shift_id=:id", {"p": pin, "id": s[0]})
                    st.success("✅ Claimed")
                    time.sleep(1); st.rerun()
        else: st.info("No open shifts in this department.")

    with tab2:
        with st.form("new_shift"):
            shift
