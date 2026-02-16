import streamlit as st
import pandas as pd
import time
import math
import hashlib
import requests
import pytz
from datetime import datetime, timedelta
from streamlit_js_eval import get_geolocation
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="EC Enterprise", page_icon="🛡️", layout="centered")

# --- 2. STYLING ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stApp {
        background: radial-gradient(circle at 50% -20%, #1c2331, #0E1117);
        color: #FFFFFF;
        font-family: 'Inter', sans-serif;
    }
    .status-pill {
        display: flex; align-items: center; justify-content: center;
        padding: 12px; border-radius: 50px; font-weight: 600;
        margin-bottom: 20px; backdrop-filter: blur(10px);
    }
    .safe-mode { background: rgba(28, 79, 46, 0.4); border: 1px solid #2e7d32; color: #4caf50; }
    .danger-mode { background: rgba(79, 28, 28, 0.4); border: 1px solid #c62828; color: #ff5252; }
    div[data-testid="metric-container"] {
        background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px;
    }
    .stButton>button {
        width: 100%; height: 60px; border-radius: 12px; font-weight: 700; border: none;
    }
    .hero-header {
        text-align: center; padding: 30px 20px;
        background: linear-gradient(180deg, rgba(14,17,23,0) 0%, rgba(14,17,23,1) 100%), 
                    url("https://images.unsplash.com/photo-1550751827-4bd374c3f58b?q=80&w=2670&auto=format&fit=crop");
        background-size: cover; border-radius: 0 0 24px 24px; margin-top: -60px; margin-bottom: 30px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. CONSTANTS & USERS ---
GEOFENCE_RADIUS = 300 
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}
LOCAL_TZ = pytz.timezone('US/Eastern')

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RT", "rate": 85.00, "lat": 42.0875, "lon": -70.9915, "location": "Brockton"},
    "1002": {"name": "Charles Morgan", "role": "RN", "rate": 90.00, "lat": 42.3372, "lon": -71.1064, "location": "Boston Children's"},
    "9999": {"name": "CFO VIEW", "role": "Exec", "rate": 0.00}
}

# --- 4. BACKEND FUNCTIONS ---
def get_db_connection():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        return gspread.authorize(creds)
    except: return None

def get_current_ip():
    try: return requests.get('https://api.ipify.org', timeout=1).text
    except: return "Unknown"

def get_cloud_state(pin):
    client = get_db_connection()
    if not client: return {}
    try:
        sheet = client.open("ec_database").worksheet("workers")
        records = sheet.get_all_records()
        target = str(pin).strip()
        for row in records:
            for k, v in row.items():
                if str(k).lower().strip() == 'pin' and str(v).strip() == target:
                    return row
        return {}
    except: return {}

def update_cloud_status(pin, status, start, earn):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("workers")
            try:
                cell = sheet.find(str(pin))
                sheet.update_cell(cell.row, 2, status)
                sheet.update_cell(cell.row, 3, str(start))
                sheet.update_cell(cell.row, 4, str(earn))
                sheet.update_cell(cell.row, 5, str(datetime.now()))
            except:
                sheet.append_row([str(pin), status, str(start), str(earn), str(datetime.now())])
        except: pass

def log_transaction(pin, amount):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("transactions")
            sheet.append_row([f"TX-{int(time.time())}", str(pin), f"${amount:.2f}", str(datetime.now()), "INSTANT"])
        except: pass

def log_history(pin, action, amount, note):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("history")
            sheet.append_row([str(pin), action, str(datetime.now()), f"${amount:.2f}", note])
        except: pass

def log_schedule(pin, d, s, e):
    client = get_db_connection()
    if client:
        try:
            dt_s = LOCAL_TZ.localize(datetime.combine(d, s)).astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            dt_e = LOCAL_TZ.localize(datetime.combine(d, e)).astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            sheet = client.open("ec_database").worksheet("schedule")
            sheet.append_row([str(pin), str(d), dt_s, dt_e, "Scheduled"])
            return True
        except: return False
    return False

# --- 5. INITIALIZATION ---
if 'user_state' not in st.session_state or 'data_loaded' not in st.session_state.user_state:
    st.session_state.user_state = {
        'active': False, 'start_time': 0.0, 'earnings': 0.0, 
        'locked': False, 'payout_success': False, 'data_loaded': False
    }

# --- 6. AUTHENTICATION ---
if 'logged_in_user' not in st.session_state:
    st.markdown("<h1 style='text-align: center; margin-top: 50px;'>🛡️ EC PROTOCOL</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        pin = st.text_input("ACCESS CODE", type="password")
        if st.button("AUTHENTICATE"):
            if pin in USERS:
                st.session_state.logged_in_user = USERS[pin]
                st.session_state.pin = pin
                # Pre-load data
                if USERS[pin]['role'] != "Exec":
                    cloud = get_cloud_state(pin)
                    if cloud and str(cloud.get('status')).lower() == 'active':
                        st.session_state.user_state['active'] = True
                        st.session_state.user_state['start_time'] = float(cloud.get('start_time', 0))
                        st.session_state.user_state['earnings'] = float(cloud.get('earnings', 0))
                    st.session_state.user_state['data_loaded'] = True
                st.rerun()
            else: st.error("INVALID PIN")
    st.stop()

# --- 7. MAIN APP ---
user = st.session_state.logged_in_user
pin = st.session_state.pin

# *** GLOBAL SIDEBAR (HOISTED) ***
dev_override = False # Default state
with st.sidebar:
    st.markdown("### 🧭 NAVIGATION")
    nav_selection = st.radio("GO TO:", ["LIVE DASHBOARD", "SCHEDULER", "LOGS"])
    
    st.markdown("---")
    
    # 🔒 RESTRICTED DEV TOOLS (ONLY 1001)
    if str(pin) == "1001":
        st.caption("DEVELOPER TOOLS (ADMIN ONLY)")
        dev_override = st.checkbox("FORCE GPS OVERRIDE")
        st.markdown("---")
    
    if st.button("LOGOUT"):
        st.session_state.clear()
        st.rerun()

# *** CONTENT ROUTER ***
if user['role'] == "Exec":
    # CFO View
    st.title("COMMAND CENTER")
    client = get_db_connection()
    if client:
        st.dataframe(pd.DataFrame(client.open("ec_database").worksheet("workers").get_all_records()))

else:
    # WORKER VIEW
    # Updated Header: WHITE TEXT for name visibility
    st.markdown(f"""
        <div class="hero-header">
            <h2 style='margin:0;'>EC ENTERPRISE</h2>
            <div style='background:rgba(255, 255, 255, 0.1); color:#FFFFFF; padding:5px 15px; border-radius:20px; display:inline-block; margin-top:10px; border: 1px solid rgba(255,255,255,0.2); font-weight: bold;'>
                OPERATOR: {user['name'].upper()}
            </div>
        </div>
    """, unsafe_allow_html=True)

    # PAGE 1: LIVE DASHBOARD
    if nav_selection == "LIVE DASHBOARD":
        count = st_autorefresh(interval=10000, key="pulse")
        
        # GPS Logic
        loc = get_geolocation(component_key=f"gps_{count}")
        ip = get_current_ip()
        
        target_lat = user.get('lat', 0)
        target_lon = user.get('lon', 0)
        
        # Distance Calc
        dist = 99999
        if loc:
            try:
                R = 6371000
                lat1, lon1 = math.radians(loc['coords']['latitude']), math.radians(loc['coords']['longitude'])
                lat2, lon2 = math.radians(target_lat), math.radians(target_lon)
                a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2) * math.sin((lon2-lon1)/2)**2
                dist = R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))
            except: pass

        is_inside = dist < GEOFENCE_RADIUS or dev_override
        
        # Banner
        if is_inside:
            msg = "✅ VIRTUAL ZONE" if dev_override else f"✅ SECURE ZONE • {int(dist)}m"
            cls = "safe-mode"
        else:
            msg = f"🚫 OUTSIDE ZONE • {int(dist)}m"
            cls = "danger-mode"
            
        st.markdown(f'<div class="status-pill {cls}">{msg}</div>', unsafe_allow_html=True)
        
        # Auto-Logout
        if st.session_state.user_state['active'] and not is_inside:
            st.session_state.user_state['active'] = False
            update_cloud_status(pin, "Inactive", 0, st.session_state.user_state['earnings'])
            log_history(pin, "AUTO-LOGOUT", st.session_state.user_state['earnings'], "Geofence Exit")
            st.error("⚠️ GEOFENCE EXIT - CLOCKED OUT")
            st.rerun()

        # Money Logic
        active = st.session_state.user_state['active']
        earnings = st.session_state.user_state['earnings']
        if active:
            earnings += ((time.time() - st.session_state.user_state['start_time']) / 3600) * user['rate']
            # Reset start time to avoid double counting
            st.session_state.user_state['start_time'] = time.time() 
            st.session_state.user_state['earnings'] = earnings

        net = earnings * (1 - sum(TAX_RATES.values()))
        
        c1, c2 = st.columns(2)
        c1.metric("GROSS", f"${earnings:,.2f}")
        c2.metric("NET", f"${net:,.2f}")
        
        st.markdown("###")
        if active:
            if st.button("🔴 END SHIFT"):
                st.session_state.user_state['active'] = False
                update_cloud_status(pin, "Inactive", 0, earnings)
                log_history(pin, "CLOCK OUT", earnings, "Manual")
                st.rerun()
        else:
            if is_inside:
                if st.button("🟢 START SHIFT"):
                    st.session_state.user_state['active'] = True
                    st.session_state.user_state['start_time'] = time.time()
                    update_cloud_status(pin, "Active", time.time(), earnings)
                    log_history(pin, "CLOCK IN", earnings, f"IP: {ip}")
                    st.rerun()
            else:
                st.info(f"📍 PROCEED TO {user.get('location').upper()}")
        
        st.markdown("###")
        if not active and earnings > 0.01:
            if st.button("💸 PAYOUT"):
                log_transaction(pin, net)
                log_history(pin, "PAYOUT", net, "Settled")
                update_cloud_status(pin, "Inactive", 0, 0)
                st.session_state.user_state['earnings'] = 0.0
                st.balloons()
                st.success("TRANSFERRED")
                time.sleep(2)
                st.rerun()

    # PAGE 2: SCHEDULER
    elif nav_selection == "SCHEDULER":
        st.markdown("### 📅 Rolling Schedule")
        with st.form("sched"):
            c1, c2 = st.columns(2)
            d = c1.date_input("Date")
            s = c1.time_input("Start")
            e = c2.time_input("End")
            if st.form_submit_button("Add Shift"):
                if log_schedule(pin, d, s, e): st.success("Added")
                else: st.error("Error")
        
        # View
        try:
            client = get_db_connection()
            if client:
                data = client.open("ec_database").worksheet("schedule").get_all_records()
                my_data = [x for x in data if str(x.get('pin')).strip() == str(pin).strip()]
                if my_data: st.dataframe(pd.DataFrame(my_data))
                else: st.info("No Shifts")
        except: st.write("DB Error")

    # PAGE 3: LOGS
    elif nav_selection == "LOGS":
        st.markdown("### 📂 Logs")
        try:
            client = get_db_connection()
            if client:
                st.write("Transactions")
                st.dataframe(pd.DataFrame(client.open("ec_database").worksheet("transactions").get_all_records()))
                st.write("Activity")
                st.dataframe(pd.DataFrame(client.open("ec_database").worksheet("history").get_all_records()))
        except: st.write("No Data")
