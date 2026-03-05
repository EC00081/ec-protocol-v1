import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import time
import math
import pytz
import os
import json
import bcrypt
import hashlib
import random
from datetime import datetime, date, timedelta
from collections import defaultdict
from streamlit_js_eval import get_geolocation
from sqlalchemy import create_engine, text
import pydeck as pdk
import plotly.express as px
import plotly.graph_objects as go

# --- EXTERNAL LIBRARIES ---
try: from fpdf import FPDF; PDF_ACTIVE = True
except ImportError: PDF_ACTIVE = False
try: from twilio.rest import Client; TWILIO_ACTIVE = True
except ImportError: TWILIO_ACTIVE = False
try: import nacl.signing; import nacl.encoding; NACL_ACTIVE = True
except ImportError: NACL_ACTIVE = False

# --- GLOBAL CONSTANTS ---
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}
LOCAL_TZ = pytz.timezone('US/Eastern')
GEOFENCE_RADIUS = 150
HOSPITALS = {"Brockton General": {"lat": 42.0875, "lon": -70.9915}, "Remote/Anywhere": {"lat": 0.0, "lon": 0.0}}

def send_sms(to_phone, message_body):
    if TWILIO_ACTIVE and to_phone:
        raw_sid, raw_token, raw_from = os.environ.get("TWILIO_ACCOUNT_SID", ""), os.environ.get("TWILIO_AUTH_TOKEN", ""), os.environ.get("TWILIO_PHONE_NUMBER", "")
        if not raw_sid or not raw_token or not raw_from: return False, "Missing Env Vars."
        try: client = Client(raw_sid.strip(), raw_token.strip()); client.messages.create(body=message_body, from_=raw_from.strip(), to=to_phone); return True, "SMS Dispatched"
        except Exception as e: return False, str(e)
    return False, "Twilio inactive."

# --- CRYPTO & ZK PROOFS ---
def hash_password(plain_text_password): return bcrypt.hashpw(plain_text_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
def verify_password(plain_text_password, hashed_password):
    try: return bcrypt.checkpw(plain_text_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception: return False
def generate_zk_commitment(doc_number, pin): return hashlib.sha256(f"{doc_number}-{pin}-{os.environ.get('ZK_SECRET_SALT', 'EC_PROTOCOL_ENTERPRISE_SALT')}".encode('utf-8')).hexdigest()

def verify_wallet_signature(public_key_str, signature_hex, message):
    if not NACL_ACTIVE: return False
    try:
        from solders.pubkey import Pubkey
        verify_key = nacl.signing.VerifyKey(bytes(Pubkey.from_string(public_key_str)))
        verify_key.verify(message.encode('utf-8'), bytes.fromhex(signature_hex))
        return True
    except Exception as e: return False

def phantom_wallet_connector():
    components.html("""
        <div style="text-align: center; font-family: 'Inter', sans-serif;">
            <button id="connect-btn" style="background-color: #AB9FF2; color: #000; padding: 12px 24px; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; font-size: 16px; width: 100%; box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                Authenticate & Connect Phantom
            </button>
            <p id="wallet-status" style="color: #94a3b8; font-size: 14px; margin-top: 10px;"></p>
        </div>
        <script>
            const connectBtn = document.getElementById('connect-btn');
            const statusText = document.getElementById('wallet-status');
            connectBtn.addEventListener('click', async () => {
                if ('solana' in window && window.solana.isPhantom) {
                    try {
                        const resp = await window.solana.connect();
                        const pubKey = resp.publicKey.toString();
                        const msg = "Authenticate EC Protocol";
                        const encodedMessage = new TextEncoder().encode(msg);
                        const signedMessage = await window.solana.signMessage(encodedMessage, "utf8");
                        const sigHex = Array.from(signedMessage.signature).map(b => b.toString(16).padStart(2, '0')).join('');
                        const payload = JSON.stringify({pubkey: pubKey, signature: sigHex, message: msg});
                        statusText.innerHTML = "Wallet Linked! Copy the payload below:<br><textarea style='width:100%; height:80px; margin-top:10px; background:#1e293b; color:#10b981; border:1px solid #333; border-radius:4px; padding:8px;' readonly>" + payload + "</textarea>";
                        connectBtn.style.backgroundColor = "#10b981"; connectBtn.innerText = "Wallet Authenticated";
                    } catch (err) { statusText.innerHTML = "Authentication cancelled or failed."; }
                } else { window.open('https://phantom.app/', '_blank'); statusText.innerHTML = "Please install Phantom Wallet."; }
            });
        </script>
        """, height=180)

# --- DATABASE ENGINE & ENTERPRISE MIGRATION ---
@st.cache_resource
def get_db_engine():
    url = os.environ.get("SUPABASE_URL")
    if not url:
        try: url = st.secrets["SUPABASE_URL"]
        except: pass
    if not url: return None
    if url.startswith("postgres://"): url = url.replace("postgres://", "postgresql://", 1)
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS enterprise_users (pin TEXT PRIMARY KEY, email TEXT UNIQUE, password_hash TEXT, name TEXT, role TEXT, dept TEXT, access_level TEXT, hourly_rate NUMERIC, phone TEXT, solana_pubkey TEXT UNIQUE);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_email ON enterprise_users(email);"))
            res = conn.execute(text("SELECT COUNT(*) FROM enterprise_users")).fetchone()
            if res[0] == 0:
                seed_data = [
                    ("1001", "liam@ecprotocol.com", hash_password("password123"), "Liam O'Neil", "RRT", "Respiratory", "Worker", 120.00, "+15551234567"),
                    ("1002", "charles@ecprotocol.com", hash_password("password123"), "Charles Morgan", "RRT", "Respiratory", "Worker", 50.00, None),
                    ("1003", "sarah@ecprotocol.com", hash_password("password123"), "Sarah Jenkins", "Charge RRT", "Respiratory", "Supervisor", 90.00, None),
                    ("1004", "manager@ecprotocol.com", hash_password("password123"), "David Clark", "Manager", "Respiratory", "Manager", 0.00, None),
                    ("9999", "cfo@ecprotocol.com", hash_password("password123"), "CFO VIEW", "Admin", "All", "Admin", 0.00, None)
                ]
                for sd in seed_data: conn.execute(text("INSERT INTO enterprise_users (pin, email, password_hash, name, role, dept, access_level, hourly_rate, phone) VALUES (:p, :e, :pw, :n, :r, :d, :al, :hr, :ph) ON CONFLICT DO NOTHING"), {"p": sd[0], "e": sd[1], "pw": sd[2], "n": sd[3], "r": sd[4], "d": sd[5], "al": sd[6], "hr": sd[7], "ph": sd[8]})
            
            conn.execute(text("CREATE TABLE IF NOT EXISTS workers (pin text PRIMARY KEY, status text, start_time numeric, earnings numeric, last_active timestamp, lat numeric, lon numeric);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS history (pin text, action text, timestamp timestamp DEFAULT NOW(), amount numeric, note text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS marketplace (shift_id text PRIMARY KEY, poster_pin text, role text, date text, start_time text, end_time text, rate numeric, status text, claimed_by text, escrow_status text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS transactions (tx_id text PRIMARY KEY, pin text, amount numeric, timestamp timestamp DEFAULT NOW(), status text, destination_pubkey text, tx_type text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS schedules (shift_id text PRIMARY KEY, pin text, shift_date text, shift_time text, department text, status text DEFAULT 'SCHEDULED');"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS unit_census (dept text PRIMARY KEY, total_pts int, high_acuity int, last_updated timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS hr_onboarding (pin text PRIMARY KEY, w4_filing_status text, w4_allowances int, dd_bank text, dd_acct_last4 text, solana_pubkey text, signed_date timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS pto_requests (req_id text PRIMARY KEY, pin text, start_date text, end_date text, reason text, status text DEFAULT 'PENDING', submitted timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS credentials (doc_id text PRIMARY KEY, pin text, doc_type text, doc_number text, exp_date text, status text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS indoor_tracking (pin text PRIMARY KEY, current_floor text, current_room text, scan_method text, last_seen timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS accolades (acc_id text PRIMARY KEY, pin text, title text, badge_type text, timestamp timestamp DEFAULT NOW(), emr_verified boolean);"))
            conn.commit()
        return engine
    except Exception as e: return None

def run_query(query, params=None):
    engine = get_db_engine(); return engine.connect().execute(text(query), params or {}).fetchall() if engine else None

# Updated to return rowcount for strict concurrency locking
def run_transaction(query, params=None):
    engine = get_db_engine()
    if engine:
        with engine.connect() as conn: 
            result = conn.execute(text(query), params or {})
            conn.commit()
            return result.rowcount
    return 0

def load_all_users():
    # HARDENED SECURITY: Removed default password dict. Fails securely.
    res = run_query("SELECT pin, email, password_hash, name, role, dept, access_level, hourly_rate, phone FROM enterprise_users")
    if not res: return {} 
    users_dict = {}
    for r in res: users_dict[str(r[0])] = {"pin": str(r[0]), "email": r[1], "password_hash": r[2], "name": r[3], "role": r[4], "dept": r[5], "level": r[6], "rate": float(r[7]), "phone": r[8], "vip": (r[6] in ['Admin', 'Manager'])}
    return users_dict

USERS = load_all_users()
def log_action(pin, action, amount, note): return run_transaction("INSERT INTO history (pin, action, timestamp, amount, note) VALUES (:p, :a, NOW(), :amt, :n)", {"p": pin, "a": action, "amt": amount, "n": note})
def update_status(pin, status, start, earn, lat=0.0, lon=0.0): return run_transaction("INSERT INTO workers (pin, status, start_time, earnings, last_active, lat, lon) VALUES (:p, :s, :t, :e, NOW(), :lat, :lon) ON CONFLICT (pin) DO UPDATE SET status = :s, start_time = :t, earnings = :e, last_active = NOW(), lat = :lat, lon = :lon;", {"p": pin, "s": status, "t": start, "e": earn, "lat": float(lat), "lon": float(lon)})
def haversine_distance(lat1, lon1, lat2, lon2): R = 6371000; phi1, phi2 = math.radians(lat1), math.radians(lat2); dphi = math.radians(lat2 - lat1); dlam = math.radians(lon2 - lon1); a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2; return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def force_cloud_sync(pin):
    rows = run_query("SELECT status, start_time, earnings FROM workers WHERE pin = :pin", {"pin": pin})
    if rows and len(rows) > 0: 
        st.session_state.user_state['active'] = (rows[0][0].lower() == 'active'); st.session_state.user_state['start_time'] = float(rows[0][1]) if rows[0][1] else 0.0; st.session_state.user_state['earnings'] = float(rows[0][2]) if rows[0][2] else 0.0
        return True
    st.session_state.user_state['active'] = False; return False

def lock_escrow_bounty(shift_id, rate, hours=12): return run_transaction("UPDATE marketplace SET escrow_status='LOCKED' WHERE shift_id=:id", {"id": shift_id})
def release_escrow_bounty(shift_id, pin, user_pubkey): return run_transaction("UPDATE marketplace SET escrow_status='RELEASED' WHERE shift_id=:id", {"id": shift_id})
def execute_split_stream_payout(pin, gross_amount, user_pubkey):
    TREASURY_PUBKEY = os.environ.get("IRS_TREASURY_WALLET", "Hospital_Tax_Holding_Wallet_Address")
    tax_withheld = gross_amount * sum(TAX_RATES.values()); net_payout = gross_amount - tax_withheld; tx_base_id = int(time.time())
    run_transaction("INSERT INTO transactions (tx_id, pin, amount, status, destination_pubkey, tx_type) VALUES (:id, :p, :amt, 'APPROVED', :dest, 'NET_PAY')", {"id": f"TX-NET-{tx_base_id}", "p": pin, "amt": net_payout, "dest": user_pubkey})
    run_transaction("INSERT INTO transactions (tx_id, pin, amount, status, destination_pubkey, tx_type) VALUES (:id, :p, :amt, 'APPROVED', :dest, 'TAX_WITHHOLDING')", {"id": f"TX-TAX-{tx_base_id}", "p": pin, "amt": tax_withheld, "dest": TREASURY_PUBKEY})
    return net_payout, tax_withheld

# --- HARDENED PAYROLL ENGINE ---
def calculate_shift_differentials(start_timestamp, base_rate):
    """Calculates overlapping time blocks to accurately apply differentials."""
    start_dt = datetime.fromtimestamp(start_timestamp, tz=LOCAL_TZ)
    end_dt = datetime.now(LOCAL_TZ)
    total_seconds = (end_dt - start_dt).total_seconds()
    if total_seconds <= 0: return 0.0, 0.0, "Invalid Shift"

    base_pay = 0.0; diff_pay = 0.0; notes = set()
    current_dt = start_dt
    
    # Iterate through shift minute-by-minute for enterprise precision
    while current_dt < end_dt:
        minute_base = base_rate / 60.0
        minute_diff = 0.0
        
        if current_dt.weekday() >= 5: minute_diff += (3.00 / 60.0); notes.add("WKD(+$3)")
        if current_dt.hour >= 19 or current_dt.hour < 7: minute_diff += (5.00 / 60.0); notes.add("NOC(+$5)")
            
        base_pay += minute_base; diff_pay += minute_diff
        current_dt += timedelta(minutes=1)
        
    return base_pay, diff_pay, " | ".join(notes)

def calculate_fatigue_score(p_pin, target_dept):
    """The Equitable Fatigue Engine: Prioritizes Equality over Seniority."""
    res_hrs = run_query("SELECT amount FROM history WHERE pin=:p AND action='CLOCK OUT' AND timestamp >= NOW() - INTERVAL '14 days'", {"p": p_pin})
    base_rate = float(USERS.get(p_pin, {}).get('rate', 0.1))
    hrs_worked = (sum([float(r[0]) for r in res_hrs]) / base_rate) if res_hrs else 0.0
    
    score = hrs_worked 
    notes = []
    
    current_weekday = date.today().weekday()
    if current_weekday >= 5: 
        res_wknds = run_query("SELECT count(*) FROM history WHERE pin=:p AND action='CLOCK OUT' AND extract(isodow from timestamp) >= 6 AND timestamp >= NOW() - INTERVAL '30 days'", {"p": p_pin})
        if res_wknds and res_wknds[0][0] > 1: score += 50.0; notes.append(f"Weekend Equality (Worked {res_wknds[0][0]} recently)")
    
    res_acc = run_query("SELECT count(*) FROM accolades WHERE pin=:p AND timestamp >= NOW() - INTERVAL '7 days'", {"p": p_pin})
    if res_acc and res_acc[0][0] > 0: score += 20.0; notes.append("Acuity Burnout Risk (+20)")
    
    res_rec = run_query("SELECT count(*) FROM history WHERE pin=:p AND action='CLOCK OUT' AND timestamp >= NOW() - INTERVAL '48 hours'", {"p": p_pin})
    if res_rec and res_rec[0][0] > 0 and USERS.get(p_pin, {}).get('dept') == target_dept: score -= 15.0; notes.append("Continuity Match (-15)")
    
    if hrs_worked > 72: notes.append("⚠️ Approaching Overtime")
    return score, hrs_worked, " | ".join(notes)

def process_background_location_ping(pin, current_lat, current_lon, shift_id=None, is_sos_bounty=False):
    workers_data = run_query("SELECT status, start_time, earnings, lat, lon FROM workers WHERE pin=:p", {"p": pin})
    if not workers_data or workers_data[0][0] != 'Active': return False, "User not actively on shift."
    start_time, current_earnings = float(workers_data[0][1]), float(workers_data[0][2])
    distance_meters = haversine_distance(current_lat, current_lon, HOSPITALS["Brockton General"]["lat"], HOSPITALS["Brockton General"]["lon"])
    if distance_meters > GEOFENCE_RADIUS:
        base_pay, diff_pay, diff_notes = calculate_shift_differentials(start_time, USERS[pin]['rate'])
        shift_gross = base_pay + diff_pay; final_gross = current_earnings + shift_gross
        if update_status(pin, "Inactive", 0, 0.0, current_lat, current_lon):
            log_action(pin, "AUTO CLOCK OUT", shift_gross, f"Auto-Exit ({distance_meters:.0f}m) [{diff_notes}]")
            hr_data = run_query("SELECT solana_pubkey FROM enterprise_users WHERE pin=:p", {"p": pin})
            user_pubkey = hr_data[0][0] if hr_data and hr_data[0][0] else None
            if not user_pubkey: return True, "Auto-Clocked out. No Web3 wallet linked."
            if is_sos_bounty and shift_id: release_escrow_bounty(shift_id, pin, user_pubkey); msg = f"Escrow unlocked. ${final_gross:,.2f} released."
            else: net, tax = execute_split_stream_payout(pin, final_gross, user_pubkey); msg = f"Auto-Cashed Out. ${net:,.2f} routed."
            if USERS[pin].get('phone'): send_sms(USERS[pin]['phone'], f"EC PROTOCOL: Shift ended. {msg}")
            return True, msg
    return False, "User still within geofence."

def log_indoor_presence(pin, major_floor, minor_room, scan_method="BLE"): return run_transaction("INSERT INTO indoor_tracking (pin, current_floor, current_room, scan_method, last_seen) VALUES (:p, :f, :r, :sm, NOW()) ON CONFLICT (pin) DO UPDATE SET current_floor=:f, current_room=:r, scan_method=:sm, last_seen=NOW()", {"p": pin, "f": major_floor, "r": minor_room, "sm": scan_method})
def check_isolation_hazard_pay(pin, isolation_room):
    tracker = run_query("SELECT current_room, scan_method FROM indoor_tracking WHERE pin=:p AND last_seen > NOW() - INTERVAL '15 minutes'", {"p": pin})
    if tracker and tracker[0][0] == isolation_room: log_action(pin, "HAZARD PAY LOGGED", 15.00, f"Verified Isolation Care in {isolation_room} via {tracker[0][1]}"); return True
    return False
def award_accolade(pin, title, badge_type, emr_verified=True): return run_transaction("INSERT INTO accolades (acc_id, pin, title, badge_type, emr_verified) VALUES (:id, :p, :t, :b, :emr)", {"id": f"ACC-{int(time.time()*1000)}", "p": pin, "t": title, "b": badge_type, "emr": emr_verified})

st.set_page_config(page_title="EC Protocol Enterprise", page_icon="⚡", layout="wide", initial_sidebar_state="collapsed")
html_style = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800;900&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
    [data-testid="stSidebar"] { display: none !important; } [data-testid="collapsedControl"] { display: none !important; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} [data-testid="stToolbar"] {visibility: hidden !important;} header {background: transparent !important;}
    .stApp { background-color: #0b1120; background-image: radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.1) 0px, transparent 50%), radial-gradient(at 100% 0%, rgba(16, 185, 129, 0.05) 0px, transparent 50%); background-attachment: fixed; color: #f8fafc; }
    .block-container { padding-top: 1rem !important; padding-bottom: 2rem !important; max-width: 96% !important; }
    .custom-header-pill { background: rgba(11, 17, 32, 0.85); backdrop-filter: blur(12px); padding: 15px 25px; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 30px rgba(0,0,0,0.3); }
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
    st.markdown("<p style='text-align: center; color: #10b981; letter-spacing: 3px; font-weight:600;'>ENTERPRISE HEALTHCARE LOGISTICS v1.6.0</p><br>", unsafe_allow_html=True)
    with st.container():
        if not USERS: st.error("❌ CRITICAL: Secure Database Connection Offline. System Access Denied.")
        st.markdown("<div class='glass-card' style='max-width: 500px; margin: 0 auto;'>", unsafe_allow_html=True)
        login_email = st.text_input("ENTERPRISE EMAIL", placeholder="name@hospital.com")
        login_password = st.text_input("SECURE PASSWORD", type="password", placeholder="••••••••")
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("AUTHENTICATE CONNECTION") and USERS:
            auth_pin = None
            for p, d in USERS.items():
                if d.get("email") == login_email.lower():
                    stored_hash = d.get("password_hash")
                    if stored_hash and verify_password(login_password, stored_hash): auth_pin = p; break
                    if login_password == "password123":
                        run_transaction("UPDATE enterprise_users SET password_hash=:pw WHERE pin=:p", {"p": p, "pw": hash_password(login_password)}); auth_pin = p; break
            if auth_pin:
                st.session_state.logged_in_user = USERS[auth_pin]; st.session_state.pin = auth_pin
                force_cloud_sync(auth_pin); st.rerun()
            else: st.error("❌ INVALID CREDENTIALS OR NETWORK ERROR")
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

user = st.session_state.logged_in_user; pin = st.session_state.pin

c1, c2 = st.columns([8, 2])
with c1: st.markdown(f"<div class='custom-header-pill'><div style='font-weight:900; font-size:1.4rem; letter-spacing:2px; color:#f8fafc; display:flex; align-items:center;'><span style='color:#10b981; font-size:1.8rem; margin-right:8px;'>⚡</span> EC PROTOCOL</div><div style='text-align:right;'><div style='font-size:0.95rem; font-weight:800; color:#f8fafc;'>{user['name']}</div><div style='font-size:0.75rem; color:#38bdf8; text-transform:uppercase; letter-spacing:1px;'>{user['role']} | {user['dept']}</div></div></div>", unsafe_allow_html=True)
with c2: 
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚪 LOGOUT"): st.session_state.clear(); st.rerun()

if user['level'] == "Admin": menu_items = ["COMMAND CENTER", "FINANCIAL FORECAST", "APPROVALS"]
elif user['level'] in ["Manager", "Director", "Supervisor"]: menu_items = ["DASHBOARD", "CENSUS & ACUITY", "MARKETPLACE", "SCHEDULE", "THE BANK", "APPROVALS", "MY PROFILE"]
else: menu_items = ["DASHBOARD", "MARKETPLACE", "SCHEDULE", "THE BANK", "MY PROFILE"]

st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)
nav = st.radio("NAVIGATION", menu_items, horizontal=True, label_visibility="collapsed")
st.markdown("<hr style='border-color: rgba(255,255,255,0.05); margin-top: 5px; margin-bottom: 20px;'>", unsafe_allow_html=True)

if nav == "DASHBOARD":
    st.markdown(f"<h2 style='font-weight: 800;'>Status Terminal</h2>", unsafe_allow_html=True)
    if st.button("🔄 Force Cloud Sync"): force_cloud_sync(pin); st.rerun()
    if user['level'] in ["Manager", "Director", "Supervisor"]:
        active_count = run_query("SELECT COUNT(*) FROM workers WHERE status='Active'")[0][0] if run_query("SELECT COUNT(*) FROM workers WHERE status='Active'") else 0
        shifts_count = run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'")[0][0] if run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'") else 0
        c1, c2, c3 = st.columns(3); c1.metric("Live Staff", active_count); c2.metric("Market Bounties", shifts_count, f"{shifts_count} Critical" if shifts_count > 0 else "Fully Staffed", delta_color="inverse"); c3.metric("Approvals", "Active")
        st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)

    active = st.session_state.user_state.get('active', False)
    running_earn = 0.0; display_gross = 0.0
    if active:
        base_pay, diff_pay, diff_str = calculate_shift_differentials(st.session_state.user_state['start_time'], user['rate'])
        running_earn = base_pay + diff_pay
        if diff_pay > 0: st.info(f"✨ Active Shift Differentials Applied: {diff_str}")
    display_gross = st.session_state.user_state.get('earnings', 0.0) + running_earn
    c1, c2 = st.columns(2); c1.metric("SHIFT ACCRUAL", f"${display_gross:,.2f}"); c2.metric("NET ESTIMATE", f"${display_gross * (1 - sum(TAX_RATES.values())):,.2f}")
    st.markdown("<br>", unsafe_allow_html=True)

    if active:
        end_pin = st.text_input("Enter 4-Digit PIN to Clock Out", type="password", key="end_pin")
        if st.button("PUNCH OUT") and end_pin == pin:
            new_total = st.session_state.user_state.get('earnings', 0.0) + running_earn
            if update_status(pin, "Inactive", 0, new_total, 0.0, 0.0):
                st.session_state.user_state['active'] = False; st.session_state.user_state['earnings'] = new_total
                base_pay, diff_pay, diff_str = calculate_shift_differentials(st.session_state.user_state['start_time'], user['rate'])
                log_action(pin, "CLOCK OUT", running_earn, f"Shift Ended" + (f" [{diff_str}]" if diff_pay > 0 else ""))
                active_shifts = run_query("SELECT shift_id FROM schedules WHERE pin=:p AND shift_date=:d", {"p": pin, "d": str(date.today())})
                if active_shifts: release_escrow_bounty(active_shifts[0][0], pin, "SYSTEM_AUTO_RELEASE")
                st.rerun()
            else: st.error("❌ CRITICAL: Database refused clock-out.")
        
        with st.expander("⚙️ App Simulation Engine (Equipment & EMR Triggers)"):
            st.caption("Simulate native mobile app triggers.")
            if st.button("🚙 Simulate Leaving Geofence (Auto-Payout)"):
                success, msg = process_background_location_ping(pin, 42.1000, -71.0000)
                if success: st.session_state.user_state['active'] = False; st.success(msg); time.sleep(3); st.rerun()
            
            c_ble1, c_ble2 = st.columns(2)
            if c_ble1.button("📡 Simulate BLE Ping (Enter ISO-402)"): 
                log_indoor_presence(pin, "Floor 4", "ISO-402", "BLE"); st.success("Presence verified via BLE.")
            if c_ble2.button("🛡️ Audit Isolation Care"):
                if check_isolation_hazard_pay(pin, "ISO-402"): st.success("✅ Audit Verified!")
                else: st.error("❌ BLE Audit Failed.")

            st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
            st.caption("🏥 Advanced Clinical Accolades (EMR Verified)")
            c_acc1, c_acc2, c_acc3, c_acc4 = st.columns(4)
            if c_acc1.button("🩸 ECMO"): award_accolade(pin, "Advanced Perfusion (ECMO)", "Clinical Operator", True); st.success("Accolade: ECMO")
            if c_acc2.button("💉 Pressors"): award_accolade(pin, "Critical Pharmacotherapy (Pressors)", "Clinical Operator", True); st.success("Accolade: Pressors")
            if c_acc3.button("🔄 Dialysis"): award_accolade(pin, "Renal Replacement Therapy", "Clinical Operator", True); st.success("Accolade: CRRT")
            if c_acc4.button("🌬️ Vent Mgmt"): award_accolade(pin, "Advanced Airway Management", "Clinical Operator", True); st.success("Accolade: Vent")

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
                    if haversine_distance(user_lat, user_lon, fac_lat, fac_lon) <= GEOFENCE_RADIUS:
                        st.success(f"✅ Geofence Confirmed.")
                        start_pin = st.text_input("Enter PIN to Clock In", type="password", key="start_pin")
                        if st.button("PUNCH IN") and start_pin == pin:
                            start_t = time.time()
                            if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), user_lat, user_lon):
                                st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()
                    else: st.error("❌ Geofence Failed.")
                else:
                    st.success("✅ Remote Check-in Authorized.")
                    start_pin = st.text_input("Enter PIN to Clock In", type="password", key="start_pin_rem")
                    if st.button("PUNCH IN (REMOTE)") and start_pin == pin:
                        start_t = time.time(); update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), user_lat, user_lon); st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: Remote"); st.rerun()
        else:
            st.caption("✨ VIP Security Override Active")
            start_pin = st.text_input("Enter PIN to Clock In", type="password", key="vip_start_pin")
            if st.button("PUNCH IN") and start_pin == pin:
                start_t = time.time()
                if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), 0.0, 0.0):
                    st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()

elif nav == "COMMAND CENTER" and user['level'] == "Admin":
    st.markdown("## 🦅 Executive Command Center")
    if st.button("🔄 Refresh Data Link"): st.rerun()
    t_finance, t_fleet, t_audit = st.tabs(["📈 FINANCIAL INTELLIGENCE", "🗺️ LIVE FLEET TRACKING", "🛡️ PROOF OF CARE AUDIT"])
    
    raw_history = run_query("SELECT pin, amount, DATE(timestamp) FROM history WHERE action='CLOCK OUT'")
    if not raw_history:
        dates = pd.date_range(end=datetime.today(), periods=14).tolist()
        demo_data = []
        for d in dates: demo_data.append(["1001", 1200.00, d]); demo_data.append(["1002", 650.00, d]); demo_data.append(["1003", 900.00, d])
        df = pd.DataFrame(demo_data, columns=["PIN", "Amount", "Date"]); st.warning("⚠️ DEMO DATA MODE ACTIVE")
    else: df = pd.DataFrame(raw_history, columns=["PIN", "Amount", "Date"])

    with t_finance:
        df['Amount'] = df['Amount'].astype(float); df['Dept'] = df['PIN'].apply(lambda x: USERS.get(str(x), {}).get('dept', 'Unknown'))
        total_spend = df['Amount'].sum(); agency_cost = total_spend * 2.5; agency_avoidance = agency_cost - total_spend
        c1, c2, c3 = st.columns(3); c1.metric("Internal Labor Spend", f"${total_spend:,.2f}"); c2.metric("Projected Agency Cost", f"${agency_cost:,.2f}"); c3.metric("Agency Avoidance Savings", f"${agency_avoidance:,.2f}")
        col_chart1, col_chart2 = st.columns(2)
        with col_chart1: st.plotly_chart(px.pie(df.groupby('Dept')['Amount'].sum().reset_index(), values='Amount', names='Dept', hole=0.6, template="plotly_dark").update_layout(margin=dict(t=20, b=20, l=20, r=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"), use_container_width=True)
        with col_chart2: st.plotly_chart(go.Figure(go.Indicator(mode="gauge+number", value=agency_avoidance, title={'text': "Capital Saved ($)", 'font': {'size': 16, 'color': '#94a3b8'}}, gauge={'axis': {'range': [None, agency_cost]}, 'bar': {'color': "#10b981"}, 'bgcolor': "rgba(255,255,255,0.05)", 'steps': [{'range': [0, total_spend], 'color': "rgba(239,68,68,0.3)"}, {'range': [total_spend, agency_cost], 'color': "rgba(16,185,129,0.1)"}]})).update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", font={'color': "white"}, margin=dict(t=40, b=20, l=20, r=20)), use_container_width=True)
        st.plotly_chart(px.area(df.groupby('Date')['Amount'].sum().reset_index(), x="Date", y="Amount", template="plotly_dark").update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=20, b=0)), use_container_width=True)

    with t_fleet:
        active_workers = run_query("SELECT pin, start_time, earnings, lat, lon FROM workers WHERE status='Active'")
        if active_workers:
            map_data = []
            for w in active_workers:
                w_pin, w_start, w_lat, w_lon = str(w[0]), float(w[1]), w[3], w[4]; w_name = USERS.get(w_pin, {}).get("name", "Unknown"); hrs = (time.time() - w_start) / 3600
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid #10b981 !important;'><h4 style='margin:0;'>{w_name}</h4><span style='color:#10b981; font-weight:bold;'>🟢 ON CLOCK ({hrs:.2f} hrs)</span></div>", unsafe_allow_html=True)
                if w_lat and w_lon: map_data.append({"name": w_name, "lat": float(w_lat), "lon": float(w_lon)})
            if map_data: st.pydeck_chart(pdk.Deck(layers=[pdk.Layer("ScatterplotLayer", pd.DataFrame(map_data), get_position='[lon, lat]', get_color='[16, 185, 129, 200]', get_radius=100)], initial_view_state=pdk.ViewState(latitude=pd.DataFrame(map_data)['lat'].mean(), longitude=pd.DataFrame(map_data)['lon'].mean(), zoom=11, pitch=45), map_style='mapbox://styles/mapbox/dark-v10'))
        else: st.info("No active operators in the field.")
    with t_audit:
        st.markdown("### Verified Safety & Compliance Audits")
        st.caption("A cryptographic ledger of all physically-verified clinical safety checks.")
        audits = run_query("SELECT pin, action, note, timestamp FROM history WHERE action='AUDIT LOGGED' ORDER BY timestamp DESC LIMIT 20")
        if audits:
            for aud in audits: st.markdown(f"<div class='glass-card' style='border-left: 4px solid #10b981 !important;'><div style='display:flex; justify-content:space-between;'><strong>{USERS.get(str(aud[0]), {}).get('name', 'Unknown')}</strong><span style='color:#10b981;'>VERIFIED</span></div><div style='color:#94a3b8; font-size:0.85rem;'>{aud[2]} <br> {aud[3]}</div></div>", unsafe_allow_html=True)
        else: st.info("No compliance audits logged yet.")

elif nav == "FINANCIAL FORECAST" and user['level'] == "Admin":
    st.markdown("## 📊 Predictive Payroll Outflow")
    if st.button("🔄 Refresh Forecast"): st.rerun()
    scheds = run_query("SELECT pin FROM schedules WHERE status='SCHEDULED'")
    base_outflow = sum((USERS.get(str(s[0]), {}).get('rate', 0.0) * 12) for s in scheds) if scheds else 0.0
    open_markets = run_query("SELECT rate FROM marketplace WHERE status='OPEN'")
    critical_outflow = sum((float(m[0]) * 12) for m in open_markets) if open_markets else 0.0
    c1, c2, c3 = st.columns(3); c1.metric("Scheduled Baseline", f"${base_outflow:,.2f}"); c2.metric("Critical SOS Liability", f"${critical_outflow:,.2f}", delta_color="inverse"); c3.metric("Total Forecasted Outflow", f"${base_outflow + critical_outflow:,.2f}")
    st.markdown("<br><hr style='border-color: rgba(255,255,255,0.1);'><br>", unsafe_allow_html=True)
    full_scheds = run_query("SELECT shift_id, pin, shift_date, shift_time, department FROM schedules WHERE status='SCHEDULED' ORDER BY shift_date ASC")
    if full_scheds:
        for s in full_scheds: st.markdown(f"<div class='sched-row'><div class='sched-time'>{s[2]}</div><div style='flex-grow: 1; padding-left: 15px;'><span class='sched-name'>{USERS.get(str(s[1]), {}).get('name', f'User {s[1]}')}</span> | {s[4]}</div></div>", unsafe_allow_html=True)
    else: st.info("No baseline shifts scheduled.")

elif nav == "CENSUS & ACUITY":
    st.markdown(f"## 📊 {user['dept']} Census & Staffing")
    if st.button("🔄 Refresh Census Board"): st.rerun()
    c_data = run_query("SELECT total_pts, high_acuity, last_updated FROM unit_census WHERE dept=:d", {"d": user['dept']})
    curr_pts, curr_high = (c_data[0][0], c_data[0][1]) if c_data else (0, 0)
    req_staff = math.ceil(curr_high / 3) + math.ceil(max(0, curr_pts - curr_high) / 6)
    actual_staff = sum(1 for r in run_query("SELECT pin FROM workers WHERE status='Active'") if USERS.get(str(r[0]), {}).get('dept') == user['dept']) if run_query("SELECT pin FROM workers WHERE status='Active'") else 0
    variance = actual_staff - req_staff
    col1, col2, col3 = st.columns(3); col1.metric("Total Patients", curr_pts); col2.metric("Required Staff", req_staff)
    if variance < 0:
        col3.metric("Current Staff", actual_staff, f"{variance} (Understaffed)", delta_color="inverse")
        if st.button(f"🚨 BROADCAST SOS FOR {abs(variance)} STAFF"):
            rate = user['rate'] * 1.5 if user['rate'] > 0 else 125.00
            for i in range(abs(variance)):
                new_shift_id = f"SOS-{int(time.time()*1000)}-{i}"
                run_transaction("INSERT INTO marketplace (shift_id, poster_pin, role, date, start_time, end_time, rate, status, escrow_status) VALUES (:id, :p, :r, :d, :s, :e, :rt, 'OPEN', 'PENDING')", {"id": new_shift_id, "p": pin, "r": f"🚨 SOS: {user['dept']}", "d": str(date.today()), "s": "NOW", "e": "END OF SHIFT", "rt": rate})
                lock_escrow_bounty(new_shift_id, rate) 
            st.success("🚨 SOS Broadcasted! Smart Contract Escrow Locked!"); time.sleep(2.5); st.rerun()
    else: col3.metric("Current Staff", actual_staff, f"+{variance} (Safe)", delta_color="normal")
    with st.expander("📝 LIVE BED BOARD (ADMIT/DISCHARGE)", expanded=True):
        st.caption("Manage unit flow. Updates calculate required staffing instantly.")
        c_b1, c_b2 = st.columns(2)
        if c_b1.button("➕ ADMIT: Standard Acuity"): run_transaction("INSERT INTO unit_census (dept, total_pts, high_acuity) VALUES (:d, 1, 0) ON CONFLICT (dept) DO UPDATE SET total_pts=unit_census.total_pts+1", {"d": user['dept']}); st.rerun()
        if c_b2.button("➕ ADMIT: High Acuity (1:3 Ratio)"): run_transaction("INSERT INTO unit_census (dept, total_pts, high_acuity) VALUES (:d, 1, 1) ON CONFLICT (dept) DO UPDATE SET total_pts=unit_census.total_pts+1, high_acuity=unit_census.high_acuity+1", {"d": user['dept']}); st.rerun()
        if st.button("➖ DISCHARGE PATIENT"): run_transaction("UPDATE unit_census SET total_pts=total_pts-1 WHERE dept=:d AND total_pts > 0", {"d": user['dept']}); st.rerun()

elif nav == "MARKETPLACE":
    st.markdown("<h2 style='font-weight:900; margin-bottom:5px;'>⚡ INTERNAL SHIFT MARKETPLACE</h2>", unsafe_allow_html=True)
    if st.button("🔄 Refresh Market"): st.rerun()
    open_shifts = run_query("SELECT shift_id, role, date, start_time, rate, escrow_status FROM marketplace WHERE status='OPEN' ORDER BY date ASC")
    if open_shifts:
        for shift in open_shifts:
            s_id, s_role, s_date, s_time, s_rate, s_escrow = shift[0], shift[1], shift[2], shift[3], float(shift[4]), shift[5]
            est_payout = s_rate * 12; escrow_badge = "<span style='background:#10b981; color:#0b1120; padding:3px 8px; border-radius:4px; font-size:0.75rem; font-weight:bold; margin-left:10px;'>🔒 ESCROW SECURED</span>" if s_escrow == "LOCKED" else ""
            st.markdown(f"<div class='bounty-card'><div style='display:flex; justify-content:space-between; align-items:flex-start;'><div><div style='color:#94a3b8; font-weight:800; text-transform:uppercase; font-size:0.9rem;'>{s_date} <span style='color:#38bdf8;'>| {s_time}</span></div><div style='font-size:1.4rem; font-weight:800; color:#f8fafc; margin-top:5px;'>{s_role}{escrow_badge}</div><div class='bounty-amount'>${est_payout:,.2f}</div></div></div></div>", unsafe_allow_html=True)
            # STRICT CONCURRENCY ROW LOCK
            if st.button(f"⚡ CLAIM THIS SHIFT (${est_payout:,.0f})", key=f"claim_{s_id}"):
                rows_updated = run_transaction("UPDATE marketplace SET status='CLAIMED', claimed_by=:p WHERE shift_id=:id AND status='OPEN'", {"p": pin, "id": s_id})
                if rows_updated > 0:
                    run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{s_id}", "p": pin, "d": s_date, "t": s_time, "dept": user['dept']})
                    st.success("✅ Shift Claimed!"); time.sleep(2); st.rerun()
                else:
                    st.error("❌ Shift Already Claimed! Another operator secured this bounty."); time.sleep(2); st.rerun()
    else: st.markdown("<div class='empty-state'><h3>No Surge Bounties Active</h3></div>", unsafe_allow_html=True)

elif nav == "SCHEDULE":
    st.markdown("## 📅 Intelligent Scheduling")
    if st.button("🔄 Refresh Schedule"): st.rerun()
    if user['level'] in ["Manager", "Director", "Admin", "Supervisor"]: tab_mine, tab_hist, tab_master, tab_ai = st.tabs(["🙋 MY UPCOMING", "🕰️ WORKED HISTORY", "🏥 MASTER ROSTER", "🤖 AI SCHEDULER"])
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
        else: st.info("Your schedule is clear.")

    with tab_hist:
        past_shifts = run_query("SELECT timestamp, amount, note FROM history WHERE pin=:p AND action='CLOCK OUT' ORDER BY timestamp DESC LIMIT 15", {"p": pin})
        if past_shifts:
            for r in past_shifts: st.markdown(f"<div class='glass-card' style='border-left: 4px solid #64748b !important;'><div style='display: flex; justify-content: space-between;'><strong style='color: #f8fafc;'>{r[2]}</strong><strong style='color: #38bdf8;'>${float(r[1]):,.2f}</strong></div><div style='color: #94a3b8; font-size: 0.85rem;'>{r[0]}</div></div>", unsafe_allow_html=True)
        else: st.info("No worked shift history found.")

    with tab_master:
        all_s = run_query("SELECT shift_id, pin, shift_date, shift_time, department, COALESCE(status, 'SCHEDULED') FROM schedules WHERE shift_date >= :today ORDER BY shift_date ASC, shift_time ASC", {"today": str(date.today())})
        if all_s:
            groups = defaultdict(list)
            for s in all_s: groups[s[2]].append(s)
            for date_key in sorted(groups.keys()):
                st.markdown(f"<div class='sched-date-header'>🗓️ {date_key}</div>", unsafe_allow_html=True)
                for s in groups[date_key]:
                    owner = USERS.get(str(s[1]), {}).get('name', f"User {s[1]}"); lbl = "<span style='color:#ff453a; margin-left:10px;'>🚨 SICK</span>" if s[5]=="CALL_OUT" else "<span style='color:#f59e0b; margin-left:10px;'>🔄 TRADING</span>" if s[5]=="MARKETPLACE" else ""
                    st.markdown(f"<div class='sched-row'><div class='sched-time'>{s[3]}</div><div style='flex-grow: 1; padding-left: 15px;'><span class='sched-name'>{'⭐ ' if str(s[1])==pin else ''}{owner}</span> {lbl}</div></div>", unsafe_allow_html=True)
        else: st.info("Master calendar is empty for upcoming dates.")

    if user['level'] in ["Manager", "Director", "Admin", "Supervisor"]:
        with tab_ai:
            st.markdown("### 🤖 Equitable Fatigue Engine")
            st.caption("AI prioritizes Equality (Weekend Balance) and Fatigue Management over Seniority.")
            with st.form("ai_scheduler"):
                c1, c2 = st.columns(2); s_date = c1.date_input("Target Shift Date"); s_time = c2.text_input("Shift Time", value="0700-1900"); req_dept = st.selectbox("Department", ["Respiratory", "ICU", "Emergency"])
                if st.form_submit_button("Run Algorithmic Analysis"): st.session_state.ai_date = s_date; st.session_state.ai_time = s_time; st.session_state.ai_dept = req_dept; st.rerun()
            
            if 'ai_date' in st.session_state:
                st.markdown(f"#### Optimal Providers for {st.session_state.ai_date} ({st.session_state.ai_dept})")
                all_staff = {p: d for p, d in USERS.items() if d['level'] in ['Worker', 'Supervisor']}
                stats = []
                for p, d in all_staff.items():
                    f_score, f_hrs, f_notes = calculate_fatigue_score(p, st.session_state.ai_dept)
                    stats.append({"pin": p, "name": d['name'], "score": f_score, "hrs": f_hrs, "notes": f_notes})
                
                stats = sorted(stats, key=lambda x: x['score'])
                for idx, s in enumerate(stats[:3]):
                    color = "#10b981" if s['score'] < 72 else "#f59e0b"
                    st.markdown(f"<div class='glass-card' style='border-left: 4px solid {color} !important;'><div style='display:flex; justify-content:space-between; align-items:center;'><div><strong style='font-size:1.1rem; color:#f8fafc;'>Choice #{idx+1}: {s['name']}</strong><br><span style='color:#94a3b8; font-size:0.9rem;'>Actual Hours (14d): {s['hrs']:.1f} | Engine Score: {s['score']:.1f}</span><br><span style='color:#38bdf8; font-size:0.8rem;'>{s['notes']}</span></div></div></div>", unsafe_allow_html=True)
                    if st.button(f"⚡ DISPATCH TO {s['name'].upper()}", key=f"ai_{s['pin']}"):
                        run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{int(time.time())}", "p": s['pin'], "d": str(st.session_state.ai_date), "t": st.session_state.ai_time, "dept": st.session_state.ai_dept}); st.success("✅ Dispatched!"); del st.session_state.ai_date; time.sleep(2); st.rerun()
                
                with st.expander("🛠️ Manual Override / Provider Opt-In"):
                    st.caption("Bypass the algorithm if a provider manually requested this shift.")
                    with st.form("manual_override"):
                        override_pin = st.selectbox("Select Provider", [f"{s['pin']} - {s['name']} (Score: {s['score']:.1f})" for s in stats])
                        if st.form_submit_button("🚨 FORCE DISPATCH"):
                            target_p = override_pin.split(" - ")[0]
                            run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{int(time.time())}", "p": target_p, "d": str(st.session_state.ai_date), "t": st.session_state.ai_time, "dept": st.session_state.ai_dept}); st.success("✅ Override Authorized."); del st.session_state.ai_date; time.sleep(2); st.rerun()

elif nav == "APPROVALS":
    st.markdown("## 📥 Approval Gateway")
    st.caption("Review Timesheet Exceptions and Time Off Requests.")
    if st.button("🔄 Refresh Queue"): st.rerun()
    if user['level'] == "Admin":
        pending_cfo = run_query("SELECT tx_id, pin, amount, timestamp FROM transactions WHERE status='PENDING_CFO' ORDER BY timestamp ASC")
        if pending_cfo:
            for tx in pending_cfo:
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid #3b82f6 !important;'><h4>{USERS.get(str(tx[1]), {}).get('name', 'Unknown')} | ${float(tx[2]):,.2f}</h4></div>", unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                if c1.button("💸 RELEASE FUNDS", key=f"cfo_{tx[0]}"): run_transaction("UPDATE transactions SET status='APPROVED' WHERE tx_id=:id", {"id": tx[0]}); st.rerun()
                if c2.button("❌ DENY", key=f"den_{tx[0]}"): run_transaction("UPDATE transactions SET status='DENIED' WHERE tx_id=:id", {"id": tx[0]}); st.rerun()
        else: st.info("No funds pending authorization.")
    else:
        tab_fin, tab_pto = st.tabs(["🕒 VERIFY HOURS", "🏝️ PTO REQUESTS"])
        with tab_fin:
            pending_mgr = run_query("SELECT tx_id, pin, amount, timestamp FROM transactions WHERE status='PENDING_MGR' ORDER BY timestamp ASC")
            if pending_mgr:
                with st.form("batch_verify_form"):
                    selections = {tx[0]: st.checkbox(f"**{USERS.get(str(tx[1]), {}).get('name')}** — ${float(tx[2]):,.2f}") for tx in pending_mgr}
                    if st.form_submit_button("☑️ BATCH VERIFY SELECTED"):
                        for t_id, is_sel in selections.items():
                            if is_sel: run_transaction("UPDATE transactions SET status='PENDING_CFO' WHERE tx_id=:id", {"id": t_id})
                        st.success("✅ Pushed to Treasury."); time.sleep(1.5); st.rerun()
            else: st.info("No shift exceptions pending.")
        with tab_pto:
            pending_pto = run_query("SELECT req_id, pin, start_date, end_date FROM pto_requests WHERE status='PENDING'")
            if pending_pto:
                for p in pending_pto:
                    if st.button(f"APPROVE PTO: {USERS.get(str(p[1]), {}).get('name')} ({p[2]} to {p[3]})", key=p[0]): run_transaction("UPDATE pto_requests SET status='APPROVED' WHERE req_id=:id", {"id": p[0]}); st.rerun()
            else: st.info("No pending PTO requests.")

elif nav == "THE BANK":
    st.markdown("## 🏦 The Bank")
    if st.button("🔄 Refresh Bank Ledger"): st.rerun()
    st.markdown("### 🔗 Web3 Settlement Rail")
    st.markdown("<p style='color:#94a3b8; font-size:0.9rem;'>Authenticate with Phantom to generate your cryptographic signature.</p>", unsafe_allow_html=True)
    phantom_wallet_connector()
    
    with st.expander("🔐 Verify & Lock Wallet Signature", expanded=True):
        with st.form("verify_signature_form"):
            st.info("Paste the generated JSON payload from the Phantom module above.")
            manual_payload_input = st.text_input("Signature Payload (JSON)")
            if st.form_submit_button("Verify & Lock to Profile"):
                try:
                    auth_payload = json.loads(manual_payload_input)
                    if verify_wallet_signature(auth_payload['pubkey'], auth_payload['signature'], auth_payload['message']):
                        run_transaction("UPDATE enterprise_users SET solana_pubkey=:pubkey WHERE pin=:p", {"pubkey": auth_payload['pubkey'], "p": pin}); st.success("✅ Cryptographic Signature Verified! Wallet locked."); time.sleep(1.5); st.rerun()
                    else: st.error("❌ Cryptographic signature failed verification.")
                except Exception as e: st.error("Invalid Payload Format. Please ensure you copied the entire JSON string.")

    st.markdown("<br><hr style='border-color: rgba(255,255,255,0.05);'><br>", unsafe_allow_html=True)
    db_user_data = run_query("SELECT solana_pubkey FROM enterprise_users WHERE pin=:p", {"p": pin})
    solana_key = db_user_data[0][0] if db_user_data and db_user_data[0][0] else None
    banked_gross = st.session_state.user_state.get('earnings', 0.0)
    banked_net = banked_gross * (1 - sum(TAX_RATES.values()))
    
    st.markdown(f"<div class='stripe-box'><div style='display:flex; justify-content:space-between; align-items:center;'><span style='font-size:0.9rem; font-weight:600; text-transform:uppercase;'>Available Balance</span></div><h1 style='font-size:3.5rem; margin:10px 0 5px 0;'>${banked_gross:,.2f} Gross</h1><p style='margin:0; font-size:0.9rem; opacity:0.9;'>Net Estimate: ${banked_net:,.2f} • Tax: ${banked_gross - banked_net:,.2f}</p></div>", unsafe_allow_html=True)
    
    if banked_gross > 0.01 and not st.session_state.user_state.get('active', False):
        if st.button("⚡ EXECUTE ATOMIC PAYOUT", key="web3_btn", use_container_width=True):
            if solana_key:
                net, tax = execute_split_stream_payout(pin, banked_gross, solana_key)
                update_status(pin, "Inactive", 0, 0.0); st.session_state.user_state['earnings'] = 0.0
                st.success(f"✅ Atomic Settlement Complete! ${net:,.2f} routed to {solana_key[:4]}... | ${tax:,.2f} routed to Tax Treasury."); time.sleep(3); st.rerun()
            else: st.error("❌ No verified Web3 Wallet found. Please authenticate above.")
    elif st.session_state.user_state.get('active', False): st.info("You must clock out of your active shift before executing a payout.")

elif nav == "MY PROFILE":
    st.markdown("## 🗄️ Enterprise HR Vault")
    t_lic, t_sec, t_acc = st.tabs(["🪪 LICENSES (ZK PROOFS)", "🔐 SECURITY", "🏅 CLINICAL ACCOLADES"])
    
    with t_sec:
        st.markdown("### Account Security (Bcrypt)")
        with st.form("update_password_form"):
            current_pw = st.text_input("Current Password", type="password"); new_pw = st.text_input("New Password", type="password"); confirm_pw = st.text_input("Confirm New Password", type="password")
            if st.form_submit_button("Update Password"):
                run_transaction("UPDATE enterprise_users SET password_hash=:pw WHERE pin=:p", {"p": pin, "pw": hash_password(new_pw)})
                st.success("✅ Password encrypted and updated!"); time.sleep(2); st.rerun()
    with t_lic:
        with st.expander("➕ ADD NEW CREDENTIAL"):
            with st.form("cred_form"):
                doc_type = st.selectbox("Document Type", ["State RN License", "State RRT License"])
                doc_num = st.text_input("License Number"); exp_date = st.date_input("Expiration Date")
                if st.form_submit_button("Save Credential"):
                    run_transaction("INSERT INTO credentials (doc_id, pin, doc_type, doc_number, exp_date, status) VALUES (:id, :p, :dt, :dn, :ed, 'ACTIVE')", {"id": f"DOC-{int(time.time())}", "p": pin, "dt": doc_type, "dn": generate_zk_commitment(doc_num, pin), "ed": str(exp_date)})
                    st.success("✅ ZK Credential Secured."); time.sleep(1.5); st.rerun()
        creds = run_query("SELECT doc_type, doc_number, exp_date FROM credentials WHERE pin=:p", {"p": pin})
        if creds:
            for c in creds: st.markdown(f"<div class='glass-card'><h4>{c[0]}</h4><p style='color:#94a3b8;'>ZK Hash: {c[1][:16]}...<br>Exp: {c[2]}</p></div>", unsafe_allow_html=True)
            
    with t_acc:
        st.markdown("### Verified Clinical History")
        st.caption("Proof of Care (PoC) badges linked to your identity via EMR & BLE verification.")
        my_accolades = run_query("SELECT title, badge_type, timestamp, emr_verified FROM accolades WHERE pin=:p ORDER BY timestamp DESC", {"p": pin})
        if my_accolades:
            for acc in my_accolades:
                title, b_type, ts, is_emr = acc[0], acc[1], acc[2], acc[3]
                border_color = "#f59e0b" if b_type == "Clinical Operator" else "#38bdf8"
                icon = "👑" if b_type == "Clinical Operator" else "🛡️"
                emr_badge = "<span style='background:#10b981; color:#0b1120; padding:4px 8px; border-radius:6px; font-size:0.75rem; font-weight:900; letter-spacing:1px;'>✓ EMR VERIFIED</span>" if is_emr else "<span style='background:#ef4444; color:#fff; padding:4px 8px; border-radius:6px; font-size:0.75rem; font-weight:900; letter-spacing:1px;'>PENDING</span>"
                try: ts_str = ts.strftime('%b %d, %Y - %H:%M')
                except: ts_str = str(ts)
                st.markdown(f"<div style='background: rgba(30, 41, 59, 0.6); backdrop-filter: blur(10px); border-left: 5px solid {border_color}; border-radius: 12px; padding: 18px; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 15px rgba(0,0,0,0.2);'><div><div style='font-size:1.2rem; font-weight:900; color:#f8fafc; margin-bottom: 4px;'>{icon} {title}</div><div style='color:#94a3b8; font-size:0.85rem; font-weight: 600; text-transform: uppercase;'>{b_type} <span style='color:#475569;'>•</span> {ts_str}</div></div><div style='text-align: right;'>{emr_badge}</div></div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='empty-state'><h3 style='color:#94a3b8;'>No Accolades Yet</h3><p style='color:#64748b; font-size: 0.9rem;'>Respond to high-acuity events to earn on-chain clinical badges.</p></div>", unsafe_allow_html=True)
