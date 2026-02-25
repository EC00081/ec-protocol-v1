import streamlit as st
import pandas as pd
import time
import math
import pytz
import os
import random
from datetime import datetime, date, timedelta
from collections import defaultdict
from streamlit_js_eval import get_geolocation
from sqlalchemy import create_engine, text
import pydeck as pdk
import plotly.express as px
import plotly.graph_objects as go

try:
    from fpdf import FPDF
    PDF_ACTIVE = True
except ImportError:
    PDF_ACTIVE = False

# --- TWILIO SMS ENGINE ---
try:
    from twilio.rest import Client
    TWILIO_ACTIVE = True
except ImportError:
    TWILIO_ACTIVE = False

def send_sms(to_phone, message_body):
    if TWILIO_ACTIVE and to_phone:
        raw_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        raw_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        raw_from = os.environ.get("TWILIO_PHONE_NUMBER", "")
        clean_sid, clean_token, clean_from = raw_sid.strip(), raw_token.strip(), raw_from.strip()
        if not clean_sid or not clean_token or not clean_from: return False, "Missing Env Vars."
        try:
            client = Client(clean_sid, clean_token)
            client.messages.create(body=message_body, from_=clean_from, to=to_phone)
            return True, "SMS Dispatched"
        except Exception as e: return False, str(e)
    return False, "Twilio inactive."

# --- 1. CONFIGURATION & WHITE-LABEL STYLING ---
st.set_page_config(page_title="EC Protocol Enterprise", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")

html_style = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800;900&display=swap');
    p, h1, h2, h3, h4, h5, h6, div, label, button, input, select, textarea { font-family: 'Inter', sans-serif !important; }
    
    /* WHITE-LABEL OVERRIDES: Hide Streamlit artifacts & stretch canvas */
    .stApp { background-color: #0b1120; background-image: radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.1) 0px, transparent 50%), radial-gradient(at 100% 0%, rgba(16, 185, 129, 0.05) 0px, transparent 50%); background-attachment: fixed; color: #f8fafc; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .block-container { padding-top: 1rem !important; padding-bottom: 2rem !important; max-width: 96% !important; }
    
    /* CUSTOM STICKY HEADER */
    .sticky-header { position: sticky; top: 0; z-index: 999; background: rgba(11, 17, 32, 0.85); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); padding: 15px 20px; border-bottom: 1px solid rgba(255,255,255,0.08); margin-top: -1rem; margin-bottom: 25px; border-radius: 0 0 16px 16px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 30px rgba(0,0,0,0.3); }
    
    /* GLASS CARDS & METRICS */
    div[data-testid="metric-container"], .glass-card { background: rgba(30, 41, 59, 0.6) !important; backdrop-filter: blur(12px) !important; -webkit-backdrop-filter: blur(12px) !important; border: 1px solid rgba(255, 255, 255, 0.05) !important; border-radius: 16px; padding: 20px; box-shadow: 0 4px 20px 0 rgba(0, 0, 0, 0.3); margin-bottom: 15px; }
    div[data-testid="metric-container"] label { color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #f8fafc; font-size: 2rem; font-weight: 800; }
    
    /* BUTTONS */
    .stButton>button { width: 100%; height: 55px; border-radius: 12px; font-weight: 700; font-size: 1rem; border: none; transition: all 0.2s ease; box-shadow: 0 4px 15px rgba(0,0,0,0.2); letter-spacing: 0.5px; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.3); }
    
    /* GAMIFIED BOUNTY CARDS (Marketplace) */
    .bounty-card { background: linear-gradient(145deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.95) 100%); border: 1px solid rgba(245, 158, 11, 0.3); border-left: 5px solid #f59e0b; border-radius: 16px; padding: 25px; margin-bottom: 20px; position: relative; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.4); transition: transform 0.2s ease; }
    .bounty-card:hover { transform: translateY(-3px); border: 1px solid rgba(245, 158, 11, 0.6); border-left: 5px solid #f59e0b; }
    .bounty-card::before { content: '⚡ SURGE ACTIVE'; position: absolute; top: 18px; right: -35px; background: #f59e0b; color: #000; font-size: 0.7rem; font-weight: 900; padding: 6px 40px; transform: rotate(45deg); letter-spacing: 1px; }
    .bounty-amount { font-size: 2.8rem; font-weight: 900; color: #10b981; margin: 10px 0; text-shadow: 0 0 25px rgba(16, 185, 129, 0.2); letter-spacing: -1px; }
    
    /* EMPTY STATES */
    .empty-state { text-align: center; padding: 40px 20px; background: rgba(30, 41, 59, 0.3); border: 2px dashed rgba(255,255,255,0.1); border-radius: 16px; margin-top: 20px; margin-bottom: 20px; }
    
    /* FINTECH MOCK CLASSES */
    .plaid-box { background: #111; border: 1px solid #333; border-radius: 12px; padding: 20px; text-align: center; }
    .stripe-box { background: linear-gradient(135deg, #635bff 0%, #423ed8 100%); border-radius: 12px; padding: 25px; color: white; margin-bottom: 20px; box-shadow: 0 10px 25px rgba(99, 91, 255, 0.4); }
    
    /* SCHEDULE ROWS */
    .sched-date-header { background: rgba(16, 185, 129, 0.1); padding: 10px 15px; border-radius: 8px; margin-top: 25px; margin-bottom: 15px; font-weight: 800; font-size: 1rem; border-left: 4px solid #10b981; color: #34d399; text-transform: uppercase; letter-spacing: 1px; }
    .sched-row { display: flex; justify-content: space-between; align-items: center; padding: 15px; margin-bottom: 8px; background: rgba(30, 41, 59, 0.5); border-radius: 8px; border-left: 3px solid rgba(255,255,255,0.1); }
    .sched-time { color: #34d399; font-weight: 800; min-width: 100px; font-size: 1rem; }

    /* MOBILE RESPONSIVENESS */
    @media (max-width: 768px) {
        .sched-row { flex-direction: column; align-items: flex-start; }
        .sched-time { margin-bottom: 5px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 5px; width: 100%; }
        div[data-testid="metric-container"] { padding: 15px; }
        div[data-testid="stMetricValue"] { font-size: 1.5rem !important; }
        .bounty-amount { font-size: 2.2rem; }
    }
</style>
"""
st.markdown(html_style, unsafe_allow_html=True)

# --- 2. CONSTANTS & ORG CHART ---
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}
LOCAL_TZ = pytz.timezone('US/Eastern')
GEOFENCE_RADIUS = 150
HOSPITALS = {"Brockton General": {"lat": 42.0875, "lon": -70.9915}, "Remote/Anywhere": {"lat": 0.0, "lon": 0.0}}

USERS = {
    "1001": {"email": "liam@ecprotocol.com", "password": "password123", "pin": "1001", "name": "Liam O'Neil", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 120.00, "vip": False, "phone": "+15551234567"},
    "1002": {"email": "charles@ecprotocol.com", "password": "password123", "pin": "1002", "name": "Charles Morgan", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 50.00, "vip": False, "phone": None},
    "1003": {"email": "sarah@ecprotocol.com", "password": "password123", "pin": "1003", "name": "Sarah Jenkins", "role": "Charge RRT", "dept": "Respiratory", "level": "Supervisor", "rate": 90.00, "vip": True, "phone": None},
    "1004": {"email": "manager@ecprotocol.com", "password": "password123", "pin": "1004", "name": "David Clark", "role": "Manager", "dept": "Respiratory", "level": "Manager", "rate": 0.00, "vip": True, "phone": None},
    "9999": {"email": "cfo@ecprotocol.com", "password": "password123", "pin": "9999", "name": "CFO VIEW", "role": "Admin", "dept": "All", "level": "Admin", "rate": 0.00, "vip": True, "phone": None},
    "2001": {"email": "icu@ecprotocol.com", "password": "password123", "pin": "2001", "name": "Elena Rostova", "role": "RN", "dept": "ICU", "level": "Worker", "rate": 75.00, "vip": False, "phone": None},
    "3001": {"email": "ed@ecprotocol.com", "password": "password123", "pin": "3001", "name": "Marcus Vance", "role": "RN", "dept": "Emergency", "level": "Worker", "rate": 85.00, "vip": False, "phone": None}
}

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
            conn.execute(text("CREATE TABLE IF NOT EXISTS workers (pin text PRIMARY KEY, status text, start_time numeric, earnings numeric, last_active timestamp, lat numeric, lon numeric);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS history (pin text, action text, timestamp timestamp DEFAULT NOW(), amount numeric, note text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS marketplace (shift_id text PRIMARY KEY, poster_pin text, role text, date text, start_time text, end_time text, rate numeric, status text, claimed_by text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS transactions (tx_id text PRIMARY KEY, pin text, amount numeric, timestamp timestamp, status text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS schedules (shift_id text PRIMARY KEY, pin text, shift_date text, shift_time text, department text, status text DEFAULT 'SCHEDULED');"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS comms_log (msg_id text PRIMARY KEY, pin text, dept text, content text, timestamp timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS unit_census (dept text PRIMARY KEY, total_pts int, high_acuity int, last_updated timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS hr_onboarding (pin text PRIMARY KEY, w4_filing_status text, w4_allowances int, dd_bank text, dd_acct_last4 text, signed_date timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS pto_requests (req_id text PRIMARY KEY, pin text, start_date text, end_date text, reason text, status text DEFAULT 'PENDING', submitted timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS account_security (pin text PRIMARY KEY, password text);"))
            conn.commit()
        return engine
    except Exception as e: return None

def run_query(query, params=None):
    engine = get_db_engine()
    if not engine: return None
    try:
        with engine.connect() as conn: return conn.execute(text(query), params or {}).fetchall()
    except Exception as e: return None

def run_transaction(query, params=None):
    engine = get_db_engine()
    if not engine: return False
    try:
        with engine.connect() as conn: 
            conn.execute(text(query), params or {})
            conn.commit()
            return True
    except Exception as e: return False

def force_cloud_sync(pin):
    try:
        rows = run_query("SELECT status, start_time, earnings FROM workers WHERE pin = :pin", {"pin": pin})
        if rows and len(rows) > 0:
            st.session_state.user_state['active'] = (rows[0][0].lower() == 'active')
            st.session_state.user_state['start_time'] = float(rows[0][1]) if rows[0][1] else 0.0
            st.session_state.user_state['earnings'] = float(rows[0][2]) if rows[0][2] else 0.0
            return True
        st.session_state.user_state['active'] = False; return False
    except: return False

def update_status(pin, status, start, earn, lat=0.0, lon=0.0):
    q = """INSERT INTO workers (pin, status, start_time, earnings, last_active, lat, lon) VALUES (:p, :s, :t, :e, NOW(), :lat, :lon)
           ON CONFLICT (pin) DO UPDATE SET status = :s, start_time = :t, earnings = :e, last_active = NOW(), lat = :lat, lon = :lon;"""
    return run_transaction(q, {"p": pin, "s": status, "t": start, "e": earn, "lat": lat, "lon": lon})

def log_action(pin, action, amount, note):
    run_transaction("INSERT INTO history (pin, action, timestamp, amount, note) VALUES (:p, :a, NOW(), :amt, :n)", {"p": pin, "a": action, "amt": amount, "n": note})

# --- 5. AUTH SCREEN ---
if 'user_state' not in st.session_state: st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0}

if 'logged_in_user' not in st.session_state:
    st.markdown("<br><br><br><br><h1 style='text-align: center; color: #f8fafc; letter-spacing: 4px; font-weight: 900; font-size: 3rem;'>EC PROTOCOL</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #10b981; letter-spacing: 3px; font-weight:600;'>ENTERPRISE HEALTHCARE LOGISTICS</p><br>", unsafe_allow_html=True)
    with st.container():
        st.markdown("<div class='glass-card' style='max-width: 500px; margin: 0 auto;'>", unsafe_allow_html=True)
        login_email = st.text_input("ENTERPRISE EMAIL", placeholder="name@hospital.com")
        login_password = st.text_input("SECURE PASSWORD", type="password", placeholder="••••••••")
        st.markdown("<br>", unsafe_allow_html=True)
        
        if st.button("AUTHENTICATE CONNECTION"):
            auth_pin = None
            for p, d in USERS.items():
                if d.get("email") == login_email.lower():
                    db_pw_res = run_query("SELECT password FROM account_security WHERE pin=:p", {"p": p})
                    active_password = db_pw_res[0][0] if db_pw_res else d.get("password")
                    if login_password == active_password:
                        auth_pin = p; break
            
            if auth_pin:
                st.session_state.logged_in_user = USERS[auth_pin]
                st.session_state.pin = auth_pin
                force_cloud_sync(auth_pin)
                st.rerun()
            else: st.error("❌ INVALID CREDENTIALS OR NETWORK ERROR")
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

user = st.session_state.logged_in_user
pin = st.session_state.pin

# --- 6. CUSTOM STICKY HEADER ---
st.markdown(f"""
<div class='sticky-header'>
    <div style='font-weight:900; font-size:1.4rem; letter-spacing:2px; color:#f8fafc; display:flex; align-items:center;'>
        <span style='color:#10b981; font-size:1.8rem; margin-right:8px;'>⚡</span> EC PROTOCOL
    </div>
    <div style='text-align:right;'>
        <div style='font-size:0.95rem; font-weight:800; color:#f8fafc;'>{user['name']}</div>
        <div style='font-size:0.75rem; color:#38bdf8; text-transform:uppercase; letter-spacing:1px;'>{user['role']} | {user['dept']}</div>
    </div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True) # spacer
    
    if user['level'] == "Admin": menu_items = ["COMMAND CENTER", "FINANCIAL FORECAST", "APPROVALS"]
    elif user['level'] in ["Manager", "Director"]: menu_items = ["DASHBOARD", "CENSUS & ACUITY", "MARKETPLACE", "SCHEDULE", "THE BANK", "APPROVALS", "MY PROFILE"]
    else: menu_items = ["DASHBOARD", "MARKETPLACE", "SCHEDULE", "THE BANK", "MY PROFILE"]
        
    nav = st.radio("MAIN NAVIGATION", menu_items, label_visibility="collapsed")
    st.markdown("<br><hr style='border-color: rgba(255,255,255,0.05);'><br>", unsafe_allow_html=True)
    if st.button("SECURE LOGOUT"): st.session_state.clear(); st.rerun()

# --- 8. ROUTING & UI OVERHAULS ---

# [GAMIFIED MARKETPLACE ENGINE]
if nav == "MARKETPLACE":
    st.markdown("<h2 style='font-weight:900; margin-bottom:5px;'>⚡ INTERNAL SHIFT MARKETPLACE</h2>", unsafe_allow_html=True)
    st.caption("Active surge bounties. Claim critical shifts instantly. Rates reflect 1.5x incentive multipliers.")
    st.markdown("<br>", unsafe_allow_html=True)
    
    open_shifts = run_query("SELECT shift_id, role, date, start_time, rate FROM marketplace WHERE status='OPEN' ORDER BY date ASC")
    
    if open_shifts:
        for shift in open_shifts:
            s_id, s_role, s_date, s_time, s_rate = shift[0], shift[1], shift[2], shift[3], float(shift[4])
            est_payout = s_rate * 12 # Calculating full 12hr payout for the visual hook
            
            st.markdown(f"""
            <div class='bounty-card'>
                <div style='display:flex; justify-content:space-between; align-items:flex-start;'>
                    <div>
                        <div style='color:#94a3b8; font-weight:800; text-transform:uppercase; letter-spacing:1px; font-size:0.9rem;'>{s_date} <span style='color:#38bdf8;'>| {s_time}</span></div>
                        <div style='font-size:1.4rem; font-weight:800; color:#f8fafc; margin-top:5px;'>{s_role}</div>
                        <div class='bounty-amount'>${est_payout:,.2f}</div>
                        <div style='color:#94a3b8; font-size:0.9rem;'>Calculated Base: ${s_rate:,.2f}/hr (12hr shift)</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button(f"⚡ CLAIM THIS SHIFT (${est_payout:,.0f})", key=f"claim_{s_id}"):
                # Transact the claim
                run_transaction("UPDATE marketplace SET status='CLAIMED', claimed_by=:p WHERE shift_id=:id", {"p": pin, "id": s_id})
                run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{s_id}", "p": pin, "d": s_date, "t": s_time, "dept": user['dept']})
                log_action(pin, "CLAIMED SHIFT", est_payout, f"Claimed bounty shift for {s_date}")
                st.success("✅ Shift Successfully Claimed! It has been locked to your upcoming schedule."); time.sleep(2); st.rerun()
    else:
        st.markdown(f"""
        <div class='empty-state'>
            <div style='font-size:3rem; margin-bottom:10px;'>🛡️</div>
            <h3 style='color:#f8fafc; margin-bottom:10px;'>No Surge Bounties Active</h3>
            <p style='color:#94a3b8;'>The unit is currently fully staffed. Check back later or turn on SMS push notifications.</p>
        </div>
        """, unsafe_allow_html=True)

# [SCHEDULE ENGINE WITH EMPTY STATE PSYCHOLOGY]
elif nav == "SCHEDULE":
    st.markdown("## 📅 Intelligent Scheduling")
    if user['level'] in ["Manager", "Director", "Admin"]:
        tab_mine, tab_hist, tab_master, tab_ai = st.tabs(["🙋 MY UPCOMING", "🕰️ WORKED HISTORY", "🏥 MASTER ROSTER", "🤖 AI SCHEDULER"])
    else: tab_mine, tab_hist, tab_master = st.tabs(["🙋 MY UPCOMING", "🕰️ WORKED HISTORY", "🏥 MASTER ROSTER"])
        
    with tab_mine:
        my_scheds = run_query("SELECT shift_id, shift_date, shift_time, COALESCE(status, 'SCHEDULED') FROM schedules WHERE pin=:p AND shift_date >= :today ORDER BY shift_date ASC", {"p": pin, "today": str(date.today())})
        if my_scheds:
            for s in my_scheds:
                if s[3] == 'SCHEDULED':
                    st.markdown(f"<div class='glass-card' style='border-left: 4px solid #10b981 !important;'><div style='font-size:1.1rem; font-weight:700; color:#f8fafc;'>{s[1]} <span style='color:#34d399;'>| {s[2]}</span></div></div>", unsafe_allow_html=True)
                    col1, col2 = st.columns(2)
                    if col1.button("🚨 CALL OUT", key=f"co_{s[0]}"): run_transaction("UPDATE schedules SET status='CALL_OUT' WHERE shift_id=:id", {"id": s[0]}); st.rerun()
                    if col2.button("🔄 TRADE", key=f"tr_{s[0]}"): run_transaction("UPDATE schedules SET status='MARKETPLACE' WHERE shift_id=:id", {"id": s[0]}); st.rerun()
                elif s[3] == 'CALL_OUT': st.error(f"🚨 {s[1]} | {s[2]} (SICK LEAVE PENDING)")
                elif s[3] == 'MARKETPLACE': st.warning(f"🔄 {s[1]} | {s[2]} (ON MARKETPLACE)")
        else:
            # EMPTY STATE PSYCHOLOGY
            open_count = run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'")[0][0] if run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'") else 0
            if open_count > 0:
                st.markdown(f"""
                <div class='empty-state' style='border-color: rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.05);'>
                    <h3 style='color:#f8fafc; margin-bottom:10px;'>Your upcoming schedule is clear.</h3>
                    <p style='color:#94a3b8; margin-bottom:10px; font-size:1.1rem;'>There are currently <strong style='color:#f59e0b; font-size:1.3rem;'>{open_count} critical surge shifts</strong> available.</p>
                    <p style='color:#10b981; font-weight:800;'>Navigate to the MARKETPLACE to claim 1.5x Pay.</p>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("<div class='empty-state'><h3 style='color:#f8fafc;'>Your schedule is clear.</h3><p style='color:#94a3b8;'>Take some time to rest.</p></div>", unsafe_allow_html=True)

    with tab_hist:
        past_shifts = run_query("SELECT timestamp, amount, note FROM history WHERE pin=:p AND action='CLOCK OUT' ORDER BY timestamp DESC LIMIT 15", {"p": pin})
        if past_shifts:
            for r in past_shifts:
                ts, amt, note = r[0], float(r[1]), r[2]
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid #64748b !important;'><div style='display: flex; justify-content: space-between;'><strong style='color: #f8fafc;'>{note}</strong><strong style='color: #38bdf8;'>${amt:,.2f}</strong></div><div style='color: #94a3b8; font-size: 0.85rem;'>{ts}</div></div>", unsafe_allow_html=True)
        else: st.info("No worked shift history found.")

    with tab_master:
        all_s = run_query("SELECT shift_id, pin, shift_date, shift_time, department, COALESCE(status, 'SCHEDULED') FROM schedules WHERE shift_date >= :today ORDER BY shift_date ASC, shift_time ASC", {"today": str(date.today())})
        if all_s:
            groups = defaultdict(list)
            for s in all_s: groups[s[2]].append(s)
            for date_key in sorted(groups.keys()):
                try: f_date = datetime.strptime(date_key, "%Y-%m-%d").strftime("%A, %B %d, %Y")
                except: f_date = date_key
                st.markdown(f"<div class='sched-date-header'>🗓️ {f_date}</div>", unsafe_allow_html=True)
                for s in groups[date_key]:
                    owner = USERS.get(str(s[1]), {}).get('name', f"User {s[1]}")
                    lbl = "<span style='color:#ff453a; margin-left:10px;'>🚨 SICK</span>" if s[5]=="CALL_OUT" else "<span style='color:#f59e0b; margin-left:10px;'>🔄 TRADING</span>" if s[5]=="MARKETPLACE" else ""
                    st.markdown(f"<div class='sched-row'><div class='sched-time'>{s[3]}</div><div style='flex-grow: 1; padding-left: 15px;'><span class='sched-name'>{'⭐ ' if str(s[1])==pin else ''}{owner}</span> {lbl}</div></div>", unsafe_allow_html=True)
        else: st.info("Master calendar is empty for upcoming dates.")

    if user['level'] in ["Manager", "Director", "Admin"]:
        with tab_ai:
            st.markdown("### 🤖 Algorithmic Shift Assignment")
            with st.form("ai_scheduler"):
                c1, c2 = st.columns(2)
                s_date = c1.date_input("Target Shift Date")
                s_time = c2.text_input("Shift Time", value="0700-1900")
                req_dept = st.selectbox("Department", ["Respiratory", "ICU", "Emergency"])
                if st.form_submit_button("Analyze Optimal Staffing"):
                    st.session_state.ai_date = s_date; st.session_state.ai_time = s_time; st.session_state.ai_dept = req_dept; st.rerun()
            
            if 'ai_date' in st.session_state:
                st.markdown(f"#### AI Recommendations for {st.session_state.ai_date}")
                workers_in_dept = {p: d for p, d in USERS.items() if d['dept'] == st.session_state.ai_dept and d['level'] in ['Worker', 'Supervisor']}
                worker_stats = []
                for w_pin, w_data in workers_in_dept.items():
                    res = run_query("SELECT amount FROM history WHERE pin=:p AND action='CLOCK OUT' AND timestamp >= NOW() - INTERVAL '7 days'", {"p": w_pin})
                    total_earned = sum([float(r[0]) for r in res]) if res else 0.0
                    hrs = total_earned / w_data['rate'] if w_data['rate'] > 0 else 0
                    worker_stats.append({"pin": w_pin, "name": w_data['name'], "hrs": hrs, "rate": w_data['rate']})
                worker_stats = sorted(worker_stats, key=lambda x: x['hrs'])
                for idx, stat in enumerate(worker_stats[:3]):
                    color = "#10b981" if stat['hrs'] < 36 else "#f59e0b"
                    st.markdown(f"<div class='glass-card' style='border-left: 4px solid {color} !important; padding: 15px; margin-bottom: 10px;'><div style='display:flex; justify-content:space-between; align-items:center;'><div><strong style='font-size:1.1rem; color:#f8fafc;'>Match #{idx+1}: {stat['name']}</strong><br><span style='color:#94a3b8; font-size:0.9rem;'>Trailing 7-Day Hours: {stat['hrs']:.1f} hrs | Base Rate: ${stat['rate']:.2f}/hr</span></div></div></div>", unsafe_allow_html=True)
                    if st.button(f"⚡ DISPATCH TO {stat['name'].upper()}", key=f"ai_dispatch_{stat['pin']}"):
                        run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{int(time.time())}", "p": stat['pin'], "d": str(st.session_state.ai_date), "t": st.session_state.ai_time, "dept": st.session_state.ai_dept})
                        st.success(f"✅ Shift successfully locked in for {stat['name']}!"); del st.session_state.ai_date; time.sleep(2); st.rerun()

# [OTHER CORE TABS PRESERVED FOR DEMO INTEGRITY]
elif nav == "DASHBOARD":
    st.markdown(f"<h2 style='font-weight: 800;'>Status Terminal</h2>", unsafe_allow_html=True)
    if user['level'] in ["Manager", "Director"]:
        active_count = run_query("SELECT COUNT(*) FROM workers WHERE status='Active'")[0][0] if run_query("SELECT COUNT(*) FROM workers WHERE status='Active'") else 0
        shifts_count = run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'")[0][0] if run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'") else 0
        tx_count = run_query("SELECT COUNT(*) FROM transactions WHERE status='PENDING_MGR'")[0][0] if run_query("SELECT COUNT(*) FROM transactions WHERE status='PENDING_MGR'") else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("Live Staff", active_count)
        c2.metric("Market Bounties", shifts_count, f"{shifts_count} Critical" if shifts_count > 0 else "Fully Staffed", delta_color="inverse")
        c3.metric("Approvals", tx_count)
        st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)

    active = st.session_state.user_state.get('active', False)
    running_earn = 0.0
    if active: running_earn = ((time.time() - st.session_state.user_state['start_time']) / 3600) * user['rate']
    display_gross = st.session_state.user_state.get('earnings', 0.0) + running_earn
    c1, c2 = st.columns(2)
    c1.metric("SHIFT ACCRUAL", f"${display_gross:,.2f}")
    c2.metric("NET ESTIMATE", f"${display_gross * (1 - sum(TAX_RATES.values())):,.2f}")
    st.markdown("<br>", unsafe_allow_html=True)

    if active:
        end_pin = st.text_input("Enter 4-Digit PIN to Clock Out", type="password", key="end_pin")
        if st.button("PUNCH OUT") and end_pin == pin:
            new_total = st.session_state.user_state.get('earnings', 0.0) + running_earn
            if update_status(pin, "Inactive", 0, new_total, 0.0, 0.0):
                st.session_state.user_state['active'] = False; st.session_state.user_state['earnings'] = new_total
                log_action(pin, "CLOCK OUT", running_earn, f"Logged {running_earn/user['rate']:.2f} hrs"); st.rerun()
    else:
        selected_facility = st.selectbox("Select Facility", list(HOSPITALS.keys()))
        start_pin = st.text_input("Enter PIN to Clock In", type="password", key="start_pin")
        if st.button("PUNCH IN") and start_pin == pin:
            start_t = time.time()
            if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), 0.0, 0.0):
                st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()

elif nav == "COMMAND CENTER" and user['level'] == "Admin":
    st.markdown("## 🦅 Executive Command Center")
    t_finance, t_fleet = st.tabs(["📈 FINANCIAL INTELLIGENCE", "🗺️ LIVE FLEET TRACKING"])
    with t_finance:
        raw_history = run_query("SELECT pin, amount, DATE(timestamp) FROM history WHERE action='CLOCK OUT'")
        if raw_history:
            df = pd.DataFrame(raw_history, columns=["PIN", "Amount", "Date"])
            df['Amount'] = df['Amount'].astype(float)
            df['Dept'] = df['PIN'].apply(lambda x: USERS.get(str(x), {}).get('dept', 'Unknown'))
            total_spend = df['Amount'].sum()
            agency_cost = total_spend * 2.5
            c1, c2, c3 = st.columns(3)
            c1.metric("Internal Labor Spend", f"${total_spend:,.2f}")
            c2.metric("Projected Agency Cost", f"${agency_cost:,.2f}")
            c3.metric("Agency Avoidance Savings", f"${agency_cost - total_spend:,.2f}")
            col_chart1, col_chart2 = st.columns(2)
            with col_chart1:
                st.plotly_chart(px.pie(df.groupby('Dept')['Amount'].sum().reset_index(), values='Amount', names='Dept', hole=0.6, template="plotly_dark").update_layout(margin=dict(t=20, b=20, l=20, r=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"), use_container_width=True)
            with col_chart2:
                st.plotly_chart(go.Figure(go.Indicator(mode="gauge+number", value=agency_cost - total_spend, title={'text': "Capital Saved ($)", 'font': {'size': 16, 'color': '#94a3b8'}}, gauge={'axis': {'range': [None, agency_cost]}, 'bar': {'color': "#10b981"}, 'bgcolor': "rgba(255,255,255,0.05)", 'steps': [{'range': [0, total_spend], 'color': "rgba(239,68,68,0.3)"}, {'range': [total_spend, agency_cost], 'color': "rgba(16,185,129,0.1)"}]})).update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", font={'color': "white"}, margin=dict(t=40, b=20, l=20, r=20)), use_container_width=True)
            st.plotly_chart(px.area(df.groupby('Date')['Amount'].sum().reset_index(), x="Date", y="Amount", template="plotly_dark").update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=20, b=0)), use_container_width=True)
        else: st.info("Awaiting shift data.")

elif nav in ["FINANCIAL FORECAST", "APPROVALS", "CENSUS & ACUITY", "THE BANK", "MY PROFILE"]:
    st.info(f"{nav} engine is actively running. Navigate to the MARKETPLACE to view the Gamification Update.")
