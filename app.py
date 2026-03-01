import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import time
import math
import pytz
import os
import bcrypt
import hashlib
from datetime import datetime, date, timedelta
from collections import defaultdict
from streamlit_js_eval import get_geolocation
from sqlalchemy import create_engine, text
import pydeck as pdk
import plotly.express as px
import plotly.graph_objects as go

# --- GLOBAL CONSTANTS ---
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
}

# --- EXTERNAL LIBRARIES ---
try: from fpdf import FPDF; PDF_ACTIVE = True
except ImportError: PDF_ACTIVE = False
try: from twilio.rest import Client; TWILIO_ACTIVE = True
except ImportError: TWILIO_ACTIVE = False

def send_sms(to_phone, message_body):
    if TWILIO_ACTIVE and to_phone:
        raw_sid, raw_token, raw_from = os.environ.get("TWILIO_ACCOUNT_SID", ""), os.environ.get("TWILIO_AUTH_TOKEN", ""), os.environ.get("TWILIO_PHONE_NUMBER", "")
        if not raw_sid or not raw_token or not raw_from: return False, "Missing Env Vars."
        try:
            client = Client(raw_sid.strip(), raw_token.strip())
            client.messages.create(body=message_body, from_=raw_from.strip(), to=to_phone)
            return True, "SMS Dispatched"
        except Exception as e: return False, str(e)
    return False, "Twilio inactive."

# --- CRYPTO & ZK PROOFS ---
def hash_password(plain_text_password): return bcrypt.hashpw(plain_text_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
def verify_password(plain_text_password, hashed_password):
    try: return bcrypt.checkpw(plain_text_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except ValueError: return False
def generate_zk_commitment(doc_number, pin):
    salt = os.environ.get("ZK_SECRET_SALT", "EC_PROTOCOL_ENTERPRISE_SALT")
    return hashlib.sha256(f"{doc_number}-{pin}-{salt}".encode('utf-8')).hexdigest()

# --- DATABASE ENGINE ---
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
            conn.execute(text("CREATE TABLE IF NOT EXISTS marketplace (shift_id text PRIMARY KEY, poster_pin text, role text, date text, start_time text, end_time text, rate numeric, status text, claimed_by text, escrow_status text);"))
            try: conn.execute(text("ALTER TABLE marketplace ADD COLUMN escrow_status text;"))
            except: pass
            conn.execute(text("CREATE TABLE IF NOT EXISTS transactions (tx_id text PRIMARY KEY, pin text, amount numeric, timestamp timestamp DEFAULT NOW(), status text, destination_pubkey text, tx_type text);"))
            try: conn.execute(text("ALTER TABLE transactions ADD COLUMN destination_pubkey text;"))
            except: pass
            try: conn.execute(text("ALTER TABLE transactions ADD COLUMN tx_type text;"))
            except: pass
            conn.execute(text("CREATE TABLE IF NOT EXISTS schedules (shift_id text PRIMARY KEY, pin text, shift_date text, shift_time text, department text, status text DEFAULT 'SCHEDULED');"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS unit_census (dept text PRIMARY KEY, total_pts int, high_acuity int, last_updated timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS hr_onboarding (pin text PRIMARY KEY, w4_filing_status text, w4_allowances int, dd_bank text, dd_acct_last4 text, solana_pubkey text, signed_date timestamp DEFAULT NOW());"))
            try: conn.execute(text("ALTER TABLE hr_onboarding ADD COLUMN solana_pubkey text;"))
            except: pass
            conn.execute(text("CREATE TABLE IF NOT EXISTS pto_requests (req_id text PRIMARY KEY, pin text, start_date text, end_date text, reason text, status text DEFAULT 'PENDING', submitted timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS account_security (pin text PRIMARY KEY, password text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS credentials (doc_id text PRIMARY KEY, pin text, doc_type text, doc_number text, exp_date text, status text);"))
            # NEW: BLE Indoor Tracking Table
            conn.execute(text("CREATE TABLE IF NOT EXISTS indoor_tracking (pin text PRIMARY KEY, current_floor text, current_room text, last_seen timestamp DEFAULT NOW());"))
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

def log_action(pin, action, amount, note): run_transaction("INSERT INTO history (pin, action, timestamp, amount, note) VALUES (:p, :a, NOW(), :amt, :n)", {"p": pin, "a": action, "amt": amount, "n": note})
def update_status(pin, status, start, earn, lat=0.0, lon=0.0): q = "INSERT INTO workers (pin, status, start_time, earnings, last_active, lat, lon) VALUES (:p, :s, :t, :e, NOW(), :lat, :lon) ON CONFLICT (pin) DO UPDATE SET status = :s, start_time = :t, earnings = :e, last_active = NOW(), lat = :lat, lon = :lon;"; return run_transaction(q, {"p": pin, "s": status, "t": start, "e": earn, "lat": lat, "lon": lon})
def haversine_distance(lat1, lon1, lat2, lon2): R = 6371000; phi1, phi2 = math.radians(lat1), math.radians(lat2); dphi = math.radians(lat2 - lat1); dlam = math.radians(lon2 - lon1); a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2; return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
def force_cloud_sync(pin):
    rows = run_query("SELECT status, start_time, earnings FROM workers WHERE pin = :pin", {"pin": pin})
    if rows and len(rows) > 0: st.session_state.user_state['active'] = (rows[0][0].lower() == 'active'); st.session_state.user_state['start_time'] = float(rows[0][1]) if rows[0][1] else 0.0; st.session_state.user_state['earnings'] = float(rows[0][2]) if rows[0][2] else 0.0; return True
    st.session_state.user_state['active'] = False; return False
# --- WEB3 & CYBER-PHYSICAL PROTOCOLS ---
def lock_escrow_bounty(shift_id, rate, hours=12):
    run_transaction("UPDATE marketplace SET escrow_status='LOCKED' WHERE shift_id=:id", {"id": shift_id})
    return True

def release_escrow_bounty(shift_id, pin, user_pubkey):
    run_transaction("UPDATE marketplace SET escrow_status='RELEASED' WHERE shift_id=:id", {"id": shift_id})
    return True

def execute_split_stream_payout(pin, gross_amount, user_pubkey):
    TREASURY_PUBKEY = os.environ.get("IRS_TREASURY_WALLET", "Hospital_Tax_Holding_Wallet_Address")
    tax_withheld = gross_amount * sum(TAX_RATES.values())
    net_payout = gross_amount - tax_withheld
    tx_base_id = int(time.time())
    run_transaction("INSERT INTO transactions (tx_id, pin, amount, status, destination_pubkey, tx_type) VALUES (:id, :p, :amt, 'APPROVED', :dest, 'NET_PAY')", {"id": f"TX-NET-{tx_base_id}", "p": pin, "amt": net_payout, "dest": user_pubkey})
    run_transaction("INSERT INTO transactions (tx_id, pin, amount, status, destination_pubkey, tx_type) VALUES (:id, :p, :amt, 'APPROVED', :dest, 'TAX_WITHHOLDING')", {"id": f"TX-TAX-{tx_base_id}", "p": pin, "amt": tax_withheld, "dest": TREASURY_PUBKEY})
    return net_payout, tax_withheld

def process_background_location_ping(pin, current_lat, current_lon, shift_id=None, is_sos_bounty=False):
    workers_data = run_query("SELECT status, start_time, earnings, lat, lon FROM workers WHERE pin=:p", {"p": pin})
    if not workers_data or workers_data[0][0] != 'Active': return False, "User not actively on shift."
    start_time, current_earnings = float(workers_data[0][1]), float(workers_data[0][2])
    fac_lat, fac_lon = HOSPITALS["Brockton General"]["lat"], HOSPITALS["Brockton General"]["lon"]
    distance_meters = haversine_distance(current_lat, current_lon, fac_lat, fac_lon)
    
    if distance_meters > GEOFENCE_RADIUS:
        hours_worked = (time.time() - start_time) / 3600
        shift_gross = hours_worked * USERS[pin]['rate']
        final_gross = current_earnings + shift_gross
        update_status(pin, "Inactive", 0, 0.0, current_lat, current_lon)
        log_action(pin, "AUTO CLOCK OUT", shift_gross, f"Geofence exited ({distance_meters:.0f}m)")
        hr_data = run_query("SELECT solana_pubkey FROM hr_onboarding WHERE pin=:p", {"p": pin})
        user_pubkey = hr_data[0][0] if hr_data and hr_data[0][0] else None
        if not user_pubkey: return True, "Auto-Clocked out, but funds held. No Web3 wallet linked."
        
        if is_sos_bounty and shift_id:
            release_escrow_bounty(shift_id, pin, user_pubkey)
            status_msg = f"Escrow Smart Contract unlocked. ${final_gross:,.2f} released."
        else:
            net, tax = execute_split_stream_payout(pin, final_gross, user_pubkey)
            status_msg = f"Standard Shift Auto-Cashed Out. ${net:,.2f} routed to wallet."
        if USERS[pin].get('phone'): send_sms(USERS[pin]['phone'], f"EC PROTOCOL: Shift ended. {status_msg}")
        return True, status_msg
    return False, "User still within geofence."

def process_ble_beacon_ping(pin, major_floor, minor_room, rssi_signal):
    """
    Called by the native mobile app when a BLE beacon is detected nearby.
    """
    if rssi_signal > -70: 
        run_transaction("INSERT INTO indoor_tracking (pin, current_floor, current_room, last_seen) VALUES (:p, :f, :r, NOW()) ON CONFLICT (pin) DO UPDATE SET current_floor=:f, current_room=:r, last_seen=NOW()", {"p": pin, "f": major_floor, "r": minor_room})
        return True
    return False

def check_isolation_hazard_pay(pin, isolation_room):
    """
    Compliant BLE Use Case: Automatically logs Hazard/Isolation pay multipliers
    based on verified physical time spent inside designated high-acuity/isolation rooms.
    """
    tracker = run_query("SELECT current_room FROM indoor_tracking WHERE pin=:p AND last_seen > NOW() - INTERVAL '15 minutes'", {"p": pin})
    if tracker and tracker[0][0] == isolation_room:
        # Worker was physically verified in the isolation room. Log the hazard premium.
        log_action(pin, "HAZARD PAY LOGGED", 15.00, f"Verified Isolation Care in {isolation_room}")
        return True
    return False

def phantom_wallet_connector():
    components.html("""
        <div style="text-align: center; font-family: 'Inter', sans-serif;">
            <button id="connect-btn" style="background-color: #AB9FF2; color: #000; padding: 12px 24px; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; font-size: 16px; width: 100%; box-shadow: 0 4px 15px rgba(0,0,0,0.2); transition: all 0.2s ease;">
                Connect Phantom Wallet
            </button>
            <p id="wallet-status" style="color: #94a3b8; font-size: 14px; margin-top: 10px;"></p>
        </div>
        <script>
            const connectBtn = document.getElementById('connect-btn');
            const statusText = document.getElementById('wallet-status');
            connectBtn.addEventListener('click', async () => {
                if ('solana' in window) {
                    const provider = window.solana;
                    if (provider.isPhantom) {
                        try {
                            const resp = await provider.connect();
                            statusText.innerHTML = "Wallet Linked! Copy your key below: <br><strong style='color:#10b981;'>" + resp.publicKey.toString() + "</strong>";
                            connectBtn.style.backgroundColor = "#10b981"; connectBtn.innerText = "Wallet Connected";
                        } catch (err) { statusText.innerHTML = "Connection cancelled."; }
                    }
                } else { window.open('https://phantom.app/', '_blank'); statusText.innerHTML = "Please install Phantom Wallet extension."; }
            });
        </script>
        """, height=140)

# --- CSS & AUTHENTICATION ---
html_style = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800;900&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
    [data-testid="stSidebar"] { display: none !important; } [data-testid="collapsedControl"] { display: none !important; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} [data-testid="stToolbar"] {visibility: hidden !important;} header {background: transparent !important;}
    .stApp { background-color: #0b1120; background-image: radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.1) 0px, transparent 50%), radial-gradient(at 100% 0%, rgba(16, 185, 129, 0.05) 0px, transparent 50%); background-attachment: fixed; color: #f8fafc; }
    .block-container { padding-top: 1rem !important; padding-bottom: 2rem !important; max-width: 96% !important; }
    .custom-header-pill { background: rgba(11, 17, 32, 0.85); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); padding: 15px 25px; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 30px rgba(0,0,0,0.3); }
    div[data-testid="metric-container"], .glass-card { background: rgba(30, 41, 59, 0.6) !important; backdrop-filter: blur(12px) !important; border: 1px solid rgba(255, 255, 255, 0.05) !important; border-radius: 16px; padding: 20px; margin-bottom: 15px; box-shadow: 0 4px 20px 0 rgba(0, 0, 0, 0.3); }
    div[data-testid="metric-container"] label { color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #f8fafc; font-size: 2rem; font-weight: 800; }
    .stButton>button { width: 100%; height: 55px; border-radius: 12px; font-weight: 700; font-size: 1rem; border: none; transition: all 0.2s ease; box-shadow: 0 4px 15px rgba(0,0,0,0.2); letter-spacing: 0.5px; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.3); }
    div[role="radiogroup"] { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; }
    .bounty-card { background: linear-gradient(145deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.95) 100%); border: 1px solid rgba(245, 158, 11, 0.3); border-left: 5px solid #f59e0b; border-radius: 16px; padding: 25px; margin-bottom: 20px; position: relative; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.4); transition: transform 0.2s ease; }
    .bounty-card:hover { transform: translateY(-3px); border: 1px solid rgba(245, 158, 11, 0.6); }
    .bounty-card::before { content: '⚡ SURGE ACTIVE'; position: absolute; top: 18px; right: -35px; background: #f59e0b; color: #000; font-size: 0.7rem; font-weight: 900; padding: 6px 40px; transform: rotate(45deg); letter-spacing: 1px; }
    .bounty-amount { font-size: 2.8rem; font-weight: 900; color: #10b981; margin: 10px 0; text-shadow: 0 0 25px rgba(16, 185, 129, 0.2); letter-spacing: -1px; }
    .empty-state { text-align: center; padding: 40px 20px; background: rgba(30, 41, 59, 0.3); border: 2px dashed rgba(255,255,255,0.1); border-radius: 16px; margin-top: 20px; margin-bottom: 20px; }
    .plaid-box { background: #111; border: 1px solid #333; border-radius: 12px; padding: 20px; text-align: center; }
    .stripe-box { background: linear-gradient(135deg, #635bff 0%, #423ed8 100%); border-radius: 12px; padding: 25px; color: white; margin-bottom: 20px; box-shadow: 0 10px 25px rgba(99, 91, 255, 0.4); }
    .sched-date-header { background: rgba(16, 185, 129, 0.1); padding: 10px 15px; border-radius: 8px; margin-top: 25px; margin-bottom: 15px; font-weight: 800; font-size: 1rem; border-left: 4px solid #10b981; color: #34d399; text-transform: uppercase; }
    .sched-row { display: flex; justify-content: space-between; align-items: center; padding: 15px; margin-bottom: 8px; background: rgba(30, 41, 59, 0.5); border-radius: 8px; border-left: 3px solid rgba(255,255,255,0.1); }
    .sched-time { color: #34d399; font-weight: 800; min-width: 100px; font-size: 1rem; }
    @media (max-width: 768px) { .sched-row { flex-direction: column; align-items: flex-start; } .sched-time { margin-bottom: 5px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 5px; width: 100%; } div[data-testid="stMetricValue"] { font-size: 1.5rem !important; } .bounty-amount { font-size: 2.2rem; } }
</style>
"""
st.markdown(html_style, unsafe_allow_html=True)

if 'user_state' not in st.session_state: st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0}

if 'logged_in_user' not in st.session_state:
    st.markdown("<br><br><br><br><h1 style='text-align: center; color: #f8fafc; letter-spacing: 4px; font-weight: 900; font-size: 3rem;'>EC PROTOCOL</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #10b981; letter-spacing: 3px; font-weight:600;'>ENTERPRISE HEALTHCARE LOGISTICS v1.3.8</p><br>", unsafe_allow_html=True)
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
                    if db_pw_res:
                        if verify_password(login_password, db_pw_res[0][0]): auth_pin = p; break
                    else:
                        if login_password == d.get("password"):
                            auth_pin = p; run_transaction("INSERT INTO account_security (pin, password) VALUES (:p, :pw)", {"p": p, "pw": hash_password(login_password)}); break
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
# --- TOP NAVIGATION ---
c1, c2 = st.columns([8, 2])
with c1:
    st.markdown(f"<div class='custom-header-pill'><div style='font-weight:900; font-size:1.4rem; letter-spacing:2px; color:#f8fafc; display:flex; align-items:center;'><span style='color:#10b981; font-size:1.8rem; margin-right:8px;'>⚡</span> EC PROTOCOL</div><div style='text-align:right;'><div style='font-size:0.95rem; font-weight:800; color:#f8fafc;'>{user['name']}</div><div style='font-size:0.75rem; color:#38bdf8; text-transform:uppercase; letter-spacing:1px;'>{user['role']} | {user['dept']}</div></div></div>", unsafe_allow_html=True)
with c2:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚪 LOGOUT"): st.session_state.clear(); st.rerun()

if user['level'] == "Admin": menu_items = ["COMMAND CENTER", "FINANCIAL FORECAST", "APPROVALS"]
elif user['level'] in ["Manager", "Director"]: menu_items = ["DASHBOARD", "CENSUS & ACUITY", "MARKETPLACE", "SCHEDULE", "THE BANK", "APPROVALS", "MY PROFILE"]
else: menu_items = ["DASHBOARD", "MARKETPLACE", "SCHEDULE", "THE BANK", "MY PROFILE"]

st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)
nav = st.radio("NAVIGATION", menu_items, horizontal=True, label_visibility="collapsed")
st.markdown("<hr style='border-color: rgba(255,255,255,0.05); margin-top: 5px; margin-bottom: 20px;'>", unsafe_allow_html=True)

# --- MASTER ROUTING ---
if nav == "DASHBOARD":
    st.markdown(f"<h2 style='font-weight: 800;'>Status Terminal</h2>", unsafe_allow_html=True)
    if st.button("🔄 Refresh Dashboard"): st.rerun()
    
    if user['level'] in ["Manager", "Director"]:
        active_count = run_query("SELECT COUNT(*) FROM workers WHERE status='Active'")[0][0] if run_query("SELECT COUNT(*) FROM workers WHERE status='Active'") else 0
        shifts_count = run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'")[0][0] if run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'") else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("Live Staff", active_count)
        c2.metric("Market Bounties", shifts_count, f"{shifts_count} Critical" if shifts_count > 0 else "Fully Staffed", delta_color="inverse")
        c3.metric("Approvals", "Active")
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
                log_action(pin, "CLOCK OUT", running_earn, f"Logged {running_earn/user['rate']:.2f} hrs")
                active_shifts = run_query("SELECT shift_id FROM schedules WHERE pin=:p AND shift_date=:d", {"p": pin, "d": str(date.today())})
                if active_shifts: release_escrow_bounty(active_shifts[0][0], pin, "SYSTEM_AUTO_RELEASE")
                st.rerun()
                
     # BACKGROUND SIMULATION TOOLS
        with st.expander("⚙️ App Simulation Engine (Test Background Pings)"):
            st.caption("Simulate native mobile app triggers.")
            if st.button("🚙 Simulate Leaving Geofence (Auto-Payout)"):
                success, msg = process_background_location_ping(pin, 42.1000, -71.0000)
                if success:
                    st.session_state.user_state['active'] = False
                    st.success(msg); time.sleep(3); st.rerun()
            
            c_ble1, c_ble2 = st.columns(2)
            if c_ble1.button("📡 Simulate BLE Ping (Enter Isolation Room 402)"):
                process_ble_beacon_ping(pin, "Floor 4", "ISO-402", -50)
                st.success("Indoor location physically verified in ISO-402")
            if c_ble2.button("🛡️ Audit Isolation Care (Claim Hazard Pay)"):
                if check_isolation_hazard_pay(pin, "ISO-402"):
                    st.success("✅ BLE Verified! You were physically present in the isolation room. $15.00 Hazard Pay Logged.")
                else: 
                    st.error("❌ BLE Audit Failed. No tracking data found for ISO-402. You must enter the room first.")
                
    else:
        selected_facility = st.selectbox("Select Facility", list(HOSPITALS.keys()))
        if not user.get('vip', False):
            st.info("Identity verification required to initiate shift.")
            camera_photo = st.camera_input("Take a photo to verify identity")
            loc = get_geolocation()
            if camera_photo and loc:
                user_lat, user_lon = loc['coords']['latitude'], loc['coords']['longitude']
                fac_lat, fac_lon = HOSPITALS[selected_facility]["lat"], HOSPITALS[selected_facility]["lon"]
                if selected_facility != "Remote/Anywhere":
                    df_map = pd.DataFrame({'lat': [user_lat, fac_lat], 'lon': [user_lon, fac_lon], 'color': [[59, 130, 246, 200], [16, 185, 129, 200]], 'radius': [20, GEOFENCE_RADIUS]})
                    st.pydeck_chart(pdk.Deck(layers=[pdk.Layer("ScatterplotLayer", df_map, get_position='[lon, lat]', get_color='color', get_radius='radius')], initial_view_state=pdk.ViewState(latitude=user_lat, longitude=user_lon, zoom=15, pitch=45), map_style='mapbox://styles/mapbox/dark-v10'))
                    if haversine_distance(user_lat, user_lon, fac_lat, fac_lon) <= GEOFENCE_RADIUS:
                        st.success(f"✅ Geofence Confirmed.")
                        start_pin = st.text_input("Enter PIN to Clock In", type="password", key="start_pin")
                        if st.button("PUNCH IN") and start_pin == pin:
                            start_t = time.time()
                            if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), user_lat, user_lon):
                                st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()
                    else: st.error("❌ Geofence Failed. You are too far from the facility.")
                else:
                    st.success("✅ Remote Check-in Authorized.")
                    start_pin = st.text_input("Enter PIN to Clock In", type="password", key="start_pin_rem")
                    if st.button("PUNCH IN (REMOTE)") and start_pin == pin:
                        start_t = time.time(); update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), user_lat, user_lon); st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: Remote"); st.rerun()
        else:
            st.caption("✨ VIP Security Override Active")
            start_pin = st.text_input("Enter PIN to Clock In", type="password", key="vip_start_pin")
            if st.button("PUNCH IN") and start_pin == pin:
                start_t = time.time(); update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), 0.0, 0.0); st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()

elif nav == "COMMAND CENTER" and user['level'] == "Admin":
    st.info("Executive Command Active.")

elif nav == "CENSUS & ACUITY":
    st.markdown(f"## 📊 {user['dept']} Census & Staffing")
    if st.button("🔄 Refresh Census Board"): st.rerun()
    c_data = run_query("SELECT total_pts, high_acuity, last_updated FROM unit_census WHERE dept=:d", {"d": user['dept']})
    curr_pts, curr_high = (c_data[0][0], c_data[0][1]) if c_data else (0, 0)
    req_staff = math.ceil(curr_high / 3) + math.ceil(max(0, curr_pts - curr_high) / 6)
    actual_staff = sum(1 for r in run_query("SELECT pin FROM workers WHERE status='Active'") if USERS.get(str(r[0]), {}).get('dept') == user['dept']) if run_query("SELECT pin FROM workers WHERE status='Active'") else 0
    variance = actual_staff - req_staff
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Patients", curr_pts)
    col2.metric("Required Staff (Calculated)", req_staff)
    if variance < 0:
        col3.metric("Current Staff", actual_staff, f"{variance} (Understaffed)", delta_color="inverse")
        st.error(f"🚨 UNSAFE STAFFING: Requires {abs(variance)} more personnel.")
        if st.button(f"🚨 BROADCAST SOS FOR {abs(variance)} STAFF"):
            rate = user['rate'] * 1.5 if user['rate'] > 0 else 125.00
            for i in range(abs(variance)):
                new_shift_id = f"SOS-{int(time.time()*1000)}-{i}"
                run_transaction("INSERT INTO marketplace (shift_id, poster_pin, role, date, start_time, end_time, rate, status, escrow_status) VALUES (:id, :p, :r, :d, :s, :e, :rt, 'OPEN', 'PENDING')", {"id": new_shift_id, "p": pin, "r": f"🚨 SOS: {user['dept']}", "d": str(date.today()), "s": "NOW", "e": "END OF SHIFT", "rt": rate})
                lock_escrow_bounty(new_shift_id, rate) 
            st.success("🚨 SOS Broadcasted! Smart Contract Escrow Locked!"); time.sleep(2.5); st.rerun()
    else: col3.metric("Current Staff", actual_staff, f"+{variance} (Safe)", delta_color="normal")

    with st.expander("📝 UPDATE CENSUS NUMBERS"):
        with st.form("update_census"):
            new_t = st.number_input("Total Unit Census", min_value=0, value=curr_pts, step=1)
            new_h = st.number_input("High Acuity (Vents/ICU Stepdown)", min_value=0, value=curr_high, step=1)
            if st.form_submit_button("Lock In Census"):
                run_transaction("INSERT INTO unit_census (dept, total_pts, high_acuity) VALUES (:d, :t, :h) ON CONFLICT (dept) DO UPDATE SET total_pts=:t, high_acuity=:h, last_updated=NOW()", {"d": user['dept'], "t": new_t, "h": new_h})
                st.success("Census Updated!"); time.sleep(1); st.rerun()
elif nav == "MARKETPLACE":
    st.markdown("<h2 style='font-weight:900; margin-bottom:5px;'>⚡ INTERNAL SHIFT MARKETPLACE</h2>", unsafe_allow_html=True)
    if st.button("🔄 Refresh Market"): st.rerun()
    st.caption("Active surge bounties. Claim critical shifts instantly.")
    
    open_shifts = run_query("SELECT shift_id, role, date, start_time, rate, escrow_status FROM marketplace WHERE status='OPEN' ORDER BY date ASC")
    if open_shifts:
        for shift in open_shifts:
            s_id, s_role, s_date, s_time, s_rate, s_escrow = shift[0], shift[1], shift[2], shift[3], float(shift[4]), shift[5]
            est_payout = s_rate * 12
            escrow_badge = "<span style='background:#10b981; color:#0b1120; padding:3px 8px; border-radius:4px; font-size:0.75rem; font-weight:bold; margin-left:10px;'>🔒 ESCROW SECURED</span>" if s_escrow == "LOCKED" else ""
            st.markdown(f"<div class='bounty-card'><div style='display:flex; justify-content:space-between; align-items:flex-start;'><div><div style='color:#94a3b8; font-weight:800; text-transform:uppercase; font-size:0.9rem;'>{s_date} <span style='color:#38bdf8;'>| {s_time}</span></div><div style='font-size:1.4rem; font-weight:800; color:#f8fafc; margin-top:5px;'>{s_role}{escrow_badge}</div><div class='bounty-amount'>${est_payout:,.2f}</div></div></div></div>", unsafe_allow_html=True)
            if st.button(f"⚡ CLAIM THIS SHIFT (${est_payout:,.0f})", key=f"claim_{s_id}"):
                run_transaction("UPDATE marketplace SET status='CLAIMED', claimed_by=:p WHERE shift_id=:id", {"p": pin, "id": s_id})
                run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{s_id}", "p": pin, "d": s_date, "t": s_time, "dept": user['dept']})
                st.success("✅ Shift Claimed!"); time.sleep(2); st.rerun()
    else: st.markdown("<div class='empty-state'><h3>No Surge Bounties Active</h3></div>", unsafe_allow_html=True)

elif nav == "SCHEDULE":
    st.markdown("## 📅 Intelligent Scheduling")
    if st.button("🔄 Refresh Schedule"): st.rerun()
    tab_mine, tab_hist = st.tabs(["🙋 MY UPCOMING", "🕰️ WORKED HISTORY"])
    with tab_mine:
        my_scheds = run_query("SELECT shift_id, shift_date, shift_time, COALESCE(status, 'SCHEDULED') FROM schedules WHERE pin=:p AND shift_date >= :today ORDER BY shift_date ASC", {"p": pin, "today": str(date.today())})
        if my_scheds:
            for s in my_scheds: st.markdown(f"<div class='glass-card'><strong>{s[1]}</strong> | {s[2]}</div>", unsafe_allow_html=True)
        else: st.info("No upcoming shifts.")

elif nav == "THE BANK":
    st.markdown("## 🏦 The Bank")
    if st.button("🔄 Refresh Bank Ledger"): st.rerun()
    st.markdown("### 🔗 Web3 Settlement Rail")
    st.markdown("<p style='color:#94a3b8; font-size:0.9rem;'>Link your Solana wallet for T+0 USDC PayFi Settlement.</p>", unsafe_allow_html=True)
    phantom_wallet_connector()
    with st.expander("Register Web3 Public Key"):
        with st.form("web3_register"):
            st.caption("Paste your Phantom Wallet key here to lock it to your HR profile.")
            pub_key_input = st.text_input("Solana Public Key")
            if st.form_submit_button("Lock Key to Vault"):
                link_web3_wallet(pin, pub_key_input)
                st.success("✅ Solana Key Registered Successfully!"); time.sleep(1.5); st.rerun()

    st.markdown("<br><hr style='border-color: rgba(255,255,255,0.05);'><br>", unsafe_allow_html=True)
    
    bank_info = run_query("SELECT dd_bank, dd_acct_last4, solana_pubkey FROM hr_onboarding WHERE pin=:p", {"p": pin})
    solana_key = bank_info[0][2] if bank_info and bank_info[0][2] else None
    
    banked_gross = st.session_state.user_state.get('earnings', 0.0)
    banked_net = banked_gross * (1 - sum(TAX_RATES.values()))
    
    st.markdown(f"<div class='stripe-box'><div style='display:flex; justify-content:space-between; align-items:center;'><span style='font-size:0.9rem; font-weight:600; text-transform:uppercase;'>Available Balance</span></div><h1 style='font-size:3.5rem; margin:10px 0 5px 0;'>${banked_gross:,.2f} Gross</h1><p style='margin:0; font-size:0.9rem; opacity:0.9;'>Net Estimate: ${banked_net:,.2f} • Tax: ${banked_gross - banked_net:,.2f}</p></div>", unsafe_allow_html=True)
    
    if banked_gross > 0.01 and not st.session_state.user_state.get('active', False):
        if st.button("⚡ EXECUTE ATOMIC PAYOUT", key="web3_btn", use_container_width=True):
            if solana_key:
                net, tax = execute_split_stream_payout(pin, banked_gross, solana_key)
                update_status(pin, "Inactive", 0, 0.0)
                st.session_state.user_state['earnings'] = 0.0
                st.success(f"✅ Atomic Settlement Complete! ${net:,.2f} routed to {solana_key[:4]}... | ${tax:,.2f} routed to Tax Treasury.")
                time.sleep(3); st.rerun()
            else: st.error("❌ No Web3 Wallet linked. Please connect your Phantom Wallet and register your key above.")
    elif st.session_state.user_state.get('active', False): st.info("You must clock out of your active shift before executing a payout.")

elif nav == "MY PROFILE":
    st.markdown("## 🗄️ Enterprise HR Vault")
    t_lic, t_sec = st.tabs(["🪪 LICENSES (ZK PROOFS)", "🔐 SECURITY"])
    
    with t_sec:
        st.markdown("### Account Security (Bcrypt)")
        with st.form("update_password_form"):
            current_pw = st.text_input("Current Password", type="password")
            new_pw = st.text_input("New Password", type="password")
            confirm_pw = st.text_input("Confirm New Password", type="password")
            if st.form_submit_button("Update Password"):
                db_pw_res = run_query("SELECT password FROM account_security WHERE pin=:p", {"p": pin})
                is_current_valid = verify_password(current_pw, db_pw_res[0][0]) if db_pw_res else (current_pw == USERS[pin]["password"])
                if not is_current_valid: st.error("❌ Current password incorrect.")
                elif new_pw != confirm_pw: st.error("❌ New passwords do not match.")
                else:
                    run_transaction("INSERT INTO account_security (pin, password) VALUES (:p, :pw) ON CONFLICT (pin) DO UPDATE SET password=:pw", {"p": pin, "pw": hash_password(new_pw)})
                    st.success("✅ Password successfully encrypted!"); time.sleep(2); st.rerun()
    with t_lic:
        with st.expander("➕ ADD NEW CREDENTIAL"):
            with st.form("cred_form"):
                doc_type = st.selectbox("Document Type", ["State RN License", "State RRT License"])
                doc_num = st.text_input("License Number")
                exp_date = st.date_input("Expiration Date")
                if st.form_submit_button("Save Credential"):
                    zk_hash = generate_zk_commitment(doc_num, pin)
                    run_transaction("INSERT INTO credentials (doc_id, pin, doc_type, doc_number, exp_date, status) VALUES (:id, :p, :dt, :dn, :ed, 'ACTIVE')", {"id": f"DOC-{int(time.time())}", "p": pin, "dt": doc_type, "dn": zk_hash, "ed": str(exp_date)})
                    st.success("✅ ZK Credential Secured. Plain-text license destroyed."); time.sleep(1.5); st.rerun()
        creds = run_query("SELECT doc_type, doc_number, exp_date FROM credentials WHERE pin=:p", {"p": pin})
        if creds:
            for c in creds: st.markdown(f"<div class='glass-card'><h4>{c[0]}</h4><p style='color:#94a3b8;'>ZK Hash: {c[1][:16]}...<br>Exp: {c[2]}</p></div>", unsafe_allow_html=True)
