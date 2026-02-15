import streamlit as st
import pandas as pd
import time
import math
import hashlib
import requests
from datetime import datetime, timedelta
from streamlit_js_eval import get_geolocation
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_autorefresh import st_autorefresh

# --- 1. PREMIUM UI CONFIGURATION ---
st.set_page_config(page_title="EC Enterprise", page_icon="🛡️", layout="centered")

# $100M APP STYLING (GLASSMORPHISM & ANIMATIONS)
st.markdown("""
    <style>
    /* HIDE DEFAULT STREAMLIT UI */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* GLOBAL THEME */
    .stApp {
        background: radial-gradient(circle at 50% -20%, #1c2331, #0E1117);
        color: #FFFFFF;
        font-family: 'Inter', -apple-system, sans-serif;
    }
    
    /* RADAR PULSE ANIMATION */
    @keyframes pulse-green {
        0% { box-shadow: 0 0 0 0 rgba(76, 175, 80, 0.7); }
        70% { box-shadow: 0 0 0 10px rgba(76, 175, 80, 0); }
        100% { box-shadow: 0 0 0 0 rgba(76, 175, 80, 0); }
    }
    @keyframes pulse-red {
        0% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0.7); }
        70% { box-shadow: 0 0 0 10px rgba(255, 75, 75, 0); }
        100% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0); }
    }
    
    /* GLASS CARDS (MONEY & STATS) */
    div[data-testid="metric-container"] {
        background: rgba(255, 255, 255, 0.03);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
        transition: transform 0.2s;
    }
    
    /* STATUS PILLS */
    .status-pill {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 12px 20px;
        border-radius: 50px;
        font-weight: 600;
        letter-spacing: 0.5px;
        margin-bottom: 25px;
        backdrop-filter: blur(10px);
    }
    .safe-mode {
        background: rgba(28, 79, 46, 0.4);
        border: 1px solid #2e7d32;
        color: #4caf50;
        animation: pulse-green 2s infinite;
    }
    .danger-mode {
        background: rgba(79, 28, 28, 0.4);
        border: 1px solid #c62828;
        color: #ff5252;
        animation: pulse-red 2s infinite;
    }
    
    /* MODERN BUTTONS */
    .stButton>button {
        width: 100%;
        height: 64px;
        border-radius: 14px;
        font-weight: 700;
        font-size: 18px;
        border: none;
        text-transform: uppercase;
        letter-spacing: 1px;
        transition: all 0.3s ease;
    }
    
    /* HEADER DESIGN */
    .hero-header {
        text-align: center;
        padding: 40px 20px;
        background: linear-gradient(180deg, rgba(14,17,23,0) 0%, rgba(14,17,23,1) 100%), 
                    url("https://images.unsplash.com/photo-1550751827-4bd374c3f58b?q=80&w=2670&auto=format&fit=crop");
        background-size: cover;
        background-position: center;
        border-radius: 0 0 24px 24px;
        margin-top: -70px;
        margin-bottom: 30px;
        border-bottom: 1px solid rgba(255,255,255,0.1);
    }
    </style>
    """, unsafe_allow_html=True)

# --- CONFIGURATION (TARGET: BROCKTON HOSPITAL) ---
HOSPITAL_LAT = 42.0875
HOSPITAL_LON = -70.9915
GEOFENCE_RADIUS = 300 
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}

# ⚡ HEARTBEAT
count = st_autorefresh(interval=10000, key="pulse")

# --- DATABASE ENGINE ---
def get_db_connection():
    try:
        if "gcp_service_account" not in st.secrets: return None
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        client = gspread.authorize(creds)
        return client
    except: return None

# --- STATE MANAGEMENT (FIXED) ---
# Auto-repair session state if keys are missing
if 'user_state' not in st.session_state or 'data_loaded' not in st.session_state.user_state:
    st.session_state.user_state = {
        'active': False, 
        'start_time': 0.0, 
        'earnings': 0.0, 
        'locked': False,
        'payout_success': False,
        'clock_in_ip': None,
        'data_loaded': False
    }

# --- BACKEND FUNCTIONS ---
def get_current_ip():
    try: return requests.get('https://api.ipify.org', timeout=1).text
    except: return "Unknown"

def get_cloud_state(pin):
    client = get_db_connection()
    if not client: return {}
    try:
        sheet = client.open("ec_database").worksheet("workers")
        records = sheet.get_all_records()
        target_pin = str(pin).strip()
        for row in records:
            row_pin = None
            for key in row.keys():
                if str(key).strip().lower() == 'pin':
                    row_pin = str(row[key]).strip()
                    break
            if row_pin == target_pin: return row
        return {}
    except: return {}

def update_cloud_status(pin, status, start_time, earnings):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("workers")
            try:
                cell = sheet.find(str(pin))
                row = cell.row
                sheet.update_cell(row, 2, status)
                sheet.update_cell(row, 3, str(start_time))
                sheet.update_cell(row, 4, str(earnings))
                sheet.update_cell(row, 5, str(datetime.now()))
            except:
                sheet.append_row([str(pin), status, str(start_time), str(earnings), str(datetime.now())])
        except: pass

def log_transaction(pin, amount):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("transactions")
            tx_id = f"TX-{int(time.time())}"
            sheet.append_row([tx_id, str(pin), f"${amount:.2f}", str(datetime.now()), "INSTANT"])
            return tx_id
        except: return "ERR"

def log_history(pin, action, amount, note):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("history")
            sheet.append_row([str(pin), action, str(datetime.now()), f"${amount:.2f}", note])
        except: pass

def log_schedule(pin, date, start, end):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("schedule")
            sheet.append_row([str(pin), str(date), str(start), str(end), "Scheduled"])
            return True
        except: return False

# --- CALLBACKS ---
def cb_clock_in():
    st.session_state.user_state['active'] = True
    st.session_state.user_state['start_time'] = time.time()
    st.session_state.user_state['locked'] = True 
    current_ip = get_current_ip()
    st.session_state.user_state['clock_in_ip'] = current_ip
    pin = st.session_state.pin
    update_cloud_status(pin, "Active", time.time(), st.session_state.user_state['earnings'])
    log_history(pin, "CLOCK IN", st.session_state.user_state['earnings'], f"IP: {current_ip}")

def cb_clock_out():
    st.session_state.user_state['active'] = False
    pin = st.session_state.pin
    earnings = st.session_state.user_state['earnings']
    update_cloud_status(pin, "Inactive", 0, earnings)
    log_history(pin, "CLOCK OUT", earnings, "User Action")

def cb_payout():
    if st.session_state.user_state['earnings'] <= 0.01: return 
    pin = st.session_state.pin
    amount = st.session_state.user_state['earnings']
    taxed_amount = amount * (1 - sum(TAX_RATES.values()))
    log_transaction(pin, taxed_amount)
    st.session_state.user_state['earnings'] = 0.0
    st.session_state.user_state['payout_success'] = True
    update_cloud_status(pin, "Inactive", 0, 0)
    log_history(pin, "PAYOUT", taxed_amount, "Settled")

def cb_force_sync():
    pin = st.session_state.pin
    with st.spinner("Establishing Secure Handshake..."):
        cloud = get_cloud_state(pin)
        if cloud:
            status_val = str(cloud.get('status', '')).strip().lower()
            if status_val == 'active':
                st.session_state.user_state['active'] = True
                try:
                    st.session_state.user_state['start_time'] = float(cloud.get('start_time', 0))
                    st.session_state.user_state['earnings'] = float(cloud.get('earnings', 0))
                except: pass
            else:
                st.session_state.user_state['active'] = False
                try: st.session_state.user_state['earnings'] = float(cloud.get('earnings', 0))
                except: pass
            st.session_state.user_state['data_loaded'] = True
            st.toast("Protocol Synced.")
        else:
            st.toast("User ID Not Found")

# --- MATH ---
def get_distance(lat1, lon1, lat2, lon2):
    try:
        R = 6371000 
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return c * R
    except: return 0

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RT", "rate": 85.00},
    "1002": {"name": "Charles Morgan", "role": "RN", "rate": 90.00},
    "9999": {"name": "CFO VIEW", "role": "Exec", "rate": 0.00}
}

# --- LOGIN SCREEN ---
if 'logged_in_user' not in st.session_state:
    st.markdown("""
        <div style="text-align: center; padding: 50px;">
            <h1 style="font-size: 60px;">🛡️</h1>
            <h1 style="font-weight: 800; letter-spacing: -2px;">EC PROTOCOL</h1>
            <p style="color: #6e7280; font-size: 14px; text-transform: uppercase; letter-spacing: 2px;">Enterprise Login</p>
        </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        pin = st.text_input("ACCESS CODE", type="password", label_visibility="collapsed")
        if st.button("INITIALIZE SESSION"):
            if pin in USERS:
                st.session_state.logged_in_user = USERS[pin]
                st.session_state.pin = pin
                if USERS[pin]['role'] != "Exec": cb_force_sync()
                st.rerun()
            else:
                st.error("UNAUTHORIZED")
    st.stop()

# --- MAIN APP ---
user = st.session_state.logged_in_user
pin = st.session_state.pin

if user['role'] != "Exec":
    # 1. HEADER
    st.markdown(f"""
        <div class="hero-header">
            <h1 style='color:white; margin:0; font-size: 28px; font-weight: 800;'>EC ENTERPRISE</h1>
            <div style='display:inline-block; padding: 4px 12px; border-radius: 20px; background: rgba(59, 142, 219, 0.2); border: 1px solid #3b8edb; color: #3b8edb; font-size: 12px; margin-top: 10px;'>
                OPERATOR: {user['name'].upper()}
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    # 2. TABS (MAIN, SCHEDULE, LOGS)
    tab_main, tab_schedule, tab_logs = st.tabs(["MAIN CONTROL", "SCHEDULE", "LOGS"])

    with tab_main:
        # LIVE GPS STREAM
        loc = get_geolocation(component_key=f"gps_{count}")
        current_ip = get_current_ip()
        
        dist_msg = "ACQUIRING SATELLITE..."
        pill_class = "status-neutral"
        is_inside = False
        
        # DEV CONTROL
        with st.sidebar:
            st.caption("DEVELOPER TOOLS")
            dev_override = st.checkbox("FORCE GPS OVERRIDE (VIRTUAL)")
        
        if loc:
            dist = get_distance(loc['coords']['latitude'], loc['coords']['longitude'], HOSPITAL_LAT, HOSPITAL_LON)
            is_inside = dist < GEOFENCE_RADIUS or dev_override
            
            if is_inside:
                if dev_override:
                    dist_msg = "✅ VIRTUAL ZONE ACTIVE"
                else:
                    dist_msg = f"✅ SECURE ZONE • {int(dist)}m"
                pill_class = "safe-mode"
            else:
                dist_msg = f"🚫 OUTSIDE PERIMETER • {int(dist)}m"
                pill_class = "danger-mode"
                
            if st.session_state.user_state['active'] and not is_inside:
                cb_clock_out()
                st.error("⚠️ GEOFENCE BREACH - PROTOCOL HALTED")
                st.rerun()

        st.markdown(f'<div class="status-pill {pill_class}">{dist_msg}</div>', unsafe_allow_html=True)

        # EARNINGS
        if not st.session_state.user_state['data_loaded']:
            with st.spinner("Decrypting Financial Data..."):
                cb_force_sync()

        is_active = st.session_state.user_state['active']
        current_earnings = st.session_state.user_state['earnings']
        
        if is_active:
            start = st.session_state.user_state['start_time']
            if start > 0:
                elapsed_hours = (time.time() - start) / 3600
                current_earnings = elapsed_hours * user['rate']
                st.session_state.user_state['earnings'] = current_earnings
        
        net_pay = current_earnings * (1 - sum(TAX_RATES.values()))

        # MONEY CARDS
        c1, c2 = st.columns(2)
        c1.metric("GROSS ACCRUAL", f"${current_earnings:,.2f}", delta="Live" if is_active else None)
        c2.metric("NET PAYABLE", f"${net_pay:,.2f}", delta="Ready" if not is_active and net_pay > 0 else None)

        # CONTROLS
        st.markdown("###") # Spacer
        if is_active:
            st.button("🔴 TERMINATE SESSION", on_click=cb_clock_out, use_container_width=True)
        else:
            if is_inside:
                st.button("🟢 INITIALIZE PROTOCOL", on_click=cb_clock_in, use_container_width=True)
            else:
                st.info("📍 ENTER HOSPITAL ZONE TO BEGIN")
                
        # WALLET
        st.markdown("###")
        if not is_active and current_earnings > 0.01:
            st.info(f"💰 LIQUIDITY AVAILABLE: **${net_pay:,.2f}**")
            st.button("💸 EXECUTE TRANSFER", on_click=cb_payout, use_container_width=True)

        if st.session_state.user_state.get('payout_success'):
            st.balloons()
            st.success("ASSETS TRANSFERRED TO BANK")
            st.session_state.user_state['payout_success'] = False

    with tab_schedule:
        st.markdown("### 📅 Rolling Schedule")
        
        # Add Shift Form
        with st.expander("➕ Add New Shift"):
            with st.form("add_shift_form"):
                d = st.date_input("Date")
                s_time = st.time_input("Start Time")
                e_time = st.time_input("End Time")
                if st.form_submit_button("Confirm Schedule"):
                    res = log_schedule(pin, d, s_time, e_time)
                    if res: st.success("Shift Added to Cloud")
                    else: st.error("Schedule Failed - Check DB Connection")
        
        # View Shifts
        st.markdown("#### Upcoming Shifts")
        try:
            client = get_db_connection()
            if client:
                sheet = client.open("ec_database").worksheet("schedule")
                all_shifts = sheet.get_all_records()
                # Filter for current user
                my_shifts = [s for s in all_shifts if str(s.get('pin')).strip() == str(pin).strip()]
                if my_shifts:
                    st.dataframe(pd.DataFrame(my_shifts)[['date', 'start_time', 'end_time', 'notes']], use_container_width=True)
                else:
                    st.info("No upcoming shifts scheduled.")
        except: st.info("Schedule tab not found in DB.")

    with tab_logs:
        sub_t1, sub_t2 = st.tabs(["TRANSACTIONS", "ACTIVITY"])
        with sub_t1:
            try:
                client = get_db_connection()
                if client:
                    sheet = client.open("ec_database").worksheet("transactions")
                    st.dataframe(pd.DataFrame(sheet.get_all_records()), use_container_width=True)
            except: st.write("No Records")
        with sub_t2:
            try:
                client = get_db_connection()
                if client:
                    sheet = client.open("ec_database").worksheet("history")
                    st.dataframe(pd.DataFrame(sheet.get_all_records()), use_container_width=True)
            except: st.write("No Records")
        
    st.markdown("---")
    c1, c2 = st.columns([3,1])
    with c1:
        st.caption(f"SECURE ID: {current_ip}")
    with c2:
        if st.button("LOGOUT"):
            st.session_state.clear()
            st.rerun()

else:
    # CFO VIEW
    st.markdown(f"""
        <div class="hero-header">
            <h1 style='color:white; margin:0;'>COMMAND CENTER</h1>
            <p style='color:#f1c40f; margin:0;'>GLOBAL OVERSIGHT</p>
        </div>
    """, unsafe_allow_html=True)
    
    client = get_db_connection()
    if client:
        sheet = client.open("ec_database").worksheet("workers")
        st.dataframe(pd.DataFrame(sheet.get_all_records()), use_container_width=True)
        
    if st.button("LOGOUT"):
        st.session_state.clear()
        st.rerun()
