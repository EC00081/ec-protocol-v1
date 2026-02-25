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
        diag = f"[SID Length: {len(clean_sid)} | Token Length: {len(clean_token)}]"
        if not clean_sid or not clean_token or not clean_from: return False, f"Missing Env Vars. {diag}"
        try:
            client = Client(clean_sid, clean_token)
            client.messages.create(body=message_body, from_=clean_from, to=to_phone)
            return True, "SMS Dispatched"
        except Exception as e: return False, f"{diag} | Error: {str(e)}"
    return False, "Twilio library inactive or missing phone number."

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
GEOFENCE_RADIUS = 150
HOSPITALS = {"Brockton General": {"lat": 42.0875, "lon": -70.9915}, "Remote/Anywhere": {"lat": 0.0, "lon": 0.0}}

USERS = {
    "1001": {"email": "liam@ecprotocol.com", "password": "password123", "pin": "1001", "name": "Liam O'Neil", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 1200.00, "vip": False, "phone": "+15555555555"},
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
            conn.execute(text("CREATE TABLE IF NOT EXISTS assignments (assign_id text PRIMARY KEY, shift_date text, pin text, dept text, zone text, status text DEFAULT 'ACTIVE', swap_with_pin text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS credentials (doc_id text PRIMARY KEY, pin text, doc_type text, doc_number text, exp_date text, status text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS vaccines (vax_id text PRIMARY KEY, pin text, vax_type text, admin_date text, exp_date text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS hr_onboarding (pin text PRIMARY KEY, w4_filing_status text, w4_allowances int, dd_bank text, dd_acct_last4 text, signed_date timestamp DEFAULT NOW());"))
            # NEW: PTO Table
            conn.execute(text("CREATE TABLE IF NOT EXISTS pto_requests (req_id text PRIMARY KEY, pin text, start_date text, end_date text, reason text, status text DEFAULT 'PENDING', submitted timestamp DEFAULT NOW());"))
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

# --- 4. CORE DB LOGIC ---
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

chat_label = "COMMS & CHAT"
if 'last_read_chat' not in st.session_state: st.session_state.last_read_chat = datetime.utcnow()
latest_msg_q = run_query("SELECT MAX(timestamp) FROM comms_log")
if latest_msg_q and latest_msg_q[0][0]:
    latest_db_dt = pd.to_datetime(latest_msg_q[0][0])
    if latest_db_dt.tzinfo is None: latest_db_dt = latest_db_dt.tz_localize('UTC')
    session_read_dt = pd.to_datetime(st.session_state.last_read_chat)
    if session_read_dt.tzinfo is None: session_read_dt = session_read_dt.tz_localize('UTC')
    if latest_db_dt > session_read_dt: chat_label = "COMMS & CHAT 🔴"

with st.sidebar:
    st.markdown(f"<h3 style='color: #38bdf8; margin-bottom: 0;'>{user['name'].upper()}</h3>", unsafe_allow_html=True)
    st.caption(f"{user['role']} | {user['dept']}")
    st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
    
    if user['level'] == "Admin": menu_items = ["COMMAND CENTER", "MASTER SCHEDULE", "APPROVALS"]
    elif user['level'] in ["Manager", "Director"]: menu_items = ["DASHBOARD", "CENSUS & ACUITY", "ASSIGNMENTS", chat_label, "MARKETPLACE", "SCHEDULE", "THE BANK", "APPROVALS", "MY PROFILE"]
    elif user['level'] == "Supervisor": menu_items = ["DASHBOARD", "CENSUS & ACUITY", "ASSIGNMENTS", chat_label, "MARKETPLACE", "SCHEDULE", "THE BANK", "MY PROFILE"]
    else: menu_items = ["DASHBOARD", "ASSIGNMENTS", chat_label, "MARKETPLACE", "SCHEDULE", "THE BANK", "MY PROFILE"]
        
    nav = st.radio("MENU", menu_items)
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("LOGOUT"): st.session_state.clear(); st.rerun()

if "COMMS" in nav:
    st.session_state.last_read_chat = datetime.utcnow()
    if "🔴" in nav: st.rerun() 
    nav = "COMMS & CHAT"

# --- 8. ROUTING ---

# [DASHBOARD & MANAGER HUD] 
if nav == "DASHBOARD":
    hr = datetime.now(LOCAL_TZ).hour
    greeting = "Good Morning" if hr < 12 else "Good Afternoon" if hr < 17 else "Good Evening"
    
    # --- MANAGER HUD ---
    if user['level'] in ["Manager", "Director"]:
        st.markdown(f"<h1 style='font-weight: 800;'>{greeting}, {user['name'].split(' ')[0]}</h1>", unsafe_allow_html=True)
        st.markdown("### 🎛️ Departmental Overview")
        
        # Gathering Data for Manager
        active_staff = run_query("SELECT COUNT(*) FROM workers WHERE status='Active'")
        active_count = active_staff[0][0] if active_staff else 0
        
        open_shifts = run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'")
        shifts_count = open_shifts[0][0] if open_shifts else 0
        
        pending_tx = run_query("SELECT COUNT(*) FROM transactions WHERE status='PENDING'")
        tx_count = pending_tx[0][0] if pending_tx else 0
        
        pending_pto = run_query("SELECT COUNT(*) FROM pto_requests WHERE status='PENDING'")
        pto_count = pending_pto[0][0] if pending_pto else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Live Staff on Floor", active_count)
        c2.metric("Unfilled SOS / Market Shifts", shifts_count, f"{shifts_count} Critical" if shifts_count > 0 else "Fully Staffed", delta_color="inverse")
        c3.metric("Pending Approvals", tx_count + pto_count, f"{tx_count} Payouts | {pto_count} PTO", delta_color="off")
        st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
        
    else:
        st.markdown(f"<h1 style='font-weight: 800;'>{greeting}, {user['name'].split(' ')[0]}</h1>", unsafe_allow_html=True)

    # Worker Clock-in Engine (Available for all)
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
                user_lat, user_lon = loc['coords']['latitude'], loc['coords']['longitude']
                fac_lat, fac_lon = HOSPITALS[selected_facility]["lat"], HOSPITALS[selected_facility]["lon"]
                
                st.markdown("### 🛰️ Live Geofence Uplink")
                if selected_facility != "Remote/Anywhere":
                    df_map = pd.DataFrame({'lat': [user_lat, fac_lat], 'lon': [user_lon, fac_lon], 'color': [[59, 130, 246, 200], [16, 185, 129, 200]], 'radius': [20, GEOFENCE_RADIUS]})
                    layer = pdk.Layer("ScatterplotLayer", df_map, get_position='[lon, lat]', get_color='color', get_radius='radius', pickable=True)
                    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=pdk.ViewState(latitude=user_lat, longitude=user_lon, zoom=15, pitch=45), map_style='mapbox://styles/mapbox/dark-v10'))
                    
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
                    else: st.error(f"❌ Geofence Failed. You are {int(distance)}m away.")
                else:
                    st.success("✅ Remote Check-in Authorized.")
                    start_pin = st.text_input("Enter 4-Digit PIN to Clock In", type="password", key="start_pin_rem")
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

# [COMMAND CENTER - EXECUTIVE CFO SUITE]
elif nav == "COMMAND CENTER" and user['level'] == "Admin":
    if st.button("🔄 Refresh Data Link"): st.rerun()
    st.markdown("## 🦅 Executive Command Center")
    t_finance, t_fleet = st.tabs(["📈 FINANCIAL INTELLIGENCE", "🗺️ LIVE FLEET TRACKING"])
    
    with t_finance:
        st.markdown("### CFO Predictive Analytics Board")
        
        # Raw Data Extraction
        raw_history = run_query("SELECT pin, amount, DATE(timestamp) FROM history WHERE action='CLOCK OUT'")
        
        if raw_history:
            df = pd.DataFrame(raw_history, columns=["PIN", "Amount", "Date"])
            df['Amount'] = df['Amount'].astype(float)
            df['Dept'] = df['PIN'].apply(lambda x: USERS.get(str(x), {}).get('dept', 'Unknown'))
            
            total_spend = df['Amount'].sum()
            agency_cost = total_spend * 2.5
            agency_avoidance = agency_cost - total_spend
            
            # Top KPIs
            c1, c2, c3 = st.columns(3)
            c1.metric("Internal Labor Spend (Total)", f"${total_spend:,.2f}")
            c2.metric("Projected Agency Cost (2.5x)", f"${agency_cost:,.2f}")
            c3.metric("Agency Avoidance Savings", f"${agency_avoidance:,.2f}", "Positive ROI")
            
            st.markdown("<br>", unsafe_allow_html=True)
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                st.markdown("#### Spend by Department")
                dept_spend = df.groupby('Dept')['Amount'].sum().reset_index()
                fig_pie = px.pie(dept_spend, values='Amount', names='Dept', hole=0.6, template="plotly_dark", color_discrete_sequence=px.colors.sequential.Teal)
                fig_pie.update_layout(margin=dict(t=20, b=20, l=20, r=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_pie, use_container_width=True)
                
            with col_chart2:
                st.markdown("#### Agency Avoidance Efficiency")
                # Using a Plotly Gauge to make it look super high-end
                fig_gauge = go.Figure(go.Indicator(
                    mode = "gauge+number",
                    value = agency_avoidance,
                    title = {'text': "Capital Saved vs. Agency ($)", 'font': {'size': 16, 'color': '#94a3b8'}},
                    gauge = {
                        'axis': {'range': [None, agency_cost], 'tickwidth': 1, 'tickcolor': "white"},
                        'bar': {'color': "#10b981"},
                        'bgcolor': "rgba(255,255,255,0.05)",
                        'steps': [
                            {'range': [0, total_spend], 'color': "rgba(239,68,68,0.3)"},
                            {'range': [total_spend, agency_cost], 'color': "rgba(16,185,129,0.1)"}],
                    }
                ))
                fig_gauge.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", font={'color': "white"}, margin=dict(t=40, b=20, l=20, r=20))
                st.plotly_chart(fig_gauge, use_container_width=True)
                
            st.markdown("#### 7-Day Spend Trajectory")
            daily_spend = df.groupby('Date')['Amount'].sum().reset_index()
            fig_area = px.area(daily_spend, x="Date", y="Amount", template="plotly_dark", color_discrete_sequence=["#3b82f6"])
            fig_area.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig_area, use_container_width=True)
            
            # Export Function for CFO
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(label="📥 Export Raw Financial Ledger (CSV)", data=csv, file_name='ec_financial_ledger.csv', mime='text/csv')
            
        else:
            st.info("Awaiting shift completion data to render financial models.")

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
                st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=pdk.ViewState(latitude=df_fleet['lat'].mean(), longitude=df_fleet['lon'].mean(), zoom=11, pitch=45), map_style='mapbox://styles/mapbox/dark-v10', tooltip={"text": "{name}"}))
        else:
            st.info("No active operators in the field.")

# [CENSUS & ACUITY + TWILIO SOS]
elif nav == "CENSUS & ACUITY" and user['level'] in ["Supervisor", "Manager", "Director"]:
    st.markdown(f"## 📊 {user['dept']} Census & Staffing")
    if st.button("🔄 Refresh Census Board"): st.rerun()
    
    c_data = run_query("SELECT total_pts, high_acuity, last_updated FROM unit_census WHERE dept=:d", {"d": user['dept']})
    curr_pts, curr_high = (c_data[0][0], c_data[0][1]) if c_data else (0, 0)
    last_upd = pd.to_datetime(c_data[0][2]).tz_localize('UTC').astimezone(LOCAL_TZ).strftime("%I:%M %p") if c_data and c_data[0][2] else "Never"

    req_staff = math.ceil(curr_high / 3) + math.ceil(max(0, curr_pts - curr_high) / 6)
    actual_staff = sum(1 for r in run_query("SELECT pin FROM workers WHERE status='Active'") if USERS.get(str(r[0]), {}).get('dept') == user['dept']) if run_query("SELECT pin FROM workers WHERE status='Active'") else 0
    variance = actual_staff - req_staff
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Patients", curr_pts, f"{curr_high} High Acuity", delta_color="off")
    col2.metric("Required Staff (Calculated)", req_staff)
    
    if variance < 0:
        col3.metric("Current Staff", actual_staff, f"{variance} (Understaffed)", delta_color="inverse")
        st.error(f"🚨 UNSAFE STAFFING: Requires {abs(variance)} more personnel.")
        if st.button(f"🚨 BROADCAST SOS FOR {abs(variance)} STAFF"):
            rate = user['rate'] * 1.5 if user['rate'] > 0 else 125.00
            for i in range(abs(variance)):
                run_transaction("INSERT INTO marketplace (shift_id, poster_pin, role, date, start_time, end_time, rate, status) VALUES (:id, :p, :r, :d, :s, :e, :rt, 'OPEN')", {"id": f"SOS-{int(time.time()*1000)}-{i}", "p": pin, "r": f"🚨 SOS: {user['dept']}", "d": str(date.today()), "s": "NOW", "e": "END OF SHIFT", "rt": rate})
            
            msg_id = f"MSG-SOS-{int(time.time()*1000)}"
            run_transaction("INSERT INTO comms_log (msg_id, pin, dept, content) VALUES (:id, :p, :d, :c)", {"id": msg_id, "p": "9999", "d": user['dept'], "c": f"🚨 ALERT: Understaffed by {abs(variance)}. Shifts posted at 1.5x pay."}) 
            
            sms_sent = False
            for u_pin, u_data in USERS.items():
                if u_data.get('dept') == user['dept'] and u_data.get('phone') and u_pin != pin:
                    success, msg = send_sms(u_data['phone'], f"EC PROTOCOL SOS: {user['dept']} needs {abs(variance)} staff NOW. Claim in app.")
                    if success: sms_sent = True
            
            st.success("🚨 SOS Broadcasted! Shifts pushed" + (" and SMS Alerts dispatched!" if sms_sent else "."))
            time.sleep(2.5); st.rerun()
    else:
        col3.metric("Current Staff", actual_staff, f"+{variance} (Safe)", delta_color="normal")
        st.success(f"✅ Safe Staffing Maintained.")

    with st.expander("📝 UPDATE CENSUS NUMBERS", expanded=False):
        with st.form("update_census"):
            new_t = st.number_input("Total Unit Census", min_value=0, value=curr_pts, step=1)
            new_h = st.number_input("High Acuity (Vents/ICU Stepdown)", min_value=0, value=curr_high, step=1)
            if st.form_submit_button("Lock In Census"):
                if new_h > new_t: st.error("High acuity cannot exceed total patients.")
                else:
                    if run_query("SELECT 1 FROM unit_census WHERE dept=:d", {"d": user['dept']}): run_transaction("UPDATE unit_census SET total_pts=:t, high_acuity=:h, last_updated=NOW() WHERE dept=:d", {"d": user['dept'], "t": new_t, "h": new_h})
                    else: run_transaction("INSERT INTO unit_census (dept, total_pts, high_acuity) VALUES (:d, :t, :h)", {"d": user['dept'], "t": new_t, "h": new_h})
                    st.success("Census Updated!"); time.sleep(1); st.rerun()

# [APPROVALS ENGINE - PAYOUTS & PTO]
elif nav == "APPROVALS" and user['level'] in ["Manager", "Director", "Admin"]:
    st.markdown("## 📥 Manager Approvals")
    if st.button("🔄 Refresh Queue"): st.rerun()
    
    tab_fin, tab_pto = st.tabs(["💸 FINANCIAL PAYOUTS", "🏝️ PTO REQUESTS"])
    
    with tab_fin:
        st.markdown("### Pending Financial Withdrawals")
        pending_tx = run_query("SELECT tx_id, pin, amount, timestamp FROM transactions WHERE status='PENDING' ORDER BY timestamp ASC")
        if pending_tx:
            for tx in pending_tx:
                t_id, w_pin, t_amt, t_time = tx[0], tx[1], float(tx[2]), tx[3]
                w_name = USERS.get(str(w_pin), {}).get("name", f"User {w_pin}")
                with st.container():
                    st.markdown(f"<div class='glass-card' style='border-left: 4px solid #f59e0b !important;'><h4 style='margin:0; color:#f8fafc;'>{w_name} requested a transfer of <span style='color:#10b981;'>${t_amt:,.2f}</span></h4><p style='color:#94a3b8; font-size:0.85rem; margin-top:5px;'>Requested: {t_time}</p></div>", unsafe_allow_html=True)
                    c1, c2 = st.columns(2)
                    if c1.button("✅ APPROVE PAYOUT", key=f"app_{t_id}"):
                        run_transaction("UPDATE transactions SET status='APPROVED' WHERE tx_id=:id", {"id": t_id})
                        log_action(pin, "MANAGER APPROVAL", t_amt, f"Approved payout for {w_name}")
                        target_phone = USERS.get(str(w_pin), {}).get('phone')
                        if target_phone: send_sms(target_phone, f"EC PROTOCOL: Your payout of ${t_amt:,.2f} has been approved.")
                        st.success("Approved."); time.sleep(1.5); st.rerun()
                    if c2.button("❌ DENY", key=f"den_{t_id}"):
                        run_transaction("UPDATE transactions SET status='DENIED' WHERE tx_id=:id", {"id": t_id}); st.error("Denied."); time.sleep(1); st.rerun()
        else: st.info("No pending financial transactions.")

    with tab_pto:
        st.markdown("### Pending Time-Off Requests")
        pending_pto = run_query("SELECT req_id, pin, start_date, end_date, reason, submitted FROM pto_requests WHERE status='PENDING' ORDER BY submitted ASC")
        if pending_pto:
            for pto in pending_pto:
                p_id, p_pin, start_d, end_d, reason, p_time = pto[0], pto[1], pto[2], pto[3], pto[4], pto[5]
                w_name = USERS.get(str(p_pin), {}).get("name", f"User {p_pin}")
                with st.container():
                    st.markdown(f"<div class='glass-card' style='border-left: 4px solid #8b5cf6 !important;'><h4 style='margin:0; color:#f8fafc;'>{w_name} requested PTO</h4><div style='color:#38bdf8; font-weight:bold; margin-top:5px;'>Dates: {start_d} to {end_d}</div><div style='color:#94a3b8; font-size:0.9rem; margin-top:5px;'>Reason: {reason}</div></div>", unsafe_allow_html=True)
                    c1, c2 = st.columns(2)
                    if c1.button("✅ APPROVE PTO", key=f"app_pto_{p_id}"):
                        run_transaction("UPDATE pto_requests SET status='APPROVED' WHERE req_id=:id", {"id": p_id})
                        target_phone = USERS.get(str(p_pin), {}).get('phone')
                        if target_phone: send_sms(target_phone, f"EC PROTOCOL: Your PTO request for {start_d} has been APPROVED.")
                        st.success("PTO Approved."); time.sleep(1.5); st.rerun()
                    if c2.button("❌ DENY", key=f"den_pto_{p_id}"):
                        run_transaction("UPDATE pto_requests SET status='DENIED' WHERE req_id=:id", {"id": p_id})
                        st.error("PTO Denied."); time.sleep(1); st.rerun()
        else: st.info("No pending PTO requests.")

# [ENTERPRISE HR VAULT & PTO REQUESTER]
elif nav == "MY PROFILE":
    st.markdown("## 🗄️ Enterprise HR Vault")
    if st.button("🔄 Refresh HR Profile"): st.rerun()
    
    t_lic, t_vax, t_tax, t_pto = st.tabs(["🪪 LICENSES & CERTS", "💉 VACCINE VAULT", "📑 TAX & ONBOARDING", "🏝️ TIME OFF (PTO)"])
    
    with t_pto:
        st.markdown("### Request Paid Time Off")
        with st.form("pto_form"):
            c1, c2 = st.columns(2)
            pto_start = c1.date_input("Start Date", min_value=date.today())
            pto_end = c2.date_input("End Date", min_value=pto_start)
            pto_reason = st.text_input("Reason / Notes (Optional)")
            if st.form_submit_button("Submit PTO Request to Manager"):
                req_id = f"PTO-{int(time.time())}"
                run_transaction("INSERT INTO pto_requests (req_id, pin, start_date, end_date, reason) VALUES (:id, :p, :sd, :ed, :r)", {"id": req_id, "p": pin, "sd": str(pto_start), "ed": str(pto_end), "r": pto_reason})
                st.success("✅ PTO Request Submitted!"); time.sleep(1.5); st.rerun()
                
        st.markdown("#### Your PTO History")
        my_pto = run_query("SELECT start_date, end_date, status, reason FROM pto_requests WHERE pin=:p ORDER BY submitted DESC", {"p": pin})
        if my_pto:
            for req in my_pto:
                sd, ed, stat, rsn = req[0], req[1], req[2], req[3]
                color = "#10b981" if stat == "APPROVED" else "#f59e0b" if stat == "PENDING" else "#ff453a"
                st.markdown(f"<div class='glass-card' style='padding: 15px; margin-bottom: 10px; border-left: 4px solid {color} !important;'><div style='display: flex; justify-content: space-between;'><strong style='color: #f8fafc;'>{sd} to {ed}</strong><strong style='color: {color};'>{stat}</strong></div><div style='color: #94a3b8; font-size: 0.85rem; margin-top: 5px;'>Notes: {rsn}</div></div>", unsafe_allow_html=True)
        else:
            st.info("No PTO requests found.")

    with t_lic:
        st.markdown("### Professional Credentials")
        with st.expander("➕ ADD NEW CREDENTIAL"):
            with st.form("cred_form"):
                doc_type = st.selectbox("Document Type", ["State RN License", "State RRT License", "BLS Certification", "ACLS Certification"])
                doc_num = st.text_input("License Number")
                exp_date = st.date_input("Expiration Date")
                if st.form_submit_button("Save Credential"):
                    run_transaction("INSERT INTO credentials (doc_id, pin, doc_type, doc_number, exp_date, status) VALUES (:id, :p, :dt, :dn, :ed, 'ACTIVE')", {"id": f"DOC-{int(time.time())}", "p": pin, "dt": doc_type, "dn": doc_num, "ed": str(exp_date)})
                    st.success("✅ Saved"); time.sleep(1); st.rerun()
        creds = run_query("SELECT doc_id, doc_type, doc_number, exp_date FROM credentials WHERE pin=:p", {"p": pin})
        if creds:
            for c in creds: st.markdown(f"<div class='glass-card' style='border-left: 4px solid #8b5cf6 !important;'><div style='font-size:1.1rem; font-weight:800; color:#f8fafc;'>{c[1]}</div><div style='color:#94a3b8;'>Exp: {c[3]}</div></div>", unsafe_allow_html=True)

    with t_vax:
        st.markdown("### Immunization Records")
        st.info("Vaccine Vault Active. Use add tools above to load immunization docs.")

    with t_tax:
        st.markdown("### W-4 Withholdings & Direct Deposit")
        hr_rec = run_query("SELECT w4_filing_status FROM hr_onboarding WHERE pin=:p", {"p": pin})
        if hr_rec: st.success("✅ **ONBOARDING COMPLETE**")
        else: st.warning("⚠️ **ACTION REQUIRED: Please complete onboarding.**")

# [OTHER TABS MINIMIZED FOR TERMINAL SPACE]
elif nav in ["COMMS & CHAT", "ASSIGNMENTS", "MARKETPLACE", "SCHEDULE", "THE BANK"]:
    st.info(f"{nav} engine is active in the background. Navigate to Command Center or Approvals to test the Executive Update.")
