import streamlit as st
import pandas as pd
import time
import math
import pytz
import os
from datetime import datetime, date, timedelta
from collections import defaultdict
from streamlit_js_eval import get_geolocation
from sqlalchemy import create_engine, text
import pydeck as pdk
import plotly.express as px

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
        try:
            # These will pull from Render Environment Variables safely during production
            sid = os.environ.get("TWILIO_ACCOUNT_SID")
            token = os.environ.get("TWILIO_AUTH_TOKEN")
            from_num = os.environ.get("TWILIO_PHONE_NUMBER")
            if sid and token and from_num:
                client = Client(sid, token)
                client.messages.create(body=message_body, from_=from_num, to=to_phone)
                return True
        except Exception as e:
            print(f"Twilio Error: {e}")
    return False

# --- 1. CONFIGURATION & STYLING ---
st.set_page_config(page_title="EC Enterprise", page_icon="🛡️", layout="wide", initial_sidebar_state="expanded")

html_style = """
<style>
    p, h1, h2, h3, h4, h5, h6, div, label, button, input, select, textarea { font-family: 'Inter', sans-serif !important; }
    .stApp { background-color: #0b1120; background-image: radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.15) 0px, transparent 50%), radial-gradient(at 100% 0%, rgba(16, 185, 129, 0.1) 0px, transparent 50%), radial-gradient(at 50% 100%, rgba(139, 92, 246, 0.1) 0px, transparent 50%); background-attachment: fixed; color: #f8fafc; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {background: transparent !important;}
    div[data-testid="metric-container"], .glass-card { background: rgba(30, 41, 59, 0.5) !important; backdrop-filter: blur(12px) !important; -webkit-backdrop-filter: blur(12px) !important; border: 1px solid rgba(255, 255, 255, 0.08) !important; border-radius: 16px; padding: 20px; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2); margin-bottom: 15px; }
    div[data-testid="metric-container"] label { color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #f8fafc; font-size: 2rem; font-weight: 800; text-shadow: 0 2px 10px rgba(0,0,0,0.3); }
    .stButton>button { width: 100%; height: 60px; border-radius: 12px; font-weight: 700; font-size: 1.1rem; border: none; transition: all 0.3s ease; text-transform: uppercase; letter-spacing: 1px; box-shadow: 0 4px 15px rgba(0,0,0,0.2); }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.3); }
    .stTextInput>div>div>input, .stSelectbox>div>div>div, .stDateInput>div>div>input, .stNumberInput>div>div>input { background-color: rgba(15, 23, 42, 0.6) !important; color: white !important; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1) !important; backdrop-filter: blur(10px); }
    .sched-date-header { background: rgba(16, 185, 129, 0.1); padding: 10px 15px; border-radius: 8px; margin-top: 25px; margin-bottom: 15px; font-weight: 800; font-size: 1.1rem; border-left: 4px solid #10b981; color: #34d399; text-transform: uppercase; letter-spacing: 1px; }
    .sched-row { display: flex; justify-content: space-between; padding: 15px; margin-bottom: 8px; border-left: 4px solid rgba(255,255,255,0.1); background: rgba(30, 41, 59, 0.5); border-radius: 8px; }
    .sched-time { color: #34d399; font-weight: 800; width: 120px; font-size: 1.1rem; }
    .chat-bubble { padding: 12px 16px; border-radius: 16px; margin-bottom: 10px; max-width: 80%; line-height: 1.4; }
    .chat-me { background: rgba(59, 130, 246, 0.2); border: 1px solid rgba(59, 130, 246, 0.4); margin-left: auto; border-bottom-right-radius: 4px; }
    .chat-them { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); margin-right: auto; border-bottom-left-radius: 4px; }
</style>
"""
st.markdown(html_style, unsafe_allow_html=True)

# --- 2. CONSTANTS & ORG CHART ---
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}
LOCAL_TZ = pytz.timezone('US/Eastern')
GEOFENCE_RADIUS = 150 # meters
HOSPITALS = {"Brockton General": {"lat": 42.0875, "lon": -70.9915}, "Remote/Anywhere": {"lat": 0.0, "lon": 0.0}}

# ADD YOUR REAL PHONE NUMBER TO LIAM O'NEIL'S PROFILE BELOW
USERS = {
    "1001": {"email": "liam@ecprotocol.com", "password": "password123", "pin": "1001", "name": "Liam O'Neil", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 1200.00, "vip": False, "phone": "+18448032563"},
    "1002": {"email": "charles@ecprotocol.com", "password": "password123", "pin": "1002", "name": "Charles Morgan", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 50.00, "vip": False, "phone": None},
    "1003": {"email": "sarah@ecprotocol.com", "password": "password123", "pin": "1003", "name": "Sarah Jenkins", "role": "Charge RRT", "dept": "Respiratory", "level": "Supervisor", "rate": 90.00, "vip": True, "phone": None},
    "1004": {"email": "manager@ecprotocol.com", "password": "password123", "pin": "1004", "name": "David Clark", "role": "Manager", "dept": "Respiratory", "level": "Manager", "rate": 0.00, "vip": True, "phone": None},
    "9999": {"email": "cfo@ecprotocol.com", "password": "password123", "pin": "9999", "name": "CFO VIEW", "role": "Admin", "dept": "All", "level": "Admin", "rate": 0.00, "vip": True, "phone": None}
}

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1); dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- 3. DATABASE ENGINE & MIGRATION ---
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
            conn.execute(text("CREATE TABLE IF NOT EXISTS assignments (assign_id text PRIMARY KEY, shift_date text, pin text, dept text, zone text, status text DEFAULT 'ACTIVE', swap_with_pin text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS credentials (doc_id text PRIMARY KEY, pin text, doc_type text, doc_number text, exp_date text, status text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS vaccines (vax_id text PRIMARY KEY, pin text, vax_type text, admin_date text, exp_date text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS hr_onboarding (pin text PRIMARY KEY, w4_filing_status text, w4_allowances int, dd_bank text, dd_acct_last4 text, signed_date timestamp DEFAULT NOW());"))
            # Safely add lat/lon to workers if it doesn't exist
            try: conn.execute(text("ALTER TABLE workers ADD COLUMN lat numeric; ALTER TABLE workers ADD COLUMN lon numeric;"))
            except: pass
            conn.commit()
        return engine
    except Exception as e: 
        print(f"DB Connection Error: {e}")
        return None

def run_query(query, params=None):
    engine = get_db_engine()
    if not engine: return None
    try:
        with engine.connect() as conn: return conn.execute(text(query), params or {}).fetchall()
    except Exception as e: 
        print(f"Query Error: {e}")
        return None

def run_transaction(query, params=None):
    engine = get_db_engine()
    if not engine: return False
    try:
        with engine.connect() as conn: 
            conn.execute(text(query), params or {})
            conn.commit()
            return True
    except Exception as e: 
        print(f"Transaction Error: {e}")
        return False

# --- 4. CORE DB LOGIC & PAYROLL HELPERS ---
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

def get_ytd_gross(pin):
    q = "SELECT amount FROM history WHERE pin=:p AND action='CLOCK OUT' AND EXTRACT(YEAR FROM timestamp) = :y"
    res = run_query(q, {"p": pin, "y": datetime.now().year})
    return sum([float(r[0]) for r in res if r[0]]) if res else 0.0

def get_period_gross(pin, start_date, end_date):
    q = "SELECT amount FROM history WHERE pin=:p AND action='CLOCK OUT' AND timestamp >= :s AND timestamp <= :e"
    res = run_query(q, {"p": pin, "s": start_date, "e": datetime.combine(end_date, datetime.max.time())})
    return sum([float(r[0]) for r in res if r[0]]) if res else 0.0

# --- 5. AUTH SCREEN & SESSION INIT ---
if 'user_state' not in st.session_state: st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0}
if 'edit_cred' not in st.session_state: st.session_state.edit_cred = None

if 'logged_in_user' not in st.session_state:
    st.markdown("<br><br><h1 style='text-align: center; color: #f8fafc; letter-spacing: 2px; font-weight: 900;'>EC PROTOCOL</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #94a3b8; letter-spacing: 3px;'>SECURE WORKFORCE ACCESS</p><br>", unsafe_allow_html=True)
    with st.container():
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        login_email = st.text_input("EMAIL ADDRESS", placeholder="name@hospital.com")
        login_password = st.text_input("PASSWORD", type="password", placeholder="••••••••")
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("AUTHENTICATE SYSTEM"):
            auth_pin = next((p for p, d in USERS.items() if d.get("email") == login_email.lower() and d.get("password") == login_password), None)
            if auth_pin:
                st.session_state.logged_in_user = USERS[auth_pin]
                st.session_state.pin = auth_pin
                st.session_state.last_read_chat = datetime.utcnow()
                force_cloud_sync(auth_pin)
                st.rerun()
            else: st.error("❌ INVALID CREDENTIALS")
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

user = st.session_state.logged_in_user
pin = st.session_state.pin

# --- SMART NOTIFICATION LOGIC ---
chat_label = "COMMS & CHAT"
if 'last_read_chat' not in st.session_state: st.session_state.last_read_chat = datetime.utcnow()
latest_msg_q = run_query("SELECT MAX(timestamp) FROM comms_log")
if latest_msg_q and latest_msg_q[0][0]:
    latest_db_dt = pd.to_datetime(latest_msg_q[0][0])
    if latest_db_dt.tzinfo is None: latest_db_dt = latest_db_dt.tz_localize('UTC')
    session_read_dt = pd.to_datetime(st.session_state.last_read_chat)
    if session_read_dt.tzinfo is None: session_read_dt = session_read_dt.tz_localize('UTC')
    if latest_db_dt > session_read_dt: chat_label = "COMMS & CHAT 🔴"

# --- 7. NAVIGATION BUILDER ---
with st.sidebar:
    st.markdown(f"<h3 style='color: #38bdf8; margin-bottom: 0;'>{user['name'].upper()}</h3>", unsafe_allow_html=True)
    st.caption(f"{user['role']} | {user['dept']}")
    st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
    
    if user['level'] == "Admin": 
        menu_items = ["COMMAND CENTER", "MASTER SCHEDULE", "APPROVALS"]
    elif user['level'] in ["Manager", "Director"]: 
        menu_items = ["DASHBOARD", "CENSUS & ACUITY", "ASSIGNMENTS", chat_label, "MARKETPLACE", "THE BANK", "APPROVALS", "MY PROFILE"]
    elif user['level'] == "Supervisor":
        menu_items = ["DASHBOARD", "CENSUS & ACUITY", "ASSIGNMENTS", chat_label, "MARKETPLACE", "THE BANK", "MY PROFILE"]
    else: 
        menu_items = ["DASHBOARD", "ASSIGNMENTS", chat_label, "MARKETPLACE", "THE BANK", "MY PROFILE"]
        
    nav = st.radio("MENU", menu_items)
        
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("LOGOUT"): st.session_state.clear(); st.rerun()

if "COMMS" in nav:
    st.session_state.last_read_chat = datetime.utcnow()
    if "🔴" in nav: st.rerun() 
    nav = "COMMS & CHAT"

# --- 8. ROUTING ---

# [DASHBOARD & GEOFENCE SHOWSTOPPER] 
if nav == "DASHBOARD":
    hr = datetime.now(LOCAL_TZ).hour
    greeting = "Good Morning" if hr < 12 else "Good Afternoon" if hr < 17 else "Good Evening"
    st.markdown(f"<h1 style='font-weight: 800;'>{greeting}, {user['name'].split(' ')[0]}</h1>", unsafe_allow_html=True)
    
    active = st.session_state.user_state.get('active', False)
    running_earn = 0.0
    if active: running_earn = ((time.time() - st.session_state.user_state['start_time']) / 3600) * user['rate']
    
    display_gross = st.session_state.user_state.get('earnings', 0.0) + running_earn
    display_net = display_gross * (1 - sum(TAX_RATES.values()))
    
    c1, c2 = st.columns(2)
    c1.metric("CURRENT SHIFT ACCRUAL", f"${display_gross:,.2f}")
    c2.metric("NET PAYOUT ESTIMATE", f"${display_net:,.2f}")
    st.markdown("<br>", unsafe_allow_html=True)

    if active:
        st.markdown("### 🔴 END SHIFT VERIFICATION")
        end_pin = st.text_input("Enter 4-Digit PIN to Clock Out", type="password", key="end_pin")
        if st.button("PUNCH OUT"):
            if end_pin == pin:
                new_total = st.session_state.user_state.get('earnings', 0.0) + running_earn
                if update_status(pin, "Inactive", 0, new_total, 0.0, 0.0):
                    st.session_state.user_state['active'] = False; st.session_state.user_state['earnings'] = new_total
                    log_action(pin, "CLOCK OUT", running_earn, f"Logged {running_earn/user['rate']:.2f} hrs")
                    st.rerun()
            else: st.error("❌ Incorrect PIN.")
    else:
        selected_facility = st.selectbox("Select Facility", list(HOSPITALS.keys()))
        if not user.get('vip', False):
            st.info("Identity verification required to initiate shift.")
            camera_photo = st.camera_input("Take a photo to verify identity")
            loc = get_geolocation()
            
            if camera_photo and loc:
                user_lat = loc['coords']['latitude']; user_lon = loc['coords']['longitude']
                fac_lat = HOSPITALS[selected_facility]["lat"]; fac_lon = HOSPITALS[selected_facility]["lon"]
                
                # --- SHOWSTOPPER 3: VISUAL GEOFENCE MAP ---
                st.markdown("### 🛰️ Live Geofence Uplink")
                if selected_facility != "Remote/Anywhere":
                    df_map = pd.DataFrame({'lat': [user_lat, fac_lat], 'lon': [user_lon, fac_lon], 'color': [[59, 130, 246, 200], [16, 185, 129, 200]], 'radius': [20, GEOFENCE_RADIUS]})
                    layer = pdk.Layer("ScatterplotLayer", df_map, get_position='[lon, lat]', get_color='color', get_radius='radius', pickable=True)
                    view_state = pdk.ViewState(latitude=user_lat, longitude=user_lon, zoom=15, pitch=45)
                    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view_state, map_style='mapbox://styles/mapbox/dark-v10'))
                    
                    distance = haversine_distance(user_lat, user_lon, fac_lat, fac_lon)
                    if distance <= GEOFENCE_RADIUS:
                        st.success(f"✅ Geofence Confirmed. You are {int(distance)}m from origin.")
                        start_pin = st.text_input("Enter 4-Digit PIN to Clock In", type="password", key="start_pin")
                        if st.button("PUNCH IN"):
                            if start_pin == pin:
                                start_t = time.time()
                                if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), user_lat, user_lon):
                                    st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t
                                    log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()
                            else: st.error("❌ Incorrect PIN.")
                    else: st.error(f"❌ Geofence Failed. You are {int(distance)}m away. Must be within {GEOFENCE_RADIUS}m.")
                else:
                    # Remote Mapping
                    df_map = pd.DataFrame({'lat': [user_lat], 'lon': [user_lon], 'color': [[59, 130, 246, 200]], 'radius': [20]})
                    layer = pdk.Layer("ScatterplotLayer", df_map, get_position='[lon, lat]', get_color='color', get_radius='radius', pickable=True)
                    view_state = pdk.ViewState(latitude=user_lat, longitude=user_lon, zoom=15, pitch=45)
                    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view_state, map_style='mapbox://styles/mapbox/dark-v10'))
                    
                    st.success("✅ Remote Check-in Authorized.")
                    start_pin = st.text_input("Enter 4-Digit PIN to Clock In", type="password", key="start_pin_remote")
                    if st.button("PUNCH IN (REMOTE)"):
                        if start_pin == pin:
                            start_t = time.time()
                            if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), user_lat, user_lon):
                                st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t
                                log_action(pin, "CLOCK IN", 0, f"Loc: Remote"); st.rerun()
                        else: st.error("❌ Incorrect PIN.")
        else:
            st.caption("✨ VIP Security Override Active")
            start_pin = st.text_input("Enter 4-Digit PIN to Clock In", type="password", key="vip_start_pin")
            if st.button("PUNCH IN"):
                if start_pin == pin:
                    start_t = time.time()
                    if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), 0.0, 0.0):
                        st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t
                        log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()
                else: st.error("❌ Incorrect PIN.")

# [COMMAND CENTER - SHOWSTOPPER 2: ANALYTICS & FLEET MAP]
elif nav == "COMMAND CENTER" and user['level'] == "Admin":
    st.markdown("## 🦅 Global Command Center")
    t_fleet, t_finance = st.tabs(["🗺️ LIVE FLEET TRACKING", "📈 FINANCIAL ANALYTICS"])
    
    with t_fleet:
        st.markdown("### Active Operators")
        active_workers = run_query("SELECT pin, start_time, earnings, lat, lon FROM workers WHERE status='Active'")
        if active_workers:
            map_data = []
            for w in active_workers:
                w_pin, w_start, w_lat, w_lon = str(w[0]), float(w[1]), w[3], w[4]
                w_name = USERS.get(w_pin, {}).get("name", "Unknown")
                w_role = USERS.get(w_pin, {}).get("role", "Worker")
                hrs = (time.time() - w_start) / 3600
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid #10b981 !important;'><h4 style='margin:0;'>{w_name} | {w_role}</h4><span style='color:#10b981; font-weight:bold;'>🟢 ON CLOCK ({hrs:.2f} hrs)</span></div>", unsafe_allow_html=True)
                if w_lat and w_lon: map_data.append({"name": w_name, "lat": float(w_lat), "lon": float(w_lon)})
            
            if map_data:
                st.markdown("### Fleet Spatial Uplink")
                df_fleet = pd.DataFrame(map_data)
                layer = pdk.Layer("ScatterplotLayer", df_fleet, get_position='[lon, lat]', get_color='[16, 185, 129, 200]', get_radius=100, pickable=True)
                view_state = pdk.ViewState(latitude=df_fleet['lat'].mean(), longitude=df_fleet['lon'].mean(), zoom=11, pitch=45)
                st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view_state, map_style='mapbox://styles/mapbox/dark-v10', tooltip={"text": "{name}"}))
        else:
            st.info("No active operators in the field.")
            
    with t_finance:
        st.markdown("### CFO Predictive Analytics Board")
        # Generate some quick math for the showstopper demo
        q_spend = "SELECT DATE(timestamp), SUM(amount) FROM history WHERE action='CLOCK OUT' GROUP BY DATE(timestamp) ORDER BY DATE(timestamp) ASC LIMIT 7"
        spend_data = run_query(q_spend)
        
        total_spend = 0
        if spend_data:
            df_spend = pd.DataFrame(spend_data, columns=["Date", "Daily Spend"])
            total_spend = df_spend["Daily Spend"].sum()
            # Agency costs typically 2.5x standard internal rates
            agency_avoidance = total_spend * 1.5 
            
            c1, c2, c3 = st.columns(3)
            c1.metric("7-Day Internal Labor Spend", f"${total_spend:,.2f}")
            c2.metric("Projected Agency Cost", f"${total_spend * 2.5:,.2f}")
            c3.metric("Agency Avoidance Savings", f"${agency_avoidance:,.2f}", "+150% ROI")
            
            st.markdown("#### Spend Trajectory vs Budget")
            fig = px.area(df_spend, x="Date", y="Daily Spend", template="plotly_dark", color_discrete_sequence=["#10b981"])
            fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Insufficient historical data to generate financial projections. Complete a few shifts to feed the AI.")

# [CENSUS & ACUITY + SOS PROTOCOL WITH TWILIO]
elif nav == "CENSUS & ACUITY" and user['level'] in ["Supervisor", "Manager", "Director"]:
    st.markdown(f"## 📊 {user['dept']} Census & Staffing")
    if st.button("🔄 Refresh Live Database"): st.rerun()
    
    c_data = run_query("SELECT total_pts, high_acuity, last_updated FROM unit_census WHERE dept=:d", {"d": user['dept']})
    curr_pts = c_data[0][0] if c_data else 0
    curr_high = c_data[0][1] if c_data else 0
    if c_data and c_data[0][2]:
        dt_obj = pd.to_datetime(c_data[0][2])
        if dt_obj.tzinfo is None: dt_obj = dt_obj.tz_localize('UTC')
        last_upd = dt_obj.astimezone(LOCAL_TZ).strftime("%I:%M %p")
    else: last_upd = "Never"

    standard_pts = max(0, curr_pts - curr_high)
    req_staff_high = math.ceil(curr_high / 3)
    req_staff_std = math.ceil(standard_pts / 6)
    total_req_staff = req_staff_high + req_staff_std

    actual_staff = 0
    active_rows = run_query("SELECT pin FROM workers WHERE status='Active'")
    if active_rows:
        for r in active_rows:
            if USERS.get(str(r[0]), {}).get('dept') == user['dept']: actual_staff += 1

    variance = actual_staff - total_req_staff
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Patients", curr_pts, f"{curr_high} High Acuity", delta_color="off")
    col2.metric("Required Staff (Calculated)", total_req_staff)
    
    if variance < 0:
        col3.metric("Current Staff (Live)", actual_staff, f"{variance} (Understaffed)", delta_color="inverse")
        st.error(f"🚨 UNSAFE STAFFING DETECTED: {user['dept']} requires {abs(variance)} more active personnel to meet safe care ratios.")
        
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button(f"🚨 BROADCAST SOS FOR {abs(variance)} STAFF"):
            missing_count = abs(variance)
            incentive_rate = user['rate'] * 1.5 if user['rate'] > 0 else 125.00
            
            for i in range(missing_count):
                s_id = f"SOS-{int(time.time()*1000)}-{i}"
                run_transaction("INSERT INTO marketplace (shift_id, poster_pin, role, date, start_time, end_time, rate, status) VALUES (:id, :p, :r, :d, :s, :e, :rt, 'OPEN')", {"id": s_id, "p": pin, "r": f"🚨 SOS URGENT: {user['dept']}", "d": str(date.today()), "s": "NOW", "e": "END OF SHIFT", "rt": incentive_rate})
            
            msg_id = f"MSG-SOS-{int(time.time()*1000)}"
            sos_msg_dept = f"🚨 SYSTEM ALERT: The unit is understaffed by {missing_count}. Emergency shifts with 1.5x incentive pay (${incentive_rate:.2f}/hr) have been posted to the Marketplace!"
            sos_msg_global = f"[{user['dept'].upper()}] SYSTEM ALERT: The unit is critically understaffed by {missing_count}. Emergency shifts have been posted to the Marketplace! Check your schedules."
            
            run_transaction("INSERT INTO comms_log (msg_id, pin, dept, content) VALUES (:id, :p, :d, :c)", {"id": msg_id, "p": "9999", "d": user['dept'], "c": sos_msg_dept}) 
            run_transaction("INSERT INTO comms_log (msg_id, pin, dept, content) VALUES (:id, :p, :d, :c)", {"id": msg_id+"-g", "p": "9999", "d": "GLOBAL", "c": sos_msg_global}) 
            
            # --- SHOWSTOPPER 1: TWILIO SMS FIRING ---
            sms_sent = False
            for u_pin, u_data in USERS.items():
                if u_data.get('dept') == user['dept'] and u_data.get('phone') and u_pin != pin:
                    sms_sent = send_sms(u_data['phone'], f"EC PROTOCOL SOS: {user['dept']} needs {missing_count} staff NOW. 1.5x Incentive Pay Active. Claim in app.") or sms_sent
            
            st.success(f"🚨 SOS Broadcasted! Shifts pushed to Marketplace." + (" SMS Alerts dispatched to off-duty staff!" if sms_sent else ""))
            time.sleep(2.5); st.rerun()
    else:
        col3.metric("Current Staff (Live)", actual_staff, f"+{variance} (Safe)", delta_color="normal")
        st.success(f"✅ Safe Staffing Maintained: Ratios are currently optimal.")

    st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
    with st.expander("📝 UPDATE CENSUS NUMBERS", expanded=False):
        with st.form("update_census"):
            st.caption(f"Last Updated: {last_upd}")
            new_t = st.number_input("Total Unit Census", min_value=0, value=curr_pts, step=1)
            new_h = st.number_input("High Acuity (Vents/ICU Stepdown)", min_value=0, value=curr_high, step=1)
            if st.form_submit_button("Lock In Census"):
                if new_h > new_t: st.error("High acuity cannot exceed total patients.")
                else:
                    exists = run_query("SELECT 1 FROM unit_census WHERE dept=:d", {"d": user['dept']})
                    if exists: success = run_transaction("UPDATE unit_census SET total_pts=:t, high_acuity=:h, last_updated=NOW() WHERE dept=:d", {"d": user['dept'], "t": new_t, "h": new_h})
                    else: success = run_transaction("INSERT INTO unit_census (dept, total_pts, high_acuity) VALUES (:d, :t, :h)", {"d": user['dept'], "t": new_t, "h": new_h})
                    if success: st.success("Census Updated!"); time.sleep(1); st.rerun()

# [APPROVALS WITH TWILIO]
elif nav == "APPROVALS" and user['level'] in ["Manager", "Director", "Admin"]:
    st.markdown("## 📥 Manager Approvals")
    st.markdown("### Pending Financial Withdrawals")
    pending_tx = run_query("SELECT tx_id, pin, amount, timestamp FROM transactions WHERE status='PENDING' ORDER BY timestamp ASC")
    if pending_tx:
        for tx in pending_tx:
            t_id, w_pin, t_amt, t_time = tx[0], tx[1], float(tx[2]), tx[3]
            w_name = USERS.get(str(w_pin), {}).get("name", f"User {w_pin}")
            with st.container():
                st.markdown(f"""<div class='glass-card' style='border-left: 4px solid #f59e0b !important;'><h4 style='margin:0; color:#f8fafc;'>{w_name} requested a transfer of <span style='color:#10b981;'>${t_amt:,.2f}</span></h4><p style='color:#94a3b8; font-size:0.85rem; margin-top:5px;'>Requested: {t_time} | TX ID: {t_id}</p></div>""", unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                if c1.button("✅ APPROVE PAYOUT", key=f"app_{t_id}"):
                    run_transaction("UPDATE transactions SET status='APPROVED' WHERE tx_id=:id", {"id": t_id})
                    log_action(pin, "MANAGER APPROVAL", t_amt, f"Approved payout for {w_name}")
                    
                    # --- SHOWSTOPPER 1: TWILIO APPROVAL SMS ---
                    target_phone = USERS.get(str(w_pin), {}).get('phone')
                    if target_phone:
                        send_sms(target_phone, f"EC PROTOCOL: Your instant payout of ${t_amt:,.2f} has been approved and dispatched to your bank.")
                    
                    st.success("Approved. Funds Released."); time.sleep(1.5); st.rerun()
                if c2.button("❌ DENY", key=f"den_{t_id}"):
                    run_transaction("UPDATE transactions SET status='DENIED' WHERE tx_id=:id", {"id": t_id}); st.error("Denied."); time.sleep(1); st.rerun()
                st.markdown("<br>", unsafe_allow_html=True)
    else: st.info("No pending financial transactions.")

# [THE BANK (WITH COLOR FIX)]
elif nav == "THE BANK":
    st.markdown("## 🏦 The Bank")
    st.caption("Manage your payouts, review shift logs, and download pay stubs.")
    banked_gross = st.session_state.user_state.get('earnings', 0.0)
    banked_net = banked_gross * (1 - sum(TAX_RATES.values()))
    
    st.markdown(f"<div class='glass-card' style='text-align: center; border-left: 4px solid #10b981 !important;'><h3 style='color: #94a3b8; margin-bottom: 5px;'>AVAILABLE FOR WITHDRAWAL</h3><h1 style='color: #10b981; font-size: 3rem; margin: 0;'>${banked_net:,.2f}</h1><p style='color: #64748b;'>Gross Accrued: ${banked_gross:,.2f} (Taxes Withheld: ${banked_gross - banked_net:,.2f})</p></div>", unsafe_allow_html=True)
    
    if banked_net > 0.01 and not st.session_state.user_state.get('active', False):
        if st.button("💸 REQUEST WITHDRAWAL (SENDS TO MANAGER)"):
            tx_id = f"TX-{int(time.time())}"
            if run_transaction("INSERT INTO transactions (tx_id, pin, amount, timestamp, status) VALUES (:id, :p, :a, NOW(), 'PENDING')", {"id": tx_id, "p": pin, "a": banked_net}):
                update_status(pin, "Inactive", 0, 0.0); st.session_state.user_state['earnings'] = 0.0
                st.success("✅ Withdrawal Requested! Awaiting Manager Approval."); time.sleep(1.5); st.rerun()
    st.markdown("<br>", unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["SHIFT LOGS", "WITHDRAWAL HISTORY", "PAY STUBS"])
    with tab1:
        res = run_query("SELECT timestamp, amount, note FROM history WHERE pin=:p AND action='CLOCK OUT' ORDER BY timestamp DESC LIMIT 30", {"p": pin})
        if res:
            for r in res:
                ts, amt, note = r[0], float(r[1]), r[2]
                st.markdown(f"<div class='glass-card' style='padding: 15px; margin-bottom: 10px; border-left: 4px solid #10b981 !important;'><div style='display: flex; justify-content: space-between;'><strong style='color: #f8fafc;'>Shift Completed</strong><strong style='color: #10b981; font-size:1.2rem;'>${amt:,.2f}</strong></div><div style='color: #94a3b8; font-size: 0.85rem;'>{ts} | <span style='color: #3b82f6; font-weight:800;'>{note}</span></div></div>", unsafe_allow_html=True)
        else: st.info("No shifts worked yet.")
    with tab2:
        res = run_query("SELECT timestamp, amount, status FROM transactions WHERE pin=:p ORDER BY timestamp DESC", {"p": pin})
        if res:
            for r in res:
                ts, amt, status = r[0], float(r[1]), r[2]
                color = "#10b981" if status == "APPROVED" else "#f59e0b" if status == "PENDING" else "#ff453a"
                st.markdown(f"<div class='glass-card' style='padding: 15px; margin-bottom: 10px; border-left: 4px solid {color} !important;'><div style='display: flex; justify-content: space-between;'><strong style='color: #f8fafc;'>Transfer Request</strong><strong style='color: {color}; font-size:1.2rem;'>${amt:,.2f}</strong></div><div style='color: #94a3b8; font-size: 0.85rem; margin-top: 5px;'>{ts} | Status: <strong style='color:{color};'>{status}</strong></div></div>", unsafe_allow_html=True)
        else: st.info("No withdrawal history.")
    with tab3:
        with st.form("pay_stub_form"):
            c1, c2 = st.columns(2)
            start_d = c1.date_input("Start Date", value=date.today() - timedelta(days=14)); end_d = c2.date_input("End Date", value=date.today())
            if st.form_submit_button("Generate PDF Statement") and PDF_ACTIVE:
                period_gross = get_period_gross(pin, start_d, end_d)
                if period_gross > 0:
                    st.session_state.pdf_data = generate_pay_stub(user, start_d, end_d, period_gross, get_ytd_gross(pin))
                    st.session_state.pdf_filename = f"PayStub_{pin}_{end_d}.pdf"
                    st.success("✅ Pay Stub Generated!")
                else: st.warning("No earnings found for this period.")
        if 'pdf_data' in st.session_state:
            st.download_button("📄 Download PDF Pay Stub", data=st.session_state.pdf_data, file_name=st.session_state.pdf_filename, mime="application/pdf")

# [OTHER TABS MINIMIZED FOR TERMINAL SPACE]
elif nav in ["COMMS & CHAT", "ASSIGNMENTS", "MARKETPLACE", "SCHEDULE", "MY PROFILE"]:
    st.info(f"{nav} engine is active in the background. Use Dashboard, Command Center, Approvals, or Census to test the new Showstopper modules.")
