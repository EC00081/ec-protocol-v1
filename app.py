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
import re
from datetime import datetime, date, timedelta
from collections import defaultdict
from streamlit_js_eval import get_geolocation
from sqlalchemy import create_engine, text
import pydeck as pdk
import plotly.express as px
import plotly.graph_objects as go

# --- EXTERNAL LIBRARIES ---
try: 
    from fpdf import FPDF
    PDF_ACTIVE = True
except ImportError: 
    PDF_ACTIVE = False

try: from twilio.rest import Client; TWILIO_ACTIVE = True
except ImportError: TWILIO_ACTIVE = False
try: import nacl.signing; import nacl.encoding; NACL_ACTIVE = True
except ImportError: NACL_ACTIVE = False

# --- GLOBAL CONSTANTS ---
LOCAL_TZ = pytz.timezone('US/Eastern')
GEOFENCE_RADIUS = 150
HOSPITALS = {"Brockton General": {"lat": 42.0875, "lon": -70.9915}, "Remote/Anywhere": {"lat": 0.0, "lon": 0.0}}
OPSEC_PW_EXPIRY_DAYS = 90

def send_sms(to_phone, message_body):
    if TWILIO_ACTIVE and to_phone:
        raw_sid, raw_token, raw_from = os.environ.get("TWILIO_ACCOUNT_SID", ""), os.environ.get("TWILIO_AUTH_TOKEN", ""), os.environ.get("TWILIO_PHONE_NUMBER", "")
        if not raw_sid or not raw_token or not raw_from: return False, "Missing Env Vars."
        try: client = Client(raw_sid.strip(), raw_token.strip()); client.messages.create(body=message_body, from_=raw_from.strip(), to=to_phone); return True, "SMS Dispatched"
        except Exception as e: return False, str(e)
    return False, "Twilio inactive."

# --- CRYPTO & OPSEC ---
def is_strong_password(password):
    if len(password) < 8: return False, "Must be at least 8 characters long."
    if not re.search(r"[A-Z]", password): return False, "Must contain an uppercase letter."
    if not re.search(r"[a-z]", password): return False, "Must contain a lowercase letter."
    if not re.search(r"\d", password): return False, "Must contain a number."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password): return False, "Must contain a special character."
    return True, "Valid"

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
                        const msg = "Authenticate EC Protocol | Nonce: " + Date.now();
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

# --- DATABASE ENGINE WITH VERBOSE ERROR DIAGNOSTICS ---
@st.cache_resource(ttl=60)
def get_db_engine():
    url = os.environ.get("SUPABASE_URL")
    if not url:
        try: url = st.secrets["SUPABASE_URL"]
        except: pass
    if not url: return "URL_MISSING"
    
    if url.startswith("postgres://"): url = url.replace("postgres://", "postgresql://", 1)
    
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS enterprise_users (pin TEXT PRIMARY KEY, email TEXT UNIQUE, password_hash TEXT, name TEXT, role TEXT, dept TEXT, access_level TEXT, hourly_rate NUMERIC, phone TEXT, solana_pubkey TEXT UNIQUE, last_pw_change TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"))
            conn.execute(text("ALTER TABLE enterprise_users ADD COLUMN IF NOT EXISTS last_pw_change TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"))
            conn.commit() 
            
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_user_email ON enterprise_users(email);"))
            conn.commit()

            res = conn.execute(text("SELECT COUNT(*) FROM enterprise_users")).fetchone()
            if res[0] == 0:
                seed_data = [
                    ("1001", "liam@ecprotocol.com", hash_password("password123"), "Liam O'Neil", "RRT", "Respiratory", "Worker", 120.00, "+15551234567"),
                    ("1002", "charles@ecprotocol.com", hash_password("password123"), "Charles Morgan", "RRT", "Respiratory", "Worker", 50.00, None),
                    ("1003", "sarah@ecprotocol.com", hash_password("password123"), "Sarah Jenkins", "Charge RRT", "Respiratory", "Supervisor", 90.00, None),
                    ("1004", "manager@ecprotocol.com", hash_password("password123"), "David Clark", "Manager", "Respiratory", "Manager", 0.00, None),
                    ("9999", "cfo@ecprotocol.com", hash_password("password123"), "CFO VIEW", "Admin", "All", "Admin", 0.00, None)
                ]
                for sd in seed_data: conn.execute(text("INSERT INTO enterprise_users (pin, email, password_hash, name, role, dept, access_level, hourly_rate, phone, last_pw_change) VALUES (:p, :e, :pw, :n, :r, :d, :al, :hr, :ph, NOW() - INTERVAL '100 days') ON CONFLICT DO NOTHING"), {"p": sd[0], "e": sd[1], "pw": sd[2], "n": sd[3], "r": sd[4], "d": sd[5], "al": sd[6], "hr": sd[7], "ph": sd[8]})
                conn.commit()
            
            conn.execute(text("CREATE TABLE IF NOT EXISTS workers (pin text PRIMARY KEY, status text, start_time numeric, earnings numeric, last_active timestamp, lat numeric, lon numeric);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS history (pin text, action text, timestamp timestamp DEFAULT NOW(), amount numeric, note text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS marketplace (shift_id text PRIMARY KEY, poster_pin text, role text, date text, start_time text, end_time text, rate numeric, status text, claimed_by text, escrow_status text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS transactions (tx_id text PRIMARY KEY, pin text, amount numeric, timestamp timestamp DEFAULT NOW(), status text, destination_pubkey text, tx_type text, note text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS schedules (shift_id text PRIMARY KEY, pin text, shift_date text, shift_time text, department text, status text DEFAULT 'SCHEDULED');"))
            
            # --- ACUITY & COMMS UPGRADE ---
            conn.execute(text("CREATE TABLE IF NOT EXISTS unit_census (dept text PRIMARY KEY, total_pts int, high_acuity int, vented_pts int DEFAULT 0, nipvv_pts int DEFAULT 0, last_updated timestamp DEFAULT NOW());"))
            try: conn.execute(text("ALTER TABLE unit_census ADD COLUMN IF NOT EXISTS vented_pts int DEFAULT 0;")); conn.execute(text("ALTER TABLE unit_census ADD COLUMN IF NOT EXISTS nipvv_pts int DEFAULT 0;"))
            except: pass
            
            conn.execute(text("CREATE TABLE IF NOT EXISTS messages (msg_id text PRIMARY KEY, sender_pin text, target_dept text, message text, is_sos boolean DEFAULT FALSE, timestamp timestamp DEFAULT NOW());"))
            try: conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_sos boolean DEFAULT FALSE;"))
            except: pass

            conn.execute(text("CREATE TABLE IF NOT EXISTS hr_onboarding (pin text PRIMARY KEY, w4_filing_status text, w4_allowances int, dd_bank text, dd_acct_last4 text, solana_pubkey text, signed_date timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS pto_requests (req_id text PRIMARY KEY, pin text, start_date text, end_date text, reason text, status text DEFAULT 'PENDING', submitted timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS credentials (doc_id text PRIMARY KEY, pin text, doc_type text, doc_number text, exp_date text, status text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS indoor_tracking (pin text PRIMARY KEY, current_floor text, current_room text, scan_method text, last_seen timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS accolades (acc_id text PRIMARY KEY, pin text, title text, badge_type text, timestamp timestamp DEFAULT NOW(), emr_verified boolean);"))
            conn.commit()
        return engine
    except Exception as e: 
        return f"DB_ERROR: {str(e)}"

def run_query(query, params=None):
    engine = get_db_engine()
    if isinstance(engine, str) or engine is None: return None
    try:
        with engine.connect() as conn: return conn.execute(text(query), params or {}).fetchall()
    except: return None

def run_transaction(query, params=None):
    engine = get_db_engine()
    if isinstance(engine, str) or engine is None: return 0
    try:
        with engine.connect() as conn: 
            result = conn.execute(text(query), params or {})
            conn.commit()
            return result.rowcount
    except: return 0

def load_all_users():
    res = run_query("SELECT pin, email, password_hash, name, role, dept, access_level, hourly_rate, phone, last_pw_change FROM enterprise_users")
    if not res: return {} 
    users_dict = {}
    for r in res: 
        users_dict[str(r[0])] = {
            "pin": str(r[0]), "email": r[1], "password_hash": r[2], "name": r[3], 
            "role": r[4], "dept": r[5], "level": r[6], "rate": float(r[7]), 
            "phone": r[8], "vip": (r[6] in ['Admin', 'Manager']),
            "last_pw_change": r[9]
        }
    return users_dict

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

def calculate_taxes(pin, gross_amount):
    if gross_amount <= 0.0: return 0.0, 0.0, 0.0, 0.0, 0.0
    res = run_query("SELECT SUM(amount) FROM history WHERE pin=:p AND action IN ('CLOCK OUT', 'MANUAL PAYOUT RELEASED') AND EXTRACT(YEAR FROM timestamp) = EXTRACT(YEAR FROM NOW())", {"p": pin})
    ytd_gross = float(res[0][0]) if res and res[0][0] else 0.0
    
    def calculate_federal_bracket(income):
        tax = 0.0
        if income > 191950: tax += (income - 191950) * 0.32; income = 191950
        if income > 100525: tax += (income - 100525) * 0.24; income = 100525
        if income > 47150: tax += (income - 47150) * 0.22; income = 47150
        if income > 11600: tax += (income - 11600) * 0.12; income = 11600
        if income > 0: tax += income * 0.10
        return tax

    fed_tax_before = calculate_federal_bracket(ytd_gross)
    fed_tax_after = calculate_federal_bracket(ytd_gross + gross_amount)
    fed_withholding = fed_tax_after - fed_tax_before
    
    ma_withholding = gross_amount * 0.05
    ss_withholding = gross_amount * 0.062
    med_withholding = gross_amount * 0.0145
    
    total_tax = fed_withholding + ma_withholding + ss_withholding + med_withholding
    return total_tax, fed_withholding, ma_withholding, ss_withholding, med_withholding

def create_paystub_pdf(name, date_str, tx_id, gross, net, tax, dest):
    if not PDF_ACTIVE: return None
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(190, 10, txt="VICENTUS ENTERPRISE - OFFICIAL PAY RECEIPT", ln=True, align='C')
        pdf.set_font("Arial", '', 12)
        pdf.ln(10)
        pdf.cell(100, 10, txt=f"Operator: {name}", ln=True)
        pdf.cell(100, 10, txt=f"Date of Settlement: {date_str}", ln=True)
        pdf.cell(100, 10, txt=f"Ledger Tx ID: {tx_id}", ln=True)
        
        mode = "Solana Web3 Smart Contract" if dest and len(dest) > 30 else "Fiat Direct Deposit"
        pdf.cell(100, 10, txt=f"Routing Method: {mode}", ln=True)
        pdf.cell(100, 10, txt=f"Destination: {dest}", ln=True)
        pdf.ln(10)
        
        pdf.line(10, 80, 200, 80)
        pdf.ln(5)
        pdf.cell(100, 10, txt=f"Gross Pay: ${gross:,.2f}", ln=True)
        pdf.cell(100, 10, txt=f"Progressive Tax Withholding: ${tax:,.2f}", ln=True)
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(100, 10, txt=f"Net Settlement: ${net:,.2f}", ln=True)
        pdf.ln(5)
        pdf.line(10, 115, 200, 115)
        
        pdf.ln(10)
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(190, 10, txt="This is a cryptographically verifiable ledger receipt generated by Vicentus.", ln=True, align='C')
        
        return pdf.output(dest='S').encode('latin-1')
    except Exception as e:
        try: return bytes(pdf.output()) 
        except: return None

def execute_split_stream_payout(pin, gross_amount, user_pubkey):
    TREASURY_PUBKEY = os.environ.get("IRS_TREASURY_WALLET", "Hospital_Tax_Holding_Wallet_Address")
    total_tax, fed, ma, ss, med = calculate_taxes(pin, gross_amount)
    net_payout = gross_amount - total_tax
    tx_base_id = int(time.time())
    dest_pubkey = user_pubkey if user_pubkey else "FIAT_DIRECT_DEPOSIT"
    note_str = f"Gross: {gross_amount} | Tax: {total_tax}"
    
    run_transaction("INSERT INTO transactions (tx_id, pin, amount, status, destination_pubkey, tx_type, note) VALUES (:id, :p, :amt, 'APPROVED', :dest, 'NET_PAY', :note)", {"id": f"TX-NET-{tx_base_id}", "p": pin, "amt": net_payout, "dest": dest_pubkey, "note": note_str})
    run_transaction("INSERT INTO transactions (tx_id, pin, amount, status, destination_pubkey, tx_type) VALUES (:id, :p, :amt, 'APPROVED', :dest, 'TAX_WITHHOLDING')", {"id": f"TX-TAX-{tx_base_id}", "p": pin, "amt": total_tax, "dest": TREASURY_PUBKEY})
    
    log_action(pin, "FUNDS WITHDRAWN", net_payout, f"Settled to {dest_pubkey[:12]}...")
    log_action(pin, "TAX WITHHELD", total_tax, f"Routed to Treasury")
    return net_payout, total_tax

def calculate_shift_differentials(start_timestamp, base_rate):
    start_dt = datetime.fromtimestamp(start_timestamp, tz=LOCAL_TZ)
    end_dt = datetime.now(LOCAL_TZ)
    total_seconds = (end_dt - start_dt).total_seconds()
    if total_seconds <= 0: return 0.0, 0.0, "Invalid Shift"

    base_pay = 0.0; diff_pay = 0.0; notes = set()
    current_dt = start_dt
    
    while current_dt < end_dt:
        minute_base = base_rate / 60.0
        minute_diff = 0.0
        if current_dt.weekday() >= 5: minute_diff += (3.00 / 60.0); notes.add("WKD(+$3)")
        if 15 <= current_dt.hour < 19: minute_diff += (3.00 / 60.0); notes.add("EVE(+$3)")
        elif current_dt.hour >= 19 or current_dt.hour < 7: minute_diff += (5.00 / 60.0); notes.add("NOC(+$5)")
        base_pay += minute_base; diff_pay += minute_diff
        current_dt += timedelta(minutes=1)
        
    return base_pay, diff_pay, " | ".join(notes)

def calculate_fatigue_score(p_pin, target_dept):
    res_hrs = run_query("SELECT amount FROM history WHERE pin=:p AND action='CLOCK OUT' AND timestamp >= NOW() - INTERVAL '14 days'", {"p": p_pin})
    base_rate = float(USERS.get(p_pin, {}).get('rate', 0.1)) if p_pin in USERS else 0.1
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

# --- DIAGNOSTIC ENGINE CHECK ---
engine_status = get_db_engine()
if isinstance(engine_status, str):
    st.markdown("<br><br><h1 style='text-align: center; color: #ef4444;'>🚨 CONNECTION SEVERED</h1>", unsafe_allow_html=True)
    if engine_status == "URL_MISSING":
        st.error("**CRITICAL ERROR:** The `SUPABASE_URL` environment variable is completely missing from Render.")
    else:
        st.error(f"**RAW DATABASE ERROR LOG:**\n\n{engine_status}")
    st.stop()

USERS = load_all_users()

if 'user_state' not in st.session_state: st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0}

if 'pending_opsec_reset' in st.session_state:
    st.markdown("<br><br><h1 style='text-align: center; color: #ef4444;'>SECURITY MANDATE</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #94a3b8;'>Your password has expired or is set to default. Hospital InfoSec protocols require an immediate update.</p><br>", unsafe_allow_html=True)
    with st.container():
        st.markdown("<div class='glass-card' style='max-width: 500px; margin: 0 auto; border-left: 4px solid #ef4444 !important;'>", unsafe_allow_html=True)
        with st.form("opsec_reset_form"):
            new_pass = st.text_input("New Secure Password", type="password")
            confirm_pass = st.text_input("Confirm Password", type="password")
            st.caption("Must be 8+ chars, with upper, lower, number, and special character.")
            if st.form_submit_button("Update & Unlock"):
                if new_pass != confirm_pass: st.error("Passwords do not match.")
                else:
                    is_valid, msg = is_strong_password(new_pass)
                    if not is_valid: st.error(f"Weak Password: {msg}")
                    else:
                        run_transaction("UPDATE enterprise_users SET password_hash=:pw, last_pw_change=NOW() WHERE pin=:p", {"p": st.session_state.pending_opsec_pin, "pw": hash_password(new_pass)})
                        st.success("✅ Password Secured. Rerouting to dashboard...")
                        del st.session_state.pending_opsec_reset
                        del st.session_state.pending_opsec_pin
                        time.sleep(2)
                        st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

if 'logged_in_user' not in st.session_state:
    st.markdown("<br><br><br><br><h1 style='text-align: center; color: #f8fafc; letter-spacing: 4px; font-weight: 900; font-size: 3rem;'>EC PROTOCOL</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #10b981; letter-spacing: 3px; font-weight:600;'>ENTERPRISE HEALTHCARE LOGISTICS v2.2.0</p><br>", unsafe_allow_html=True)
    with st.container():
        if not USERS: st.error("❌ CRITICAL: No user accounts found in the database. Please check Supabase table.")
        st.markdown("<div class='glass-card' style='max-width: 500px; margin: 0 auto;'>", unsafe_allow_html=True)
        login_email = st.text_input("ENTERPRISE EMAIL", placeholder="name@hospital.com")
        login_password = st.text_input("SECURE PASSWORD", type="password", placeholder="••••••••")
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("AUTHENTICATE CONNECTION") and USERS:
            auth_pin = None
            for p, d in USERS.items():
                if d.get("email") == login_email.lower():
                    stored_hash = d.get("password_hash")
                    pw_expired = False
                    if d.get("last_pw_change"):
                        try:
                            last_update = d["last_pw_change"]
                            if isinstance(last_update, str): last_update = datetime.fromisoformat(last_update)
                            if last_update.tzinfo is None: last_update = last_update.replace(tzinfo=pytz.UTC)
                            if (datetime.now(pytz.UTC) - last_update).days >= OPSEC_PW_EXPIRY_DAYS: pw_expired = True
                        except: pass 
                    
                    is_default = (login_password == "password123")
                    
                    if stored_hash and verify_password(login_password, stored_hash): 
                        if is_default or pw_expired:
                            st.session_state.pending_opsec_reset = True
                            st.session_state.pending_opsec_pin = p
                            st.rerun()
                        else: auth_pin = p; break
                        
                    if is_default and not stored_hash: 
                        st.session_state.pending_opsec_reset = True
                        st.session_state.pending_opsec_pin = p
                        st.rerun()
                        
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

# 🚀 NEW: Routing Update to include COMMS
if user['level'] == "Admin": menu_items = ["COMMAND CENTER", "FINANCIAL FORECAST", "APPROVALS", "COMMS"]
elif user['level'] in ["Manager", "Director", "Supervisor"]: menu_items = ["DASHBOARD", "CENSUS & ACUITY", "MARKETPLACE", "SCHEDULE", "THE BANK", "APPROVALS", "COMMS", "MY PROFILE"]
else: menu_items = ["DASHBOARD", "MARKETPLACE", "SCHEDULE", "THE BANK", "COMMS", "MY PROFILE"]

st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)
nav = st.radio("NAVIGATION", menu_items, horizontal=True, label_visibility="collapsed")
st.markdown("<hr style='border-color: rgba(255,255,255,0.05); margin-top: 5px; margin-bottom: 20px;'>", unsafe_allow_html=True)

if nav == "DASHBOARD":
    st.markdown(f"<h2 style='font-weight: 800;'>Status Terminal</h2>", unsafe_allow_html=True)
    st.caption("ℹ️ PILOT MODE: Payouts represent 'Shadow Ledger' metrics. No live USDC is transmitted during the trial.")
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
    
    est_total_tax, _, _, _, _ = calculate_taxes(pin, display_gross)
    c1, c2 = st.columns(2); c1.metric("SHIFT ACCRUAL (Gross)", f"${display_gross:,.2f}"); c2.metric("NET ESTIMATE", f"${display_gross - est_total_tax:,.2f}")
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
                base_pay, diff_pay, diff_str = calculate_shift_differentials(w_start, float(USERS.get(w_pin, {}).get("rate", 0.0)))
                est_gross = float(w[2]) + base_pay + diff_pay
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid #10b981 !important;'><div style='display:flex; justify-content:space-between; align-items:center;'><h4 style='margin:0;'>{w_name}</h4><span style='color:#10b981; font-weight:bold;'>🟢 ON CLOCK ({hrs:.2f} hrs) | Est: ${est_gross:.2f}</span></div></div>", unsafe_allow_html=True)
                if st.button(f"🛑 FORCE CLOCK OUT: {w_name}", key=f"force_out_{w_pin}"):
                    if update_status(w_pin, "Inactive", 0, 0.0, w_lat, w_lon):
                        log_action(w_pin, "CLOCK OUT", base_pay+diff_pay, f"Manager Forced Clock Out" + (f" [{diff_str}]" if diff_pay > 0 else ""))
                        hr_data = run_query("SELECT solana_pubkey FROM enterprise_users WHERE pin=:p", {"p": w_pin})
                        user_pubkey = hr_data[0][0] if hr_data and hr_data[0][0] else None
                        execute_split_stream_payout(w_pin, est_gross, user_pubkey)
                        st.success(f"✅ Successfully clocked out {w_name}."); time.sleep(2); st.rerun()
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
    
    c_data = run_query("SELECT total_pts, high_acuity, last_updated, vented_pts, nipvv_pts FROM unit_census WHERE dept=:d", {"d": user['dept']})
    curr_pts = c_data[0][0] if c_data else 0
    curr_high = c_data[0][1] if c_data else 0
    curr_vent = c_data[0][3] if c_data and len(c_data[0]) > 3 and c_data[0][3] is not None else 0
    curr_nipvv = c_data[0][4] if c_data and len(c_data[0]) > 4 and c_data[0][4] is not None else 0
    
    if user['dept'] == "Respiratory":
        req_staff = math.ceil(curr_vent / 4) + math.ceil(curr_nipvv / 6) + math.ceil(max(0, curr_pts - curr_vent - curr_nipvv) / 10)
    elif user['dept'] == "ICU":
        req_staff = math.ceil(curr_high / 1) + math.ceil(max(0, curr_pts - curr_high) / 2)
    else:
        req_staff = math.ceil(curr_high / 3) + math.ceil(max(0, curr_pts - curr_high) / 6)
        
    actual_staff = sum(1 for r in run_query("SELECT pin FROM workers WHERE status='Active'") if USERS.get(str(r[0]), {}).get('dept') == user['dept']) if run_query("SELECT pin FROM workers WHERE status='Active'") else 0
    variance = actual_staff - req_staff
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Patients", curr_pts)
    col2.metric("Required Staff", req_staff)
    
    if variance < 0:
        col3.metric("Current Staff", actual_staff, f"{variance} (Understaffed)", delta_color="inverse")
        if st.button(f"🚨 BROADCAST SOS FOR {abs(variance)} STAFF"):
            rate = user['rate'] * 1.5 if user['rate'] > 0 else 125.00
            
            # 🚀 NEW: Census SOS Button writes to the COMMS Engine AND sends SMS
            sos_text = f"CRITICAL CENSUS SURGE: {abs(variance)} operators needed in {user['dept']}. Claim in Marketplace."
            run_transaction("INSERT INTO messages (msg_id, sender_pin, target_dept, message, is_sos) VALUES (:id, :p, :d, :m, TRUE)", {"id": f"MSG-{int(time.time()*1000)}", "p": pin, "d": user['dept'], "m": sos_text})
            
            for p, d in USERS.items():
                if d.get('dept') == user['dept'] and d.get('phone'):
                    w_status = run_query("SELECT status FROM workers WHERE pin=:p", {"p": p})
                    if not w_status or w_status[0][0] != 'Active':
                        send_sms(d['phone'], f"VICENTUS ALERT: {sos_text}")
            
            for i in range(abs(variance)):
                new_shift_id = f"SOS-{int(time.time()*1000)}-{i}"
                run_transaction("INSERT INTO marketplace (shift_id, poster_pin, role, date, start_time, end_time, rate, status, escrow_status) VALUES (:id, :p, :r, :d, :s, :e, :rt, 'OPEN', 'PENDING')", {"id": new_shift_id, "p": pin, "r": f"🚨 SOS: {user['dept']}", "d": str(date.today()), "s": "NOW", "e": "END OF SHIFT", "rt": rate})
                lock_escrow_bounty(new_shift_id, rate) 
            st.success("🚨 SOS Broadcasted! Smart Contract Escrow Locked!"); time.sleep(2.5); st.rerun()
    else: 
        col3.metric("Current Staff", actual_staff, f"+{variance} (Safe)", delta_color="normal")
    
    st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
    if user['dept'] == "Respiratory":
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Life Support (Vents)", curr_vent)
        sc2.metric("Non-Invasive (BiPAP/CPAP)", curr_nipvv)
        sc3.metric("Floor Therapy (Standard)", max(0, curr_pts - curr_vent - curr_nipvv))
    elif user['dept'] == "ICU":
        sc1, sc2 = st.columns(2)
        sc1.metric("1:1 Critical Acuity", curr_high)
        sc2.metric("Standard ICU (1:2)", max(0, curr_pts - curr_high))
    
    with st.expander("📝 LIVE BED BOARD (ADMIT/DISCHARGE & ACUITY)", expanded=True):
        st.caption("Manage unit flow. Updates calculate required staffing instantly.")
        with st.form("update_census"):
            new_t = st.number_input("Total Unit Census", min_value=0, value=curr_pts)
            
            if user['dept'] == "Respiratory":
                st.markdown("**Respiratory Specifics**")
                new_vent = st.number_input("Vented Patients", min_value=0, value=curr_vent)
                new_nipvv = st.number_input("Non-Invasive (BiPAP/CPAP)", min_value=0, value=curr_nipvv)
                new_h = new_vent + new_nipvv 
            elif user['dept'] == "ICU":
                st.markdown("**ICU Specifics**")
                new_h = st.number_input("1:1 High Acuity Patients", min_value=0, value=curr_high)
                new_vent = curr_vent
                new_nipvv = curr_nipvv
            else:
                new_h = st.number_input("High Acuity Patients", min_value=0, value=curr_high)
                new_vent = curr_vent
                new_nipvv = curr_nipvv
                
            if st.form_submit_button("Lock In Census"): 
                run_transaction("INSERT INTO unit_census (dept, total_pts, high_acuity, vented_pts, nipvv_pts) VALUES (:d, :t, :h, :v, :n) ON CONFLICT (dept) DO UPDATE SET total_pts=:t, high_acuity=:h, vented_pts=:v, nipvv_pts=:n, last_updated=NOW()", {"d": user['dept'], "t": new_t, "h": new_h, "v": new_vent, "n": new_nipvv})
                st.success("Census and Acuity logged successfully."); time.sleep(1); st.rerun()

elif nav == "MARKETPLACE":
    st.markdown("<h2 style='font-weight:900; margin-bottom:5px;'>⚡ INTERNAL SHIFT MARKETPLACE</h2>", unsafe_allow_html=True)
    if st.button("🔄 Refresh Market"): st.rerun()
    open_shifts = run_query("SELECT shift_id, role, date, start_time, rate, escrow_status FROM marketplace WHERE status='OPEN' ORDER BY date ASC")
    if open_shifts:
        for shift in open_shifts:
            s_id, s_role, s_date, s_time, s_rate, s_escrow = shift[0], shift[1], shift[2], shift[3], float(shift[4]), shift[5]
            est_payout = s_rate * 12; escrow_badge = "<span style='background:#10b981; color:#0b1120; padding:3px 8px; border-radius:4px; font-size:0.75rem; font-weight:bold; margin-left:10px;'>🔒 ESCROW SECURED</span>" if s_escrow == "LOCKED" else ""
            st.markdown(f"<div class='bounty-card'><div style='display:flex; justify-content:space-between; align-items:flex-start;'><div><div style='color:#94a3b8; font-weight:800; text-transform:uppercase; font-size:0.9rem;'>{s_date} <span style='color:#38bdf8;'>| {s_time}</span></div><div style='font-size:1.4rem; font-weight:800; color:#f8fafc; margin-top:5px;'>{s_role}{escrow_badge}</div><div class='bounty-amount'>${est_payout:,.2f}</div></div></div></div>", unsafe_allow_html=True)
            if st.button(f"⚡ CLAIM THIS SHIFT (${est_payout:,.0f})", key=f"claim_{s_id}"):
                rows_updated = run_transaction("UPDATE marketplace SET status='CLAIMED', claimed_by=:p WHERE shift_id=:id AND status='OPEN'", {"p": pin, "id": s_id})
                if rows_updated > 0:
                    run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{s_id}", "p": pin, "d": s_date, "t": s_time, "dept": user['dept']})
                    st.success("✅ Shift Claimed!"); time.sleep(2); st.rerun()
                else:
                    st.error("❌ Shift Already Claimed! Another operator secured this bounty."); time.sleep(2); st.rerun()
    else: st.markdown("<div class='empty-state'><h3>No Surge Bounties Active</h3></div>", unsafe_allow_html=True)

# 🚀 NEW: COMMS MODULE
elif nav == "COMMS":
    st.markdown("## 📡 Secure Comms")
    if st.button("🔄 Refresh Feed"): st.rerun()
    
    if user['level'] in ["Manager", "Director", "Admin", "Supervisor"]: tab_intra, tab_inter, tab_sos = st.tabs([f"🏥 {user['dept']} Channel", "🌍 Hospital-Wide", "🚨 SOS Dispatch"])
    else: tab_intra, tab_inter = st.tabs([f"🏥 {user['dept']} Channel", "🌍 Hospital-Wide"])
    
    with tab_intra:
        with st.form("intra_chat"):
            msg = st.text_input("Send to Department")
            if st.form_submit_button("Send"):
                run_transaction("INSERT INTO messages (msg_id, sender_pin, target_dept, message) VALUES (:id, :p, :d, :m)", {"id": f"MSG-{int(time.time()*1000)}", "p": pin, "d": user['dept'], "m": msg})
                st.rerun()
        
        msgs = run_query("SELECT sender_pin, message, timestamp, is_sos FROM messages WHERE target_dept=:d ORDER BY timestamp DESC LIMIT 50", {"d": user['dept']})
        if msgs:
            for m in msgs:
                sender_name = USERS.get(str(m[0]), {}).get('name', 'Unknown')
                dt_str = m[2].strftime('%H:%M - %b %d') if hasattr(m[2], 'strftime') else str(m[2])
                color = "#ef4444" if m[3] else "#3b82f6"
                bg_color = "rgba(239, 68, 68, 0.1)" if m[3] else "rgba(30, 41, 59, 0.6)"
                st.markdown(f"<div style='background: {bg_color}; border-left: 4px solid {color}; padding: 15px; border-radius: 8px; margin-bottom: 10px;'><div style='display:flex; justify-content:space-between; margin-bottom:5px;'><strong style='color:#f8fafc;'>{sender_name}</strong><span style='color:#94a3b8; font-size:0.8rem;'>{dt_str}</span></div><div style='color:#cbd5e1;'>{m[1]}</div></div>", unsafe_allow_html=True)
        else: st.info("No departmental comms found.")

    with tab_inter:
        with st.form("inter_chat"):
            msg = st.text_input("Send to All Departments")
            if st.form_submit_button("Send"):
                run_transaction("INSERT INTO messages (msg_id, sender_pin, target_dept, message) VALUES (:id, :p, 'All', :m)", {"id": f"MSG-{int(time.time()*1000)}", "p": pin, "m": msg})
                st.rerun()
        
        msgs = run_query("SELECT sender_pin, message, timestamp, is_sos FROM messages WHERE target_dept='All' ORDER BY timestamp DESC LIMIT 50")
        if msgs:
            for m in msgs:
                sender_name = USERS.get(str(m[0]), {}).get('name', 'Unknown')
                dt_str = m[2].strftime('%H:%M - %b %d') if hasattr(m[2], 'strftime') else str(m[2])
                color = "#ef4444" if m[3] else "#10b981"
                bg_color = "rgba(239, 68, 68, 0.1)" if m[3] else "rgba(30, 41, 59, 0.6)"
                st.markdown(f"<div style='background: {bg_color}; border-left: 4px solid {color}; padding: 15px; border-radius: 8px; margin-bottom: 10px;'><div style='display:flex; justify-content:space-between; margin-bottom:5px;'><strong style='color:#f8fafc;'>{sender_name}</strong><span style='color:#94a3b8; font-size:0.8rem;'>{dt_str}</span></div><div style='color:#cbd5e1;'>{m[1]}</div></div>", unsafe_allow_html=True)
        else: st.info("No global comms found.")

    if user['level'] in ["Manager", "Director", "Admin", "Supervisor"]:
        with tab_sos:
            st.markdown("### Broadcast Emergency Alerts")
            st.caption("Push high-priority alerts to the in-app ledger and blast SMS messages to all off-shift personnel.")
            with st.form("sos_form"):
                sos_target = st.selectbox("Target Department", ["All", "Respiratory", "ICU", "Emergency"])
                sos_msg = st.text_area("SOS Message")
                if st.form_submit_button("🚨 TRIGGER SOS DISPATCH"):
                    run_transaction("INSERT INTO messages (msg_id, sender_pin, target_dept, message, is_sos) VALUES (:id, :p, :d, :m, TRUE)", {"id": f"MSG-{int(time.time()*1000)}", "p": pin, "d": sos_target, "m": sos_msg})
                    
                    sms_count = 0
                    for p, u_data in USERS.items():
                        if sos_target in ["All", u_data['dept']] and u_data.get('phone'):
                            w_status = run_query("SELECT status FROM workers WHERE pin=:p", {"p": p})
                            if not w_status or w_status[0][0] != 'Active':
                                send_sms(u_data['phone'], f"VICENTUS SOS: {sos_msg}")
                                sms_count += 1
                                
                    st.success(f"✅ SOS Dispatched! Internal channels updated and SMS routed to {sms_count} off-shift operators.")
                    time.sleep(2.5); st.rerun()

elif nav == "SCHEDULE":
    st.markdown("## 📅 Intelligent Scheduling")
    if st.button("🔄 Refresh Schedule"): st.rerun()
    
    if user['level'] in ["Manager", "Director", "Admin", "Supervisor"]: 
        tab_mine, tab_hist, tab_master, tab_manage, tab_pto = st.tabs(["🙋 MY UPCOMING", "🕰️ WORKED HISTORY", "🏥 MASTER ROSTER", "📝 ASSIGN SHIFTS", "🏝️ REQUEST PTO"])
    else: 
        tab_mine, tab_hist, tab_master, tab_pto = st.tabs(["🙋 MY UPCOMING", "🕰️ WORKED HISTORY", "🏥 MASTER ROSTER", "🏝️ REQUEST PTO"])
        
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
        if user['level'] in ["Manager", "Director", "Admin", "Supervisor"]:
            st.markdown("### 🏥 Master Roster")
            with st.expander("🧠 Run Weekly AI Roster Audit", expanded=False):
                st.caption("Analyze schedule efficiency and aggregate fatigue risk for a specific 7-day window.")
                with st.form("weekly_audit_form"):
                    week_start = st.date_input("Select Week Start Date", value=date.today())
                    if st.form_submit_button("Analyze Week"):
                        st.session_state.audit_week_start = week_start
                        st.rerun()
            
            if 'audit_week_start' in st.session_state:
                ws = st.session_state.audit_week_start
                we = ws + timedelta(days=7)
                st.markdown(f"#### 📊 AI Weekly Audit Report ({ws} to {we - timedelta(days=1)})")
                
                weekly_shifts = run_query("SELECT pin, count(*) FROM schedules WHERE shift_date >= :start AND shift_date < :end AND status='SCHEDULED' GROUP BY pin", {"start": str(ws), "end": str(we)})
                
                if weekly_shifts:
                    for ws_record in weekly_shifts:
                        w_pin = ws_record[0]
                        shift_count = ws_record[1]
                        est_weekly_hrs = shift_count * 12 
                        
                        w_dept = USERS.get(w_pin, {}).get('dept', 'Unknown')
                        w_name = USERS.get(w_pin, {}).get('name', 'Unknown')
                        
                        f_score, f_hrs, f_notes = calculate_fatigue_score(w_pin, w_dept)
                        projected_score = f_score + (est_weekly_hrs * 1.5) 
                        
                        color = "#10b981" 
                        if shift_count > 3 or projected_score > 80: color = "#f59e0b" 
                        if shift_count > 4 or projected_score > 100: color = "#ef4444" 
                        
                        risk_lvl = "OPTIMAL" if color == "#10b981" else "ELEVATED RISK" if color == "#f59e0b" else "CRITICAL BURNOUT RISK"
                        
                        st.markdown(f"<div class='glass-card' style='border-left: 4px solid {color} !important;'><div style='display:flex; justify-content:space-between; align-items:center;'><div><strong style='font-size:1.1rem; color:#f8fafc;'>{w_name}</strong> | <span style='color:{color}; font-weight:bold;'>{risk_lvl}</span><br><span style='color:#94a3b8; font-size:0.9rem;'>Scheduled this week: {shift_count} shifts (~{est_weekly_hrs} hrs)</span><br><span style='color:#38bdf8; font-size:0.8rem;'>Base Fatigue: {f_score:.1f} | Projected: {projected_score:.1f} | Notes: {f_notes if f_notes else 'None'}</span></div></div></div>", unsafe_allow_html=True)
                else:
                    st.info("No shifts scheduled for this week.")
                
                if st.button("Clear Audit Report"):
                    del st.session_state.audit_week_start
                    st.rerun()
                st.markdown("<hr style='border-color: rgba(255,255,255,0.05);'>", unsafe_allow_html=True)

        all_s = run_query("SELECT shift_id, pin, shift_date, shift_time, department, COALESCE(status, 'SCHEDULED') FROM schedules WHERE shift_date >= :today ORDER BY shift_date ASC, shift_time ASC", {"today": str(date.today())})
        if all_s:
            groups = defaultdict(list)
            for s in all_s: groups[s[2]].append(s)
            for date_key in sorted(groups.keys()):
                st.markdown(f"<div class='sched-date-header'>🗓️ {date_key}</div>", unsafe_allow_html=True)
                for s in groups[date_key]:
                    owner = USERS.get(str(s[1]), {}).get('name', f"User {s[1]}"); lbl = "<span style='color:#ff453a; margin-left:10px;'>🚨 SICK</span>" if s[5]=="CALL_OUT" else "<span style='color:#f59e0b; margin-left:10px;'>🔄 TRADING</span>" if s[5]=="MARKETPLACE" else ""
                    st.markdown(f"<div class='sched-row'><div class='sched-time'>{s[3]}</div><div style='flex-grow: 1; padding-left: 15px;'><span class='sched-name'>{'⭐ ' if str(s[1])==pin else ''}{owner}</span> {lbl}</div></div>", unsafe_allow_html=True)
                    if user['level'] in ["Manager", "Director", "Admin", "Supervisor"]:
                        m1, m2 = st.columns(2)
                        if m1.button("❌ Remove", key=f"del_{s[0]}", use_container_width=True):
                            run_transaction("DELETE FROM schedules WHERE shift_id=:id", {"id": s[0]}); st.rerun()
                        if m2.button("📋 Duplicate", key=f"dup_{s[0]}", use_container_width=True):
                            run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:nid, :p, :d, :t, :dept, 'SCHEDULED')", {"nid": f"SCH-{int(time.time()*1000)}{random.randint(10,99)}", "p": s[1], "d": s[2], "t": s[3], "dept": s[4]}); st.rerun()
        else: st.info("Master calendar is empty for upcoming dates.")

    if user['level'] in ["Manager", "Director", "Admin", "Supervisor"]:
        with tab_manage:
            st.markdown("### 🛠️ Shift Assignment Desk")
            dispatch_mode = st.radio("Select Dispatch Mode", ["Manual Input & AI Analyzer", "AI Auto-Dispatch (Find Best Provider)"], horizontal=True)
            st.markdown("<hr style='border-color: rgba(255,255,255,0.05);'>", unsafe_allow_html=True)
            
            if dispatch_mode == "Manual Input & AI Analyzer":
                with st.form("manual_assign_form"):
                    all_staff = {p: d for p, d in USERS.items() if d['level'] in ['Worker', 'Supervisor']}
                    staff_options = [f"{d['name']} (PIN: {p})" for p, d in all_staff.items()]
                    
                    sel_staff = st.selectbox("Select Provider", staff_options)
                    c1, c2, c3 = st.columns(3)
                    m_date = c1.date_input("Shift Date")
                    m_time = c2.text_input("Time", value="0700-1900")
                    m_dept = c3.selectbox("Department", ["Respiratory", "ICU", "Emergency", "Floor"])
                    
                    st.caption("Optional: Analyze this provider's fatigue and equity score before finalizing the schedule.")
                    col_a, col_b = st.columns(2)
                    analyze_btn = col_a.form_submit_button("🧠 Analyze Provider Efficiency")
                    assign_btn = col_b.form_submit_button("⚡ Force Assign Shift")
                    
                if analyze_btn:
                    target_pin = sel_staff.split("PIN: ")[1].replace(")", "")
                    f_score, f_hrs, f_notes = calculate_fatigue_score(target_pin, m_dept)
                    color = "#10b981" if f_score < 72 else "#f59e0b"
                    if f_score >= 100: color = "#ef4444"
                    st.markdown(f"<div class='glass-card' style='border-left: 4px solid {color} !important;'><h4>AI Efficiency Report: {sel_staff.split(' ')[0]}</h4><p><b>Engine Fatigue Score:</b> {f_score:.1f}<br><b>Trailing 14-Day Hours:</b> {f_hrs:.1f}<br><b>Risk Factors / Equity Notes:</b> {f_notes if f_notes else 'None (Optimal Candidate)'}</p></div>", unsafe_allow_html=True)
                    
                if assign_btn:
                    target_pin = sel_staff.split("PIN: ")[1].replace(")", "")
                    run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{int(time.time()*1000)}", "p": target_pin, "d": str(m_date), "t": m_time, "dept": m_dept})
                    st.success(f"✅ Shift securely added to {sel_staff.split(' ')[0]}'s master schedule."); time.sleep(1.5); st.rerun()

            else:
                st.caption("AI prioritizes Equality (Weekend Balance) and Fatigue Management over Seniority to find the optimal provider for an empty slot.")
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

    with tab_pto:
        st.markdown("### Request Paid Time Off")
        with st.form("pto_form"):
            c1, c2 = st.columns(2)
            start_d = c1.date_input("Start Date")
            end_d = c2.date_input("End Date")
            reason = st.text_input("Reason")
            if st.form_submit_button("Submit PTO Request"):
                run_transaction("INSERT INTO pto_requests (req_id, pin, start_date, end_date, reason) VALUES (:id, :p, :sd, :ed, :r)", {"id": f"PTO-{int(time.time()*1000)}", "p": pin, "sd": str(start_d), "ed": str(end_d), "r": reason})
                st.success("✅ PTO Request sent to management.")
                time.sleep(1.5); st.rerun()

elif nav == "APPROVALS":
    st.markdown("## 📥 Approval Gateway")
    st.caption("Review Timesheet Exceptions and Time Off Requests.")
    if st.button("🔄 Refresh Queue"): st.rerun()
    
    if user['level'] == "Admin":
        pending_cfo = run_query("SELECT tx_id, pin, amount, timestamp, note FROM transactions WHERE status='PENDING_CFO' ORDER BY timestamp ASC")
        if pending_cfo:
            for tx in pending_cfo:
                tx_note = tx[4] if len(tx) > 4 and tx[4] else "No context provided"
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid #3b82f6 !important;'><h4>{USERS.get(str(tx[1]), {}).get('name', 'Unknown')} | ${float(tx[2]):,.2f}</h4><p style='color:#94a3b8; font-size:0.9rem;'>{tx_note}</p></div>", unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                if c1.button("💸 RELEASE FUNDS", key=f"cfo_{tx[0]}"): 
                    updated = run_transaction("UPDATE transactions SET status='APPROVED' WHERE tx_id=:id AND status='PENDING_CFO'", {"id": tx[0]})
                    if updated: 
                        log_action(tx[1], "MANUAL PAYOUT RELEASED", tx[2], f"Approved Exception: {tx_note}")
                        st.success("Approved!"); st.rerun()
                    else: st.error("Transaction state changed. Please refresh."); time.sleep(2); st.rerun()
                if c2.button("❌ DENY", key=f"den_{tx[0]}"): 
                    run_transaction("UPDATE transactions SET status='DENIED' WHERE tx_id=:id", {"id": tx[0]}); st.rerun()
        else: st.info("No funds pending authorization.")
    else:
        tab_fin, tab_pto = st.tabs(["🕒 VERIFY HOURS", "🏝️ PTO REQUESTS"])
        
        with tab_fin:
            pending_mgr = run_query("SELECT tx_id, pin, amount, timestamp, note FROM transactions WHERE status='PENDING_MGR' ORDER BY timestamp ASC")
            if pending_mgr:
                with st.form("batch_verify_form"):
                    selections = {}
                    for tx in pending_mgr:
                        u_name = USERS.get(str(tx[1]), {}).get('name', 'Unknown')
                        tx_note = tx[4] if len(tx) > 4 and tx[4] else "No recent shift context."
                        checkbox_label = f"**{u_name}** — ${float(tx[2]):,.2f} | (Context: {tx_note})"
                        selections[tx[0]] = st.checkbox(checkbox_label)
                        
                    if st.form_submit_button("☑️ BATCH VERIFY SELECTED"):
                        for t_id, is_sel in selections.items():
                            if is_sel: run_transaction("UPDATE transactions SET status='PENDING_CFO' WHERE tx_id=:id AND status='PENDING_MGR'", {"id": t_id})
                        st.success("✅ Pushed to Treasury."); time.sleep(1.5); st.rerun()
            else: st.info("No shift exceptions pending.")
            
        with tab_pto:
            pending_pto = run_query("SELECT req_id, pin, start_date, end_date, reason FROM pto_requests WHERE status='PENDING'")
            if pending_pto:
                for p in pending_pto:
                    reason = p[4] if len(p) > 4 and p[4] else "No reason given."
                    if st.button(f"APPROVE PTO: {USERS.get(str(p[1]), {}).get('name')} ({p[2]} to {p[3]}) | Reason: {reason}", key=p[0]): 
                        run_transaction("UPDATE pto_requests SET status='APPROVED' WHERE req_id=:id", {"id": p[0]}); st.rerun()
            else: st.info("No pending PTO requests.")

elif nav == "THE BANK":
    st.markdown("## 🏦 The Bank")
    st.caption("ℹ️ SHADOW LEDGER MODE: Payouts are simulated for pilot metrics tracking. No live Web3 routing occurs.")
    if st.button("🔄 Refresh Bank Ledger"): st.rerun()
    st.markdown("### 🔗 Web3 Settlement Rail")
    st.markdown("<p style='color:#94a3b8; font-size:0.9rem;'>Authenticate with Phantom to generate your cryptographic signature. <br><b>Mobile Users:</b> You must open this dashboard inside the Phantom App browser.</p>", unsafe_allow_html=True)
    phantom_wallet_connector()
    
    with st.expander("🔐 Verify & Lock Wallet Signature", expanded=True):
        with st.form("verify_signature_form"):
            st.info("Paste the generated JSON payload from the Phantom module above.")
            manual_payload_input = st.text_input("Signature Payload (JSON)")
            if st.form_submit_button("Verify & Lock to Profile"):
                try:
                    auth_payload = json.loads(manual_payload_input)
                    msg_text = auth_payload['message']
                    if msg_text.startswith("Authenticate EC Protocol | Nonce: "):
                        msg_time = int(msg_text.split("Nonce: ")[1])
                        current_time = int(time.time() * 1000)
                        if (current_time - msg_time) < 300000: # 5 Minute expiry
                            if verify_wallet_signature(auth_payload['pubkey'], auth_payload['signature'], msg_text):
                                run_transaction("UPDATE enterprise_users SET solana_pubkey=:pubkey WHERE pin=:p", {"pubkey": auth_payload['pubkey'], "p": pin})
                                st.success("✅ Cryptographic Signature Verified! Wallet locked."); time.sleep(1.5); st.rerun()
                            else: st.error("❌ Cryptographic signature failed mathematical verification.")
                        else: st.error("❌ Signature expired. Please click the Phantom button to generate a new Nonce.")
                    else: st.error("❌ Invalid Payload format.")
                except Exception as e: st.error("Invalid Payload Format. Please ensure you copied the entire JSON string.")

    st.markdown("<br><hr style='border-color: rgba(255,255,255,0.05);'><br>", unsafe_allow_html=True)
    db_user_data = run_query("SELECT solana_pubkey FROM enterprise_users WHERE pin=:p", {"p": pin})
    solana_key = db_user_data[0][0] if db_user_data and db_user_data[0][0] else None
    
    banked_gross = st.session_state.user_state.get('earnings', 0.0)
    total_tax, fed_tx, ma_tx, ss_tx, med_tx = calculate_taxes(pin, banked_gross)
    banked_net = banked_gross - total_tax
    
    st.markdown(f"<div class='stripe-box'><div style='display:flex; justify-content:space-between; align-items:center;'><span style='font-size:0.9rem; font-weight:600; text-transform:uppercase;'>Available Balance</span></div><h1 style='font-size:3.5rem; margin:10px 0 5px 0;'>${banked_gross:,.2f} Gross</h1><p style='margin:0; font-size:0.9rem; opacity:0.9;'>Net Estimate: ${banked_net:,.2f} • Total Tax: ${total_tax:,.2f}</p></div>", unsafe_allow_html=True)
    st.caption("Federal taxes are mathematically adjusted via 2024 progressive brackets based on your Year-To-Date (YTD) cumulative earnings.")
    
    if banked_gross > 0.01 and not st.session_state.user_state.get('active', False):
        if st.button("⚡ EXECUTE PAYOUT (Web3 / Fiat Fallback)", key="web3_btn", use_container_width=True, disabled=st.session_state.get('payout_processing', False)):
            st.session_state['payout_processing'] = True
            net, tax = execute_split_stream_payout(pin, banked_gross, solana_key)
            update_status(pin, "Inactive", 0, 0.0)
            st.session_state.user_state['earnings'] = 0.0
            
            dest_txt = f"Wallet {solana_key[:4]}..." if solana_key else "Fiat Direct Deposit"
            st.success(f"✅ Settlement Complete! ${net:,.2f} routed to {dest_txt} | ${tax:,.2f} routed to Tax Treasury.")
            time.sleep(2.5) 
            st.session_state['payout_processing'] = False
            st.rerun()
    elif st.session_state.user_state.get('active', False): st.info("You must clock out of your active shift before executing a payout.")

    st.markdown("<hr style='border-color: rgba(255,255,255,0.05);'>", unsafe_allow_html=True)
    with st.expander("🛠️ Submit Exception / Overtime Hours"):
        st.caption("Submit extra hours worked outside your normal schedule for manager approval.")
        with st.form("exception_form"):
            exc_date = st.date_input("Date of Shift")
            exc_hours = st.number_input("Additional Hours", min_value=0.5, step=0.5)
            exc_reason = st.text_input("Reason (e.g., 'Stayed late for Code Blue')")
            if st.form_submit_button("Submit to Manager"):
                amt = exc_hours * user['rate']
                tx_id = f"EXC-{int(time.time()*1000)}"
                note_str = f"{exc_date}: {exc_hours}hrs - {exc_reason}"
                run_transaction("INSERT INTO transactions (tx_id, pin, amount, status, tx_type, note) VALUES (:id, :p, :amt, 'PENDING_MGR', 'EXCEPTION', :note)", {"id": tx_id, "p": pin, "amt": amt, "note": note_str})
                st.success("✅ Exception submitted to management.")
                time.sleep(1.5); st.rerun()

    st.markdown("### 📄 Ledger & Pay Stubs")
    st.caption("Download official PDF receipts for all Web3 and Fiat payouts.")
    
    paystubs = run_query("SELECT tx_id, amount, timestamp, destination_pubkey, note FROM transactions WHERE pin=:p AND tx_type='NET_PAY' ORDER BY timestamp DESC", {"p": pin})
    if paystubs:
        for stub in paystubs:
            tx_id = stub[0]
            net_amt = float(stub[1])
            dt_str = stub[2].strftime("%Y-%m-%d %H:%M") if hasattr(stub[2], 'strftime') else str(stub[2])
            dest = stub[3]
            note = stub[4]
            
            gross_amt = net_amt
            tax_amt = 0.0
            if note and "Gross:" in note:
                try:
                    gross_amt = float(note.split("Gross: ")[1].split(" |")[0])
                    tax_amt = float(note.split("Tax: ")[1])
                except: pass
            
            with st.expander(f"Payout: {dt_str} | ${net_amt:,.2f} Net"):
                st.write(f"**Transaction ID:** `{tx_id}`")
                st.write(f"**Destination:** `{dest}`")
                st.write(f"**Gross:** ${gross_amt:,.2f} | **Tax:** ${tax_amt:,.2f} | **Net:** ${net_amt:,.2f}")
                
                if PDF_ACTIVE:
                    pdf_bytes = create_paystub_pdf(user['name'], dt_str, tx_id, gross_amt, net_amt, tax_amt, dest)
                    if pdf_bytes:
                        st.download_button(label="📄 Download Official PDF Receipt", data=pdf_bytes, file_name=f"Paystub_{tx_id}.pdf", mime="application/pdf", key=f"pdf_{tx_id}")
                else:
                    st.info("PDF Generation not active. Please ensure 'fpdf' is in requirements.txt")
    else:
        st.info("No prior settlements found on ledger.")

elif nav == "MY PROFILE":
    st.markdown("## 🗄️ Enterprise HR Vault")
    t_lic, t_sec, t_acc = st.tabs(["🪪 LICENSES (ZK PROOFS)", "🔐 SECURITY", "🏅 CLINICAL ACCOLADES"])
    
    with t_sec:
        st.markdown("### Account Security (Bcrypt)")
        st.info(f"Enterprise mandates password rotation every {OPSEC_PW_EXPIRY_DAYS} days.")
        
        with st.form("update_password_form"):
            current_pw = st.text_input("Current Password", type="password"); new_pw = st.text_input("New Secure Password", type="password"); confirm_pw = st.text_input("Confirm New Password", type="password")
            st.caption("Must be 8+ chars, with upper, lower, number, and special character.")
            if st.form_submit_button("Update Password"):
                db_pw_res = run_query("SELECT password_hash FROM enterprise_users WHERE pin=:p", {"p": pin})
                if db_pw_res and verify_password(current_pw, db_pw_res[0][0]):
                    if new_pw != confirm_pw: st.error("❌ Passwords do not match.")
                    else:
                        is_valid, msg = is_strong_password(new_pw)
                        if not is_valid: st.error(f"❌ Weak Password: {msg}")
                        else:
                            run_transaction("UPDATE enterprise_users SET password_hash=:pw, last_pw_change=NOW() WHERE pin=:p", {"p": pin, "pw": hash_password(new_pw)})
                            st.success("✅ Password encrypted and updated! Clock reset."); time.sleep(2); st.rerun()
                else: st.error("❌ Current password incorrect.")
                
    with t_lic:
        with st.expander("➕ ADD NEW CREDENTIAL"):
            with st.form("cred_form"):
                doc_type = st.selectbox("Document Type", ["State RN License", "State RRT License", "ACLS Provider", "BLS Provider"])
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
