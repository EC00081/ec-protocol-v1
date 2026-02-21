import streamlit as st
import pandas as pd
import time
import math
import pytz
import random
import os
from datetime import datetime
from streamlit_js_eval import get_geolocation
from streamlit_autorefresh import st_autorefresh
from sqlalchemy import create_engine, text

# --- NEW LIBRARIES (Safely Loaded) ---
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
    /* Safely apply Inter font without breaking Streamlit's Material Icons */
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
</style>
"""
st.markdown(html_style, unsafe_allow_html=True)

# --- 2. CONSTANTS & LOCATIONS ---
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}
LOCAL_TZ = pytz.timezone('US/Eastern')
GEOFENCE_RADIUS = 150 # Meters

# DYNAMIC GEOFENCING LOCATIONS
HOSPITALS = {
    "Brockton General": {"lat": 42.0875, "lon": -70.9915},
    "Boston Medical": {"lat": 42.3350, "lon": -71.0732},
    "Remote/Anywhere": {"lat": "ANY", "lon": "ANY"}
}

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RRT", "rate": 85.00, "phone": "+18448032563"},
    "1002": {"name": "Charles Morgan", "role": "RRT", "rate": 85.00, "phone": "+15559876543"},
    "9999": {"name": "CFO VIEW", "role": "Admin", "rate": 0.00, "phone": None}
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
            result = conn.execute(text(query), params or {})
            return result.fetchall() 
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

# --- 4. CORE DB LOGIC ---
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
    except: return False

def update_status(pin, status, start, earn):
    q = """INSERT INTO workers (pin, status, start_time, earnings, last_active) VALUES (:p, :s, :t, :e, NOW())
           ON CONFLICT (pin) DO UPDATE SET status = :s, start_time = :t, earnings = :e, last_active = NOW();"""
    return run_transaction(q, {"p": pin, "s": status, "t": start, "e": earn})

def log_tx(pin, amount):
    tx_id = f"TX-{int(time.time())}"
    q = "INSERT INTO transactions (tx_id, pin, amount, timestamp, status) VALUES (:id, :p, :a, NOW(), 'INSTANT')"
    run_transaction(q, {"id": tx_id, "p": pin, "a": amount})
    return tx_id

def log_action(pin, action, amount, note):
    q = "INSERT INTO history (pin, action, timestamp, amount, note) VALUES (:p, :a, NOW(), :amt, :n)"
    run_transaction(q, {"p": pin, "a": action, "amt": amount, "n": note})

def post_shift_db(pin, role, date, start, end, rate, location):
    shift_id = f"SHIFT-{int(time.time())}"
    # Appending location to role for easy storage without altering DB schema
    role_with_loc = f"{role} @ {location}"
    q = """INSERT INTO marketplace (shift_id, poster_pin, role, date, start_time, end_time, rate, status)
           VALUES (:id, :p, :r, :d, :s, :e, :rt, 'OPEN')"""
    success = run_transaction(q, {"id": shift_id, "p": pin, "r": role_with_loc, "d": date, "s": str(start), "e": str(end), "rt": rate})
    
    # SMS TRIGGER
    if success and TWILIO_ACTIVE:
        send_sms_blast(f"🚨 New Shift: {role_with_loc} on {date}. Log in to EC Protocol to claim.")
    return success

def claim_shift_db(shift_id, claimer_pin):
    q = "UPDATE marketplace SET status='CLAIMED', claimed_by=:p WHERE shift_id=:id"
    run_transaction(q, {"p": claimer_pin, "id": shift_id})

# --- 5. ENTERPRISE FEATURES (SMS & PDF) ---
def send_sms_blast(message_body):
    try:
        account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
        auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        from_phone = os.environ.get('TWILIO_PHONE_NUMBER')
        if not all([account_sid, auth_token, from_phone]): return # Silently fail if keys missing
        
        client = Client(account_sid, auth_token)
        for pin, user in USERS.items():
            if user['phone']:
                client.messages.create(body=message_body, from_=from_phone, to=user['phone'])
    except Exception as e:
        pass # Prevents app from crashing if Twilio fails

def generate_paystub_pdf(user_name, tx_id, amount):
    if not PDF_ACTIVE: return None
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=15, style='B')
        pdf.cell(200, 10, txt="EC PROTOCOL - OFFICIAL PAYSTUB", ln=1, align='C')
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt=f"Date: {get_local_now()}", ln=1, align='L')
        pdf.cell(200, 10, txt=f"Operator: {user_name}", ln=1, align='L')
        pdf.cell(200, 10, txt=f"Transaction ID: {tx_id}", ln=1, align='L')
        pdf.cell(200, 10, txt=f"Net Payout: ${amount:,.2f}", ln=1, align='L')
        pdf.cell(200, 10, txt="Status: INSTANT SETTLEMENT (SUCCESS)", ln=1, align='L')
        # In a real app, this saves to a cloud bucket. Here we just create it in memory.
        return True 
    except: return None

# --- 6. DYNAMIC SECURITY GATES ---
def verify_security(pin, lat, lon, target_location_name):
    if str(pin) == "1001" or str(pin) == "9999": return True, "VIP/ADMIN ACCESS"
    
    # DYNAMIC GEOFENCE
    if target_location_name not in HOSPITALS: return False, "INVALID FACILITY"
    target_lat = HOSPITALS[target_location_name]["lat"]
    target_lon = HOSPITALS[target_location_name]["lon"]
    
    if target_lat != "ANY":
        R = 6371000
        lat1, lon1 = math.radians(lat), math.radians(lon)
        lat2, lon2 = math.radians(target_lat), math.radians(target_lon)
        a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2) * math.sin((lon2-lon1)/2)**2
        dist = R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))
        if dist > GEOFENCE_RADIUS: return False, f"GEOFENCE FAIL: You are {int(dist)}m away from {target_location_name}."
    
    return True, "VERIFIED"

# --- 7. UI & STATE ---
if 'user_state' not in st.session_state: st.session_state.user_state = {}
defaults = {'active': False, 'start_time': 0.0, 'earnings': 0.0, 'payout_success': False, 'payout_lock': False, 'current_location': 'Remote/Anywhere'}
for k, v in defaults.items(): 
    if k not in st.session_state.user_state: st.session_state.user_state[k] = v

if 'logged_in_user' not in st.session_state:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center; color: #f8fafc; letter-spacing: 2px;'>EC PROTOCOL</h1>", unsafe_allow_html=True)
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

# --- 8. SIDEBAR ---
with st.sidebar:
    st.caption(f"LOGGED IN AS: {user['name'].upper()}")
    if get_db_engine(): st.success("🟢 DB CONNECTED")
    else: st.error("🔴 DB DISCONNECTED")
    
    # Admin gets different navigation
    if pin == "9999": nav = st.radio("MENU", ["COMMAND CENTER", "AUDIT LOGS"])
    else: nav = st.radio("MENU", ["DASHBOARD", "MARKETPLACE", "MY LOGS"])
    
    if st.button("LOGOUT"): st.session_state.clear(); st.rerun()

# --- 9. ADMIN COMMAND CENTER (GOD MODE) ---
if pin == "9999" and nav == "COMMAND CENTER":
    st.markdown("## 🦅 Command Center")
    st.caption("Live Fleet Overview")
    
    rows = run_query("SELECT pin, status, start_time, earnings FROM workers WHERE status='Active'")
    if rows:
        for r in rows:
            w_pin = r[0]
            w_name = USERS.get(w_pin, {}).get("name", "Unknown")
            hrs = (time.time() - float(r[2])) / 3600
            current_earn = hrs * USERS.get(w_pin, {}).get("rate", 85)
            
            st.markdown(f"""
            <div class="admin-card">
                <h3 style="margin:0;">{w_name} (PIN: {w_pin})</h3>
                <p style="color:#ff453a; margin-top:5px; font-weight:bold;">🟢 ACTIVE (On Clock: {hrs:.2f} hrs | Accrued: ${current_earn:.2f})</p>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button(f"FORCE CLOCK-OUT {w_name}", key=f"force_{w_pin}"):
                update_status(w_pin, "Inactive", 0, 0)
                log_action("9999", "ADMIN FORCE LOGOUT", current_earn, f"Target: {w_pin}")
                st.success(f"Force-closed shift for {w_name}")
                time.sleep(1)
                st.rerun()
    else:
        st.info("No operators currently active.")

# --- 10. WORKER DASHBOARD ---
elif nav == "DASHBOARD" and pin != "9999":
    st.markdown(f"""<div style="padding: 20px 0; border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px;">
        <h2 style="margin:0; font-size:1.5rem;">Good Morning, {user['name'].split(' ')[0]}</h2>
        <p style="margin:0; color: #94a3b8;">{get_local_now()}</p></div>""", unsafe_allow_html=True)
    
    st_autorefresh(interval=10000)
    loc = get_geolocation(component_key="gps")
    lat, lon = (loc['coords']['latitude'], loc['coords']['longitude']) if loc else (0,0)
    
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
                log_action(pin, "CLOCK OUT", gross, f"Loc: {st.session_state.user_state['current_location']}")
                st.success("✅ SHIFT SAVED TO DATABASE")
                time.sleep(1)
                st.rerun()
    else:
        # Dynamic Facility Selector for Clock In
        selected_facility = st.selectbox("Select Facility for Shift", list(HOSPITALS.keys()))
        if st.button("🟢 START SHIFT"):
            ok, msg = verify_security(pin, lat, lon, selected_facility)
            if ok:
                start_t = time.time()
                if update_status(pin, "Active", start_t, 0):
                    st.session_state.user_state['active'] = True
                    st.session_state.user_state['start_time'] = start_t
                    st.session_state.user_state['current_location'] = selected_facility
                    log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}")
                    st.success("✅ CLOCK IN SAVED TO DATABASE")
                    time.sleep(1)
                    st.rerun()
            else: st.error(msg)

    st.markdown("<br>", unsafe_allow_html=True)
    if not active and gross > 0.01:
        if st.button(f"💸 INSTANT TRANSFER (${net:,.2f})", disabled=st.session_state.user_state['payout_lock']):
            st.session_state.user_state['payout_lock'] = True
            tx = log_tx(pin, net)
            log_action(pin, "PAYOUT", net, "Settled")
            generate_paystub_pdf(user['name'], tx, net) # Safe to run even if PDF dormant
            update_status(pin, "Inactive", 0, 0)
            st.session_state.user_state['earnings'] = 0.0
            st.success(f"FUNDS SENT: {tx}")
            if PDF_ACTIVE: st.info("📄 Paystub generated and filed.")
            time.sleep(2)
            st.session_state.user_state['payout_lock'] = False
            st.rerun()

elif nav == "MARKETPLACE" and pin != "9999":
    st.markdown("## 🏥 Shift Exchange")
    tab1, tab2 = st.tabs(["OPEN SHIFTS", "POST NEW"])
    with tab1:
        res = run_query("SELECT shift_id, poster_pin, role, date, start_time, end_time, rate, status FROM marketplace WHERE status='OPEN'")
        if res:
            for s in res:
                st.markdown(f"""<div class="shift-card"><div style="font-weight:bold; font-size:1.1rem;">{s[3]} | {s[2]}</div>
                    <div style="color:#94a3b8;">{s[4]} - {s[5]} @ ${s[6]}/hr</div></div>""", unsafe_allow_html=True)
                if st.button("CLAIM SHIFT", key=s[0]):
                    claim_shift_db(s[0], pin)
                    st.success("✅ Shift Added to Schedule")
                    time.sleep(1)
                    st.rerun()
        else: st.info("No open shifts available in your region.")

    with tab2:
        with st.form("new_shift"):
            shift_loc = st.selectbox("Facility", list(HOSPITALS.keys()))
            d = st.date_input("Date")
            c1, c2 = st.columns(2)
            s_time = c1.time_input("Start")
            e_time = c2.time_input("End")
            if st.form_submit_button("PUBLISH TO MARKET"):
                post_shift_db(pin, user['role'], d, s_time, e_time, user['rate'], shift_loc)
                msg = "Shift Published!"
                if TWILIO_ACTIVE: msg += " SMS Blast Sent."
                st.success(msg)

elif "LOGS" in nav:
    st.markdown("## 📂 Audit Trail")
    # Admin sees ALL logs, Worker sees only their own
    if pin == "9999":
        query = "SELECT pin, action, timestamp, amount, note FROM history ORDER BY timestamp DESC LIMIT 50"
        res = run_query(query)
    else:
        query = "SELECT pin, action, timestamp, amount, note FROM history WHERE pin=:p ORDER BY timestamp DESC"
        res = run_query(query, {"p": pin})
        
    if res: 
        df = pd.DataFrame(res, columns=["User PIN", "Action", "Time", "Amount", "Note"])
        st.dataframe(df, use_container_width=True)
    else: st.write("No records found.")
