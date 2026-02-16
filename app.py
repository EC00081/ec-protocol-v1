import streamlit as st
import pandas as pd
import time
import math
import requests
import pytz
import base64
import uuid
import numpy as np
from datetime import datetime
from streamlit_js_eval import get_geolocation
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from streamlit_autorefresh import st_autorefresh

# --- 0. LIGHTWEIGHT LIBRARY LOADER ---
try:
    import face_recognition
    from shapely.geometry import Point, Polygon
    BIO_ENGINE_AVAILABLE = True
except ImportError:
    BIO_ENGINE_AVAILABLE = False
    # Fallback classes for demo to prevent crashing
    class Point:
        def __init__(self, x, y): self.x, self.y = x, y
    class Polygon:
        def __init__(self, points): self.points = points
        def contains(self, point): return True 

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
    div[data-testid="stMap"] { border-radius: 16px; overflow: hidden; border: 1px solid rgba(255,255,255,0.2); }
    .status-pill { display: flex; align-items: center; justify-content: center; padding: 12px; border-radius: 50px; font-weight: 600; margin-bottom: 20px; backdrop-filter: blur(10px); }
    .safe-mode { background: rgba(28, 79, 46, 0.4); border: 1px solid #2e7d32; color: #4caf50; }
    .danger-mode { background: rgba(79, 28, 28, 0.4); border: 1px solid #c62828; color: #ff5252; }
    div[data-testid="metric-container"] { background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; }
    .stButton>button { width: 100%; height: 60px; border-radius: 12px; font-weight: 700; border: none; }
    .hero-header { text-align: center; padding: 30px 20px; background: linear-gradient(180deg, rgba(14,17,23,0) 0%, rgba(14,17,23,1) 100%), url("https://images.unsplash.com/photo-1550751827-4bd374c3f58b?q=80&w=2670&auto=format&fit=crop"); background-size: cover; border-radius: 0 0 24px 24px; margin-top: -60px; margin-bottom: 30px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. CONSTANTS ---
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}
LOCAL_TZ = pytz.timezone('US/Eastern')
BROCKTON_POLYGON_COORDS = [(42.0880, -70.9920), (42.0880, -70.9910), (42.0870, -70.9910), (42.0870, -70.9920)]
HOSPITAL_FENCE = Polygon(BROCKTON_POLYGON_COORDS)
GEOFENCE_RADIUS = 45 # Fallback radius

def get_local_now(): return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S EST")

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RRT", "rate": 85.00, "lat": 42.0875, "lon": -70.9915, "location": "Brockton"},
    "1002": {"name": "Charles Morgan", "role": "RRT", "rate": 85.00, "lat": 42.0875, "lon": -70.9915, "location": "Brockton"},
    "9999": {"name": "CFO VIEW", "role": "Exec", "rate": 0.00}
}

# --- 3. LOGIC ENGINE ---
def verify_polygon_access(user_lat, user_lon):
    if not BIO_ENGINE_AVAILABLE:
        # Fallback Radius Check
        target_lat = 42.0875
        target_lon = -70.9915
        R = 6371000
        lat1, lon1 = math.radians(user_lat), math.radians(user_lon)
        lat2, lon2 = math.radians(target_lat), math.radians(target_lon)
        a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2) * math.sin((lon2-lon1)/2)**2
        dist = R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))
        return dist < GEOFENCE_RADIUS
    point = Point(user_lat, user_lon)
    return HOSPITAL_FENCE.contains(point)

def process_biometric_hash(image_upload):
    if not BIO_ENGINE_AVAILABLE:
        time.sleep(1.0) # Simulate processing time
        return True, "SIMULATED_HASH"
    try:
        img = face_recognition.load_image_file(image_upload)
        face_locations = face_recognition.face_locations(img)
        if len(face_locations) != 1: return False, f"Liveness Check Failed: {len(face_locations)} faces detected."
        return True, face_recognition.face_encodings(img, face_locations)[0]
    except Exception as e: return False, str(e)

# --- 4. BACKEND ---
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
                sheet.update_cell(cell.row, 5, get_local_now())
            except:
                sheet.append_row([str(pin), status, str(start), str(earn), get_local_now()])
        except: pass

def log_transaction(pin, amount):
    tx_id = f"TX-{int(time.time())}"
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("transactions")
            sheet.append_row([tx_id, str(pin), f"${amount:.2f}", get_local_now(), "INSTANT"])
        except: pass
    return tx_id

def log_history(pin, action, amount, note):
    client = get_db_connection()
    if client:
        try:
            sheet = client.open("ec_database").worksheet("history")
            sheet.append_row([str(pin), action, get_local_now(), f"${amount:.2f}", note])
        except: pass

def log_schedule(pin, d, s, e):
    client = get_db_connection()
    if client:
        try:
            dt_s = datetime.combine(d, s).strftime("%Y-%m-%d %H:%M:%S EST")
            dt_e = datetime.combine(d, e).strftime("%Y-%m-%d %H:%M:%S EST")
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
            s_str = s.strftime("%H:%M EST")
            e_str = e.strftime("%H:%M EST")
            sheet = client.open("ec_database").worksheet("marketplace")
            sheet.append_row([shift_id, str(pin), role, str(d), s_str, e_str, str(rate), "OPEN"])
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
    date_str = get_local_now()
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
                <div style="text-align: center; font-size: 0.8em; margin-top: 20px;">FUNDS SETTLED VIA INSTANT TRANSFER<br>SECURE PROTOCOL v86.0</div>
            </div>
        </body>
    </html>
    """
    return html

# --- 5. INITIALIZATION ---
if 'user_state' not in st.session_state: st.session_state.user_state = {}
defaults = {
    'active': False, 'start_time': 0.0, 'earnings': 0.0, 
    'payout_success': False, 'data_loaded': False, 
    'last_tx_id': None, 'last_payout': 0.0, 'bio_auth_passed': False,
    'show_camera_in': False, 'show_camera_out': False
}
for k, v in defaults.items():
    if k not in st.session_state.user_state: st.session_state.user_state[k] = v

# --- 6. AUTH ---
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

# --- 7. CRITICAL CALLBACKS (THE FIX) ---
def secure_payout_callback():
    # 1. ATOMIC CHECK: Check if money is already gone
    current_bal = st.session_state.user_state['earnings']
    if current_bal <= 0.01:
        st.toast("⚠️ Transaction already processed!", icon="🚫")
        return 

    # 2. CALCULATE
    net = current_bal * (1 - sum(TAX_RATES.values()))
    
    # 3. WIPE STATE INSTANTLY (Prevents Double Click)
    st.session_state.user_state['earnings'] = 0.0
    st.session_state.user_state['payout_success'] = True
    st.session_state.user_state['last_tx_id'] = f"TX-{int(time.time())}" # Temp ID for UI
    st.session_state.user_state['last_payout'] = net
    
    # 4. LOG TO DB (Async-ish)
    tx_id = log_transaction(pin, net)
    st.session_state.user_state['last_tx_id'] = tx_id # Update with real ID
    log_history(pin, "PAYOUT", net, "Settled")
    update_cloud_status(pin, "Inactive", 0, 0)

# --- 8. APP UI ---
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
        
        # GEO LOGIC
        gps_valid = False
        dist = 99999
        if loc:
            lat = loc['coords']['latitude']
            lon = loc['coords']['longitude']
            gps_valid = verify_polygon_access(lat, lon) or dev_override
            dist = 0 if gps_valid else 100

        is_inside = gps_valid
        msg = "✅ SECURE ZONE" if gps_valid else "🚫 OUTSIDE PERIMETER"
        cls = "safe-mode" if gps_valid else "danger-mode"
        st.markdown(f'<div class="status-pill {cls}">{msg}</div>', unsafe_allow_html=True)
        
        # AUTO LOGOUT
        if st.session_state.user_state['active'] and not gps_valid:
            st.session_state.user_state['active'] = False
            st.session_state.user_state['bio_auth_passed'] = False
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
        
        # --- CAMERA LOGIC ---
        if active:
            if st.session_state.user_state['show_camera_out']:
                st.info("📸 BIO-HASH VERIFICATION REQUIRED")
                img = st.camera_input("SCAN FACE")
                if img:
                    success, data = process_biometric_hash(img)
                    if success:
                        st.session_state.user_state['active'] = False
                        st.session_state.user_state['show_camera_out'] = False 
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
            if gps_valid:
                if st.session_state.user_state['show_camera_in']:
                    st.info("📸 BIO-HASH VERIFICATION REQUIRED")
                    img = st.camera_input("SCAN FACE")
                    if img:
                        success, data = process_biometric_hash(img)
                        if success:
                            st.session_state.user_state['active'] = True
                            st.session_state.user_state['start_time'] = time.time()
                            st.session_state.user_state['show_camera_in'] = False
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
        
        # --- SECURE PAYOUT BUTTON (The Fix) ---
        # The button ONLY appears if earnings > 0.01
        # The secure_payout_callback wipes the earnings to 0.0 immediately
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
        st.markdown("### 🏥 SHIFT MARKETPLACE (EST)")
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
                st.caption(f"POSTING AS: {user['name']} (Rate: ${user['rate']}/hr)")
                c1, c2 = st.columns(2)
                d = c1.date_input("Date")
                s = c1.time_input("Start (EST)")
                e = c2.time_input("End (EST)")
                if st.form_submit_button("POST SHIFT"):
                    if post_shift_to_market(pin, user['role'], d, s, e, user['rate']): st.success("SHIFT POSTED")
                    else: st.error("DB Error")

    elif nav_selection == "SCHEDULER":
        st.markdown("### 📅 Rolling Schedule (EST)")
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
                sheet = client.open("ec_database").worksheet("schedule")
                data = sheet.get_all_records()
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
                tx_sheet = client.open("ec_database").worksheet("transactions")
                st.dataframe(pd.DataFrame(tx_sheet.get_all_records()))
                st.write("Activity")
                hx_sheet = client.open("ec_database").worksheet("history")
                st.dataframe(pd.DataFrame(hx_sheet.get_all_records()))
        except: st.write("No Data")
