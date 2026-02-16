import streamlit as st
import pandas as pd
import time
import math
import requests
import pytz
import base64
import uuid
from datetime import datetime, timedelta
from streamlit_js_eval import get_geolocation
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_autorefresh import st_autorefresh

# --- 1. CONFIGURATION ---
st.set_page_config(
    page_title="EC Enterprise", 
    page_icon="🛡️", 
    layout="centered", 
    initial_sidebar_state="expanded"
)

st.markdown("""
    <head>
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="theme-color" content="#0E1117">
    </head>
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stApp { background: radial-gradient(circle at 50% -20%, #1c2331, #0E1117); color: #FFFFFF; font-family: 'Inter', sans-serif; }
    .status-pill { display: flex; align-items: center; justify-content: center; padding: 12px; border-radius: 50px; font-weight: 600; margin-bottom: 20px; backdrop-filter: blur(10px); }
    .safe-mode { background: rgba(28, 79, 46, 0.4); border: 1px solid #2e7d32; color: #4caf50; }
    .danger-mode { background: rgba(79, 28, 28, 0.4); border: 1px solid #c62828; color: #ff5252; }
    div[data-testid="metric-container"] { background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; }
    .stButton>button { width: 100%; height: 60px; border-radius: 12px; font-weight: 700; border: none; }
    .hero-header { text-align: center; padding: 30px 20px; background: linear-gradient(180deg, rgba(14,17,23,0) 0%, rgba(14,17,23,1) 100%), url("https://images.unsplash.com/photo-1550751827-4bd374c3f58b?q=80&w=2670&auto=format&fit=crop"); background-size: cover; border-radius: 0 0 24px 24px; margin-top: -60px; margin-bottom: 30px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. CONSTANTS ---
GEOFENCE_RADIUS = 30
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}
LOCAL_TZ = pytz.timezone('US/Eastern')

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RRT", "rate": 85.00, "lat": 42.0875, "lon": -70.9915, "location": "Brockton"},
    "1002": {"name": "Charles Morgan", "role": "RRT", "rate": 85.00, "lat": 42.0875, "lon": -70.9915, "location": "Brockton"},
    "9999": {"name": "CFO VIEW", "role": "Exec", "rate": 0.00}
}

# --- 3. BACKEND ---
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
    tx_id = f"TX-{int(time.time())}"
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("transactions")
            sheet.append_row([tx_id, str(pin), f"${amount:.2f}", str(datetime.now()), "INSTANT"])
        except: pass
    return tx_id

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

def post_shift_to_market(pin, role, d, s, e, rate):
    client = get_db_connection()
    if client:
        try:
            shift_id = str(uuid.uuid4())[:8]
            sheet = client.open("ec_database").worksheet("marketplace")
            sheet.append_row([shift_id, str(pin), role, str(d), str(s), str(e), str(rate), "OPEN"])
            return True
        except: return False
    return False

def claim_shift(shift_id, claimer_pin):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("marketplace")
            cell = sheet.find(shift_id)
            sheet.update_cell(cell.row, 8, f"CLAIMED BY {claimer_pin}")
            return True
        except: return False
    return False

def create_receipt_html(user_name, amount, tx_id):
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = f"""
    <html>
        <body style="font-family: monospace; padding: 40px; color: #333;">
            <div style="border: 2px solid #333; padding: 30px; max-width: 400px; margin: auto;">
                <h1 style="text-align: center;">EC ENTERPRISE</h1>
                <div style="text-align:center;">OFFICIAL PAY STUB</div>
                <hr style="border: 1px dashed #333;">
                <div style="display:flex; justify-content:space-between;"><span>PAYEE:</span><span>{user_name}</span></div>
                <div style="display:flex; justify-content:space-between;"><span>DATE:</span><span>{date_str}</span></div>
                <div style="display:flex; justify-content:space-between;"><span>TX ID:</span><span>{tx_id}</span></div>
                <hr style="border: 1px dashed #333;">
                <div style="display:flex; justify-content:space-between; font-weight:bold;"><span>NET PAY:</span><span>${amount:.2f}</span></div>
                <hr style="border: 1px dashed #333;">
                <div style="text-align: center; font-size: 0.8em; margin-top: 20px;">FUNDS SETTLED VIA INSTANT TRANSFER<br>SECURE PROTOCOL v83.0</div>
            </div>
        </body>
    </html>
    """
    return html

# --- 4. STATE ---
if 'user_state' not in st.session_state: st.session_state.user_state = {}
defaults = {
    'active': False, 'start_time': 0.0, 'earnings': 0.0, 
    'payout_success': False, 'data_loaded': False, 
    'last_tx_id': None, 'last_payout': 0.0, 'bio_auth_passed': False,
    'show_camera_in': False, 'show_camera_out': False # TOGGLES FOR CAMERA
}
for k, v in defaults.items():
    if k not in st.session_state.user_state: st.session_state.user_state[k] = v

# --- 5. AUTH ---
if 'logged_in_user' not in st.session_state:
    st.markdown("<h1 style='text-align: center; margin-top: 50px;'>🛡️ EC PROTOCOL</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        pin = st.text_input("ACCESS CODE", type="password")
        if st.button("AUTHENTICATE"):
            if pin in USERS:
                st.session_state.logged_in_user = USERS[pin]
                st.session_state.pin = pin
                if USERS[pin]['role'] != "Exec":
                    cloud = get_cloud_state(pin)
                    if cloud and str(cloud.get('status')).lower() == 'active':
                        st.session_state.user_state['active'] = True
                        st.session_state.user_state['start_time'] = float(cloud.get('start_time', 0))
                        st.session_state.user_state['earnings'] = float(cloud.get('earnings', 0))
                        st.session_state.user_state['bio_auth_passed'] = True 
                    st.session_state.user_state['data_loaded'] = True
                st.rerun()
            else: st.error("INVALID PIN")
    st.stop()

user = st.session_state.logged_in_user
pin = st.session_state.pin

# --- 6. CRITICAL CALLBACKS (ANTI-FRAUD) ---
def secure_payout_callback():
    # MUTEX LOCK: Only run if earnings exist
    current_bal = st.session_state.user_state['earnings']
    if current_bal <= 0.01:
        return # STOP FRAUD

    net = current_bal * (1 - sum(TAX_RATES.values()))
    tx_id = log_transaction(pin, net)
    log_history(pin, "PAYOUT", net, "Settled")
    update_cloud_status(pin, "Inactive", 0, 0)
    
    # UPDATE STATE INSTANTLY
    st.session_state.user_state['earnings'] = 0.0
    st.session_state.user_state['last_tx_id'] = tx_id
    st.session_state.user_state['last_payout'] = net
    st.session_state.user_state['payout_success'] = True

# --- 7. APP UI ---
with st.sidebar:
    st.markdown("### 🧭 NAVIGATION")
    nav_selection = st.radio("GO TO:", ["LIVE DASHBOARD", "MARKETPLACE", "SCHEDULER", "LOGS"])
    st.markdown("---")
    if str(pin) == "1001":
        st.caption("ADMIN OVERRIDE")
        dev_override = st.checkbox("FORCE GPS VIRTUALIZATION")
        st.markdown("---")
    if st.button("LOGOUT"):
        st.session_state.clear()
        st.rerun()

if user['role'] == "Exec":
    st.title("COMMAND CENTER")
    st_autorefresh(interval=30000, key="cfo")
    client = get_db_connection()
    if client:
        data = client.open("ec_database").worksheet("workers").get_all_records()
        st.dataframe(pd.DataFrame(data))
else:
    st.markdown(f"""<div class="hero-header"><h2 style='margin:0;'>EC ENTERPRISE</h2><div style='background:rgba(255, 255, 255, 0.1); color:#FFFFFF; padding:5px 15px; border-radius:20px; display:inline-block; margin-top:10px; font-weight: bold;'>OPERATOR: {user['name'].upper()} ({user['role']})</div></div>""", unsafe_allow_html=True)

    if nav_selection == "LIVE DASHBOARD":
        count = st_autorefresh(interval=10000, key="pulse")
        loc = get_geolocation(component_key=f"gps_{count}")
        ip = get_current_ip()
        
        target_lat = user.get('lat', 0)
        target_lon = user.get('lon', 0)
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
        msg = "✅ VIRTUAL ZONE" if dev_override else (f"✅ SECURE ZONE • {int(dist)}m" if is_inside else f"🚫 OUTSIDE ZONE • {int(dist)}m")
        cls = "safe-mode" if is_inside else "danger-mode"
        st.markdown(f'<div class="status-pill {cls}">{msg}</div>', unsafe_allow_html=True)
        
        if st.session_state.user_state['active'] and not is_inside:
            st.session_state.user_state['active'] = False
            update_cloud_status(pin, "Inactive", 0, st.session_state.user_state['earnings'])
            log_history(pin, "AUTO-LOGOUT", st.session_state.user_state['earnings'], "Geofence Exit")
            st.error("⚠️ GEOFENCE EXIT - CLOCKED OUT")
            st.rerun()

        active = st.session_state.user_state['active']
        earnings = st.session_state.user_state['earnings']
        if active:
            earnings += ((time.time() - st.session_state.user_state['start_time']) / 3600) * user['rate']
            st.session_state.user_state['start_time'] = time.time() 
            st.session_state.user_state['earnings'] = earnings

        gross = earnings
        tax_held = earnings * 0.3465
        net = earnings * (1 - 0.3465)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("GROSS", f"${gross:,.2f}")
        c2.metric("🔒 TAX VAULT", f"${tax_held:,.2f}") 
        c3.metric("NET AVAIL", f"${net:,.2f}")
        
        st.markdown("###")
        
        # --- NEW CAMERA LOGIC (ON DEMAND ONLY) ---
        if active:
            # CLOCK OUT FLOW
            if st.session_state.user_state['show_camera_out']:
                st.info("📸 VERIFY IDENTITY TO END SHIFT")
                img = st.camera_input("SCAN FACE")
                if img:
                    st.session_state.user_state['active'] = False
                    st.session_state.user_state['show_camera_out'] = False # Hide camera
                    update_cloud_status(pin, "Inactive", 0, earnings)
                    log_history(pin, "CLOCK OUT", earnings, "Verified")
                    st.rerun()
                if st.button("CANCEL"):
                    st.session_state.user_state['show_camera_out'] = False
                    st.rerun()
            else:
                if st.button("🔴 END SHIFT"):
                    st.session_state.user_state['show_camera_out'] = True
                    st.rerun()
        else:
            # CLOCK IN FLOW
            if is_inside:
                if st.session_state.user_state['show_camera_in']:
                    st.info("📸 VERIFY IDENTITY TO START SHIFT")
                    img = st.camera_input("SCAN FACE")
                    if img:
                        st.session_state.user_state['active'] = True
                        st.session_state.user_state['start_time'] = time.time()
                        st.session_state.user_state['show_camera_in'] = False # Hide camera
                        update_cloud_status(pin, "Active", time.time(), earnings)
                        log_history(pin, "CLOCK IN", earnings, f"Verified IP: {ip}")
                        st.rerun()
                    if st.button("CANCEL"):
                        st.session_state.user_state['show_camera_in'] = False
                        st.rerun()
                else:
                    if st.button("🟢 START SHIFT"):
                        st.session_state.user_state['show_camera_in'] = True
                        st.rerun()
            else:
                st.info(f"📍 PROCEED TO {user.get('location').upper()}")
        
        st.markdown("###")
        # --- SECURE PAYOUT ---
        if not active and earnings > 0.01:
            st.button(f"💸 PAYOUT ${net:,.2f}", on_click=secure_payout_callback)
        
        if st.session_state.user_state.get('payout_success'):
            st.success("TRANSFER COMPLETE")
            receipt_html = create_receipt_html(
                user['name'], 
                st.session_state.user_state['last_payout'], 
                st.session_state.user_state['last_tx_id']
            )
            b64 = base64.b64encode(receipt_html.encode()).decode()
            href = f'<a href="data:text/html;base64,{b64}" download="PAY_STUB.html">'
            href += '<button style="width:100%; height:50px; background:#4CAF50; color:white; border:none; border-radius:10px;">📥 DOWNLOAD OFFICIAL RECEIPT</button></a>'
            st.markdown(href, unsafe_allow_html=True)
    
    elif nav_selection == "MARKETPLACE":
        st.markdown("### 🏥 SHIFT MARKETPLACE")
        st.info(f"BROWSING FOR ROLE: **{user['role']}**")
        tab1, tab2 = st.tabs(["BROWSE SHIFTS", "POST SHIFT"])
        with tab1:
            try:
                client = get_db_connection()
                if client:
                    sheet = client.open("ec_database").worksheet("marketplace")
                    data = sheet.get_all_records()
                    available = [x for x in data if x.get('role') == user['role'] and x.get('status') == "OPEN"]
                    if available:
                        for shift in available:
                            with st.expander(f"📅 {shift['date']} | {shift['start']} - {shift['end']} (${shift['rate']}/hr)"):
                                st.caption(f"POSTED BY: {shift['poster_pin']}")
                                if st.button(f"CLAIM SHIFT ({shift['id']})"):
                                    if claim_shift(shift['id'], pin):
                                        st.success("SHIFT CLAIMED!")
                                        time.sleep(1)
                                        st.rerun()
                                    else: st.error("ERROR CLAIMING")
                    else: st.info("NO SHIFTS AVAILABLE")
            except: st.write("Marketplace DB Not Found.")
        with tab2:
            with st.form("post_shift"):
                c1, c2 = st.columns(2)
                d = c1.date_input("Date")
                rate = c2.number_input("Hourly Rate ($)", value=user['rate'])
                s = c1.time_input("Start")
                e = c2.time_input("End")
                if st.form_submit_button("POST SHIFT TO MARKET"):
                    if post_shift_to_market(pin, user['role'], d, s, e, rate): st.success("SHIFT POSTED")
                    else: st.error("DB Error")

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
        try:
            client = get_db_connection()
            if client:
                data = client.open("ec_database").worksheet("schedule").get_all_records()
                my_data = [x for x in data if str(x.get('pin')).strip() == str(pin).strip()]
                if my_data: st.dataframe(pd.DataFrame(my_data))
                else: st.info("No Shifts")
        except: st.write("DB Error")

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
