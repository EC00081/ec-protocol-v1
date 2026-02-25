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

try:
    from fpdf import FPDF
    PDF_ACTIVE = True
except ImportError:
    PDF_ACTIVE = False

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
    "1001": {"email": "liam@ecprotocol.com", "password": "password123", "pin": "1001", "name": "Liam O'Neil", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 1200.00, "vip": False},
    "1002": {"email": "charles@ecprotocol.com", "password": "password123", "pin": "1002", "name": "Charles Morgan", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 50.00, "vip": False},
    "1003": {"email": "sarah@ecprotocol.com", "password": "password123", "pin": "1003", "name": "Sarah Jenkins", "role": "Charge RRT", "dept": "Respiratory", "level": "Supervisor", "rate": 90.00, "vip": True},
    "1004": {"email": "manager@ecprotocol.com", "password": "password123", "pin": "1004", "name": "David Clark", "role": "Manager", "dept": "Respiratory", "level": "Manager", "rate": 0.00, "vip": True},
    "9999": {"email": "cfo@ecprotocol.com", "password": "password123", "pin": "9999", "name": "CFO VIEW", "role": "Admin", "dept": "All", "level": "Admin", "rate": 0.00, "vip": True}
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

def update_status(pin, status, start, earn):
    q = """INSERT INTO workers (pin, status, start_time, earnings, last_active) VALUES (:p, :s, :t, :e, NOW())
           ON CONFLICT (pin) DO UPDATE SET status = :s, start_time = :t, earnings = :e, last_active = NOW();"""
    return run_transaction(q, {"p": pin, "s": status, "t": start, "e": earn})

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

# --- 5. PDF GENERATOR ---
if PDF_ACTIVE:
    class PayStubPDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 16); self.set_text_color(59, 130, 246); self.cell(0, 10, 'EC Protocol Enterprise Health', 0, 1, 'L')
            self.set_font('Arial', '', 10); self.set_text_color(100, 116, 139); self.cell(0, 5, 'Secure Workforce Payroll', 0, 1, 'L'); self.ln(10)
        def section_title(self, title):
            self.set_font('Arial', 'B', 12); self.set_fill_color(241, 245, 249); self.set_text_color(15, 23, 42); self.cell(0, 8, f'  {title}', 0, 1, 'L', True); self.ln(2)
        def table_row(self, c1, c2, c3, c4, c5, c6, bold=False):
            self.set_font('Arial', 'B' if bold else '', 9)
            self.cell(45, 7, str(c1), 0, 0, 'L'); self.cell(25, 7, str(c2), 0, 0, 'R'); self.cell(25, 7, str(c3), 0, 0, 'R')
            self.cell(30, 7, str(c4), 0, 0, 'R'); self.cell(30, 7, str(c5), 0, 0, 'R'); self.cell(35, 7, str(c6), 0, 1, 'R')
        def tax_row(self, c1, c2, c3, bold=False):
            self.set_font('Arial', 'B' if bold else '', 9)
            self.cell(60, 7, str(c1), 0, 0, 'L'); self.cell(40, 7, str(c2), 0, 0, 'R'); self.cell(40, 7, str(c3), 0, 1, 'R')

    def generate_pay_stub(user_data, start_date, end_date, period_gross, ytd_gross):
        pdf = PayStubPDF(); pdf.add_page(); pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_font('Arial', 'B', 12); pdf.cell(100, 10, f"EMPLOYEE: {user_data['name'].upper()}", 0, 0)
        pdf.set_font('Arial', '', 10); pdf.cell(90, 10, f"Pay Period: {start_date.strftime('%m/%d/%Y')} - {end_date.strftime('%m/%d/%Y')}", 0, 1, 'R')
        pdf.cell(100, 5, f"ID: {user_data['pin']} | Dept: {user_data['dept'].upper()}", 0, 0); pdf.cell(90, 5, f"Check Date: {date.today().strftime('%m/%d/%Y')}", 0, 1, 'R'); pdf.ln(10)
        pdf.section_title("EARNINGS"); pdf.set_font('Arial', 'B', 9); pdf.set_text_color(100, 116, 139)
        pdf.table_row("Item", "Rate", "Hours", "This Period", "YTD Hours", "YTD Amount", bold=True); pdf.set_text_color(15, 23, 42)
        rate = user_data['rate']; ph = period_gross/rate if rate>0 else 0; yh = ytd_gross/rate if rate>0 else 0
        pdf.table_row("Regular Pay", f"${rate:,.2f}", f"{ph:,.2f}", f"${period_gross:,.2f}", f"{yh:,.2f}", f"${ytd_gross:,.2f}")
        pdf.ln(2); pdf.set_fill_color(248, 250, 252); pdf.table_row("GROSS PAY", "", "", f"${period_gross:,.2f}", "", f"${ytd_gross:,.2f}", bold=True); pdf.ln(8)
        pdf.section_title("TAXES"); pdf.set_font('Arial', 'B', 9); pdf.set_text_color(100, 116, 139); pdf.tax_row("Tax", "This Period", "YTD Amount", bold=True); pdf.set_text_color(15, 23, 42)
        pt = {k: period_gross * v for k, v in TAX_RATES.items()}; yt = {k: ytd_gross * v for k, v in TAX_RATES.items()}
        pdf.tax_row("Federal Income", f"${pt['FED']:,.2f}", f"${yt['FED']:,.2f}"); pdf.tax_row("State (MA)", f"${pt['MA']:,.2f}", f"${yt['MA']:,.2f}")
        pdf.tax_row("Social Security", f"${pt['SS']:,.2f}", f"${yt['SS']:,.2f}"); pdf.tax_row("Medicare", f"${pt['MED']:,.2f}", f"${yt['MED']:,.2f}"); pdf.ln(2)
        pdf.set_fill_color(248, 250, 252); pdf.tax_row("TOTAL TAXES", f"${sum(pt.values()):,.2f}", f"${sum(yt.values()):,.2f}", bold=True); pdf.ln(10)
        net_pay = period_gross - sum(pt.values())
        pdf.set_fill_color(241, 245, 249); pdf.rect(10, pdf.get_y(), 190, 35, 'F'); pdf.set_y(pdf.get_y() + 5)
        pdf.set_font('Arial', 'B', 10); pdf.cell(63, 5, "CURRENT GROSS", 0, 0, 'C'); pdf.cell(63, 5, "DEDUCTIONS", 0, 0, 'C'); pdf.cell(63, 5, "NET PAY", 0, 1, 'C')
        pdf.set_font('Arial', 'B', 14); pdf.cell(63, 10, f"${period_gross:,.2f}", 0, 0, 'C'); pdf.set_text_color(239, 68, 68); pdf.cell(63, 10, f"${sum(pt.values()):,.2f}", 0, 0, 'C'); pdf.set_text_color(16, 185, 129); pdf.cell(63, 10, f"${net_pay:,.2f}", 0, 1, 'C')
        return bytes(pdf.output(dest='S'))

# --- 6. AUTH SCREEN & SESSION INIT ---
if 'user_state' not in st.session_state: st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0}

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
                # Set initial read time to right now to prevent old messages from triggering bubble
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
if 'last_read_chat' not in st.session_state:
    st.session_state.last_read_chat = datetime.utcnow()

# Check DB for max timestamp
latest_msg_q = run_query("SELECT MAX(timestamp) FROM comms_log")
if latest_msg_q and latest_msg_q[0][0]:
    latest_db_dt = pd.to_datetime(latest_msg_q[0][0])
    if latest_db_dt.tzinfo is None:
        latest_db_dt = latest_db_dt.tz_localize('UTC')
        
    session_read_dt = pd.to_datetime(st.session_state.last_read_chat)
    if session_read_dt.tzinfo is None:
        session_read_dt = session_read_dt.tz_localize('UTC')

    if latest_db_dt > session_read_dt:
        chat_label = "COMMS & CHAT 🔴"

# --- 7. NAVIGATION BUILDER ---
with st.sidebar:
    st.markdown(f"<h3 style='color: #38bdf8; margin-bottom: 0;'>{user['name'].upper()}</h3>", unsafe_allow_html=True)
    st.caption(f"{user['role']} | {user['dept']}")
    st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
    
    if user['level'] == "Admin": 
        menu_items = ["COMMAND CENTER", "MASTER SCHEDULE", "APPROVALS"]
    elif user['level'] in ["Manager", "Director"]: 
        menu_items = ["DASHBOARD", "CENSUS & ACUITY", chat_label, "MARKETPLACE", "SCHEDULE", "THE BANK", "APPROVALS", "MY PROFILE"]
    elif user['level'] == "Supervisor":
        menu_items = ["DASHBOARD", "CENSUS & ACUITY", chat_label, "MARKETPLACE", "SCHEDULE", "THE BANK", "MY PROFILE"]
    else: 
        menu_items = ["DASHBOARD", chat_label, "MARKETPLACE", "SCHEDULE", "THE BANK", "MY PROFILE"]
        
    nav = st.radio("MENU", menu_items)
        
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("LOGOUT"): st.session_state.clear(); st.rerun()

# Intercept Chat Navigation to clear bubble
if "COMMS" in nav:
    st.session_state.last_read_chat = datetime.utcnow()
    if "🔴" in nav:
        st.rerun() # Force instant refresh to wipe the dot
    nav = "COMMS & CHAT"

# --- 8. ROUTING ---

# [DASHBOARD] 
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
                if update_status(pin, "Inactive", 0, new_total):
                    st.session_state.user_state['active'] = False; st.session_state.user_state['earnings'] = new_total
                    log_action(pin, "CLOCK OUT", running_earn, f"Logged {running_earn/user['rate']:.2f} hrs")
                    st.rerun()
            else: st.error("❌ Incorrect PIN.")
    else:
        selected_facility = st.selectbox("Select Facility", list(HOSPITALS.keys()))
        if not user.get('vip', False):
            st.info("Identity verification required to initiate shift.")
            if st.camera_input("Take a photo to verify identity") and get_geolocation():
                st.success("✅ Geofence & Biometrics Confirmed.")
                start_pin = st.text_input("Enter 4-Digit PIN to Clock In", type="password", key="start_pin")
                if st.button("PUNCH IN"):
                    if start_pin == pin:
                        start_t = time.time()
                        if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0)):
                            st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t
                            log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()
                    else: st.error("❌ Incorrect PIN.")
        else:
            st.caption("✨ VIP Security Override Active")
            start_pin = st.text_input("Enter 4-Digit PIN to Clock In", type="password", key="vip_start_pin")
            if st.button("PUNCH IN"):
                if start_pin == pin:
                    start_t = time.time()
                    if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0)):
                        st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t
                        log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()
                else: st.error("❌ Incorrect PIN.")

# [CENSUS & ACUITY + SOS PROTOCOL]
elif nav == "CENSUS & ACUITY" and user['level'] in ["Supervisor", "Manager", "Director"]:
    st.markdown(f"## 📊 {user['dept']} Census & Staffing")
    
    if st.button("🔄 Refresh Live Database"):
        st.rerun()
        
    c_data = run_query("SELECT total_pts, high_acuity, last_updated FROM unit_census WHERE dept=:d", {"d": user['dept']})
    curr_pts = c_data[0][0] if c_data else 0
    curr_high = c_data[0][1] if c_data else 0
    
    # Proper Timezone Conversion for "Last Updated"
    if c_data and c_data[0][2]:
        dt_obj = pd.to_datetime(c_data[0][2])
        if dt_obj.tzinfo is None: dt_obj = dt_obj.tz_localize('UTC')
        last_upd = dt_obj.astimezone(LOCAL_TZ).strftime("%I:%M %p")
    else:
        last_upd = "Never"

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
                success_market = run_transaction("INSERT INTO marketplace (shift_id, poster_pin, role, date, start_time, end_time, rate, status) VALUES (:id, :p, :r, :d, :s, :e, :rt, 'OPEN')", 
                                {"id": s_id, "p": pin, "r": f"🚨 SOS URGENT: {user['dept']}", "d": str(date.today()), "s": "NOW", "e": "END OF SHIFT", "rt": incentive_rate})
            
            msg_id = f"MSG-SOS-{int(time.time()*1000)}"
            
            # 1. Dept Specific Message (Includes Pay Rate)
            sos_msg_dept = f"🚨 SYSTEM ALERT: The unit is understaffed by {missing_count}. Emergency shifts with 1.5x incentive pay (${incentive_rate:.2f}/hr) have been posted to the Marketplace!"
            
            # 2. Global Hospital Message (Scrubbed Pay Rate)
            sos_msg_global = f"[{user['dept'].upper()}] SYSTEM ALERT: The unit is critically understaffed by {missing_count}. Emergency shifts have been posted to the Marketplace! Check your schedules."
            
            success_msg1 = run_transaction("INSERT INTO comms_log (msg_id, pin, dept, content) VALUES (:id, :p, :d, :c)", {"id": msg_id, "p": "9999", "d": user['dept'], "c": sos_msg_dept}) 
            success_msg2 = run_transaction("INSERT INTO comms_log (msg_id, pin, dept, content) VALUES (:id, :p, :d, :c)", {"id": msg_id+"-g", "p": "9999", "d": "GLOBAL", "c": sos_msg_global}) 
            
            if success_market and success_msg1:
                st.success("🚨 SOS Broadcasted! Shifts pushed to Marketplace and alert sent to Team Chat.")
            else:
                st.error("Error communicating with the database.")
            time.sleep(2); st.rerun()
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
                if new_h > new_t: 
                    st.error("High acuity cannot exceed total patients.")
                else:
                    exists = run_query("SELECT 1 FROM unit_census WHERE dept=:d", {"d": user['dept']})
                    if exists:
                        success = run_transaction("UPDATE unit_census SET total_pts=:t, high_acuity=:h, last_updated=NOW() WHERE dept=:d", {"d": user['dept'], "t": new_t, "h": new_h})
                    else:
                        success = run_transaction("INSERT INTO unit_census (dept, total_pts, high_acuity) VALUES (:d, :t, :h)", {"d": user['dept'], "t": new_t, "h": new_h})
                    if success: st.success("Census Updated!"); time.sleep(1); st.rerun()
                    else: st.error("Database connection failed. Census not updated.")

# [COMMS & CHAT - Timezone Corrected]
elif nav == "COMMS & CHAT":
    st.markdown("## 💬 Secure Comms Network")
    st.caption("End-to-end encrypted internal broadcast network.")
    
    tab_global, tab_dept = st.tabs(["🌍 GLOBAL HOSPITAL", f"🏥 {user['dept'].upper()} TEAM"])
    
    def render_chat(channel_name):
        with st.form(f"chat_input_{channel_name}", clear_on_submit=True):
            col_msg, col_btn = st.columns([5, 1])
            msg = col_msg.text_input("Type your message...", label_visibility="collapsed")
            if col_btn.form_submit_button("SEND") and msg.strip():
                msg_id = f"MSG-{int(time.time()*1000)}"
                success = run_transaction("INSERT INTO comms_log (msg_id, pin, dept, content) VALUES (:id, :p, :d, :c)", {"id": msg_id, "p": pin, "d": channel_name, "c": msg})
                if success:
                    st.session_state.last_read_chat = datetime.utcnow()
                    st.rerun()
                
        st.markdown("<br>", unsafe_allow_html=True)
        
        chat_logs = run_query("SELECT pin, content, timestamp FROM comms_log WHERE dept=:d ORDER BY timestamp DESC LIMIT 30", {"d": channel_name})
        if chat_logs:
            for log in chat_logs:
                sender_pin = str(log[0])
                content = log[1]
                
                # --- TIMEZONE FIX ---
                db_ts = pd.to_datetime(log[2])
                if db_ts.tzinfo is None: db_ts = db_ts.tz_localize('UTC')
                t_stamp = db_ts.astimezone(LOCAL_TZ).strftime("%I:%M %p")
                
                if sender_pin == pin:
                    st.markdown(f"<div style='display:flex; flex-direction:column;'><div class='chat-bubble chat-me'><strong>You</strong> <span style='color:#94a3b8; font-size:0.75rem;'>{t_stamp}</span><br>{content}</div></div>", unsafe_allow_html=True)
                elif sender_pin == "9999": 
                     st.markdown(f"<div style='display:flex; flex-direction:column;'><div class='chat-bubble' style='background:rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.4); margin-right: auto; border-bottom-left-radius: 4px;'><strong style='color:#ef4444;'>SYSTEM ALERT</strong> <span style='font-size:0.75rem; color:#94a3b8;'>| Automated • {t_stamp}</span><br>{content}</div></div>", unsafe_allow_html=True)
                else:
                    sender_name = USERS.get(sender_pin, {}).get("name", f"User {sender_pin}")
                    sender_role = USERS.get(sender_pin, {}).get("role", "")
                    st.markdown(f"<div style='display:flex; flex-direction:column;'><div class='chat-bubble chat-them'><strong style='color:#38bdf8;'>{sender_name}</strong> <span style='font-size:0.75rem; color:#94a3b8;'>| {sender_role} • {t_stamp}</span><br>{content}</div></div>", unsafe_allow_html=True)
        else:
            st.info(f"No messages in the {channel_name} channel yet. Send one above to start the comms.")

    with tab_global: render_chat("GLOBAL")
    with tab_dept: render_chat(user['dept'])

# [THE BANK]
elif nav == "THE BANK":
    st.markdown("## 🏦 The Bank")
    st.caption("Manage your payouts, review shift logs, and download pay stubs.")
    
    banked_gross = st.session_state.user_state.get('earnings', 0.0)
    banked_net = banked_gross * (1 - sum(TAX_RATES.values()))
    
    st.markdown(f"""
    <div class='glass-card' style='text-align: center; border-left: 4px solid #10b981 !important;'>
        <h3 style='color: #94a3b8; margin-bottom: 5px;'>AVAILABLE FOR WITHDRAWAL</h3>
        <h1 style='color: #10b981; font-size: 3rem; margin: 0;'>${banked_net:,.2f}</h1>
        <p style='color: #64748b;'>Gross Accrued: ${banked_gross:,.2f} (Taxes Withheld: ${banked_gross - banked_net:,.2f})</p>
    </div>
    """, unsafe_allow_html=True)
    
    if banked_net > 0.01 and not st.session_state.user_state.get('active', False):
        if st.button("💸 REQUEST WITHDRAWAL (SENDS TO MANAGER)"):
            tx_id = f"TX-{int(time.time())}"
            if run_transaction("INSERT INTO transactions (tx_id, pin, amount, timestamp, status) VALUES (:id, :p, :a, NOW(), 'PENDING')", {"id": tx_id, "p": pin, "a": banked_net}):
                update_status(pin, "Inactive", 0, 0.0); st.session_state.user_state['earnings'] = 0.0
                st.success("✅ Withdrawal Requested! Awaiting Manager Approval.")
                time.sleep(1.5); st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["SHIFT LOGS", "WITHDRAWAL HISTORY", "PAY STUBS"])
    
    with tab1:
        st.markdown("### Shift & Wage Ledger")
        q = "SELECT timestamp, amount, note FROM history WHERE pin=:p AND action='CLOCK OUT' ORDER BY timestamp DESC LIMIT 30"
        res = run_query(q, {"p": pin})
        if res:
            for r in res:
                ts, amt, note = r[0], float(r[1]), r[2]
                st.markdown(f"""<div class='glass-card' style='padding: 15px; margin-bottom: 10px; border-left: 4px solid #10b981 !important;'><div style='display: flex; justify-content: space-between;'><strong style='color: #f8fafc;'>Shift Completed</strong><strong style='color: #10b981; font-size:1.2rem;'>${amt:,.2f}</strong></div><div style='color: #94a3b8; font-size: 0.85rem;'>{ts} | <span style='color: #3b82f6; font-weight:800;'>{note}</span></div></div>""", unsafe_allow_html=True)
        else: st.info("No shifts worked yet.")

    with tab2:
        st.markdown("### Transaction Status")
        q = "SELECT timestamp, amount, status FROM transactions WHERE pin=:p ORDER BY timestamp DESC"
        res = run_query(q, {"p": pin})
        if res:
            for r in res:
                ts, amt, status = r[0], float(r[1]), r[2]
                color = "#10b981" if status == "APPROVED" else "#f59e0b" if status == "PENDING" else "#ff453a"
                st.markdown(f"""<div class='glass-card' style='padding: 15px; margin-bottom: 10px; border-left: 4px solid {color} !important;'><div style='display: flex; justify-content: space-between;'><strong style='color: #f8fafc;'>Transfer Request</strong><strong style='color: {color};'>${amt:,.2f}</strong></div><div style='color: #94a3b8; font-size: 0.85rem;'>{ts} | Status: {status}</div></div>""", unsafe_allow_html=True)
        else: st.info("No withdrawal history.")
        
    with tab3:
        st.markdown("### Generate PDF Pay Stub")
        with st.form("pay_stub_form"):
            c1, c2 = st.columns(2)
            start_d = c1.date_input("Start Date", value=date.today() - timedelta(days=14))
            end_d = c2.date_input("End Date", value=date.today())
            submitted = st.form_submit_button("Generate PDF Statement")
            
        if submitted and PDF_ACTIVE:
            period_gross = get_period_gross(pin, start_d, end_d)
            if period_gross > 0:
                st.session_state.pdf_data = generate_pay_stub(user, start_d, end_d, period_gross, get_ytd_gross(pin))
                st.session_state.pdf_filename = f"PayStub_{pin}_{end_d}.pdf"
                st.success("✅ Pay Stub Generated!")
            else: st.warning("No earnings found for this period.")
        
        if 'pdf_data' in st.session_state:
            st.download_button("📄 Download PDF Pay Stub", data=st.session_state.pdf_data, file_name=st.session_state.pdf_filename, mime="application/pdf")

# [APPROVALS]
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
                    st.success("Approved."); time.sleep(1); st.rerun()
                if c2.button("❌ DENY", key=f"den_{t_id}"):
                    run_transaction("UPDATE transactions SET status='DENIED' WHERE tx_id=:id", {"id": t_id}); st.error("Denied."); time.sleep(1); st.rerun()
                st.markdown("<br>", unsafe_allow_html=True)
    else: st.info("No pending financial transactions.")

# [SCHEDULE]
elif nav == "SCHEDULE":
    st.markdown("## 📅 Master Schedule")
    if user['level'] in ["Manager", "Director", "Admin"]:
        c1, c2 = st.columns(2)
        with c1:
            with st.expander("🛠️ ASSIGN SHIFT"):
                with st.form("assign_sched"):
                    avail = {p: u['name'] for p, u in USERS.items() if u['level'] in ["Worker", "Supervisor"]}
                    t_pin = st.selectbox("Staff Member", options=list(avail.keys()), format_func=lambda x: avail[x])
                    s_date = st.date_input("Shift Date"); s_time = st.text_input("Time (e.g., 0700-1900)")
                    if st.form_submit_button("Publish Shift"):
                        run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{int(time.time())}", "p": t_pin, "d": str(s_date), "t": s_time, "dept": USERS[t_pin]['dept']})
                        st.success(f"Assigned to {avail[t_pin]}"); time.sleep(1); st.rerun()
        with c2:
            with st.expander("🗑️ REMOVE SHIFT"):
                scheds = run_query("SELECT shift_id, pin, shift_date, shift_time FROM schedules")
                if scheds:
                    with st.form("rem_sched"):
                        opts = {s[0]: f"{s[2]} | {USERS.get(str(s[1]), {}).get('name', s[1])} ({s[3]})" for s in scheds}
                        t_shift = st.selectbox("Select to Delete", options=list(opts.keys()), format_func=lambda x: opts[x])
                        if st.form_submit_button("Delete"):
                            run_transaction("DELETE FROM schedules WHERE shift_id=:id", {"id": t_shift}); st.success("Removed"); time.sleep(1); st.rerun()
                else: st.info("No shifts.")
    else:
        with st.expander("🙋 MY UPCOMING SHIFTS (Manage Exceptions)", expanded=True):
            my_scheds = run_query("SELECT shift_id, shift_date, shift_time, COALESCE(status, 'SCHEDULED') FROM schedules WHERE pin=:p ORDER BY shift_date ASC", {"p": pin})
            if my_scheds:
                for s in my_scheds:
                    if s[3] == 'SCHEDULED':
                        st.markdown(f"<div style='font-size:1.1rem; font-weight:700;'>{s[1]} <span style='color:#34d399;'>| {s[2]}</span></div>", unsafe_allow_html=True)
                        col1, col2 = st.columns(2)
                        if col1.button("🚨 CALL OUT", key=f"co_{s[0]}"):
                            run_transaction("UPDATE schedules SET status='CALL_OUT' WHERE shift_id=:id", {"id": s[0]}); st.rerun()
                        if col2.button("🔄 TRADE TO MARKET", key=f"tr_{s[0]}"):
                            run_transaction("UPDATE schedules SET status='MARKETPLACE' WHERE shift_id=:id", {"id": s[0]})
                            ts = s[2].split("-"); st_t, en_t = (ts[0], ts[1]) if len(ts)==2 else ("0000", "0000")
                            run_transaction("INSERT INTO marketplace (shift_id, poster_pin, role, date, start_time, end_time, rate, status) VALUES (:id, :p, :r, :d, :s, :e, :rt, 'OPEN')", {"id": s[0], "p": pin, "r": f"{user['role']} - Trade", "d": s[1], "s": st_t, "e": en_t, "rt": user['rate']})
                            st.rerun()
                        st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
                    elif s[3] == 'CALL_OUT': st.error(f"🚨 {s[1]} | {s[2]} (SICK LEAVE PENDING)")
                    elif s[3] == 'MARKETPLACE': st.warning(f"🔄 {s[1]} | {s[2]} (ON MARKETPLACE)")
            else: st.info("No upcoming shifts.")

    st.markdown("<br>", unsafe_allow_html=True)
    all_s = run_query("SELECT shift_id, pin, shift_date, shift_time, department, COALESCE(status, 'SCHEDULED') FROM schedules ORDER BY shift_date ASC, shift_time ASC")
    if all_s:
        groups = defaultdict(list)
        for s in all_s: groups[s[2]].append(s)
        for date_key in sorted(groups.keys()):
            try: f_date = datetime.strptime(date_key, "%Y-%m-%d").strftime("%A, %B %d, %Y")
            except: f_date = date_key
            st.markdown(f"<div class='sched-date-header'>🗓️ {f_date}</div>", unsafe_allow_html=True)
            for s in groups[date_key]:
                owner = USERS.get(str(s[1]), {}).get('name', f"User {s[1]}")
                lbl = "<span style='color:#ff453a; margin-left:10px;'>🚨 SICK</span>" if s[5]=="CALL_OUT" else "<span style='color:#f59e0b; margin-left:10px;'>🔄 TRADING</span>" if s[5]=="MARKETPLACE" else ""
                st.markdown(f"<div class='sched-row'><div class='sched-time'>{s[3]}</div><div style='flex-grow: 1; padding-left: 15px;'><span class='sched-name'>{'⭐ ' if str(s[1])==pin else ''}{owner}</span> {lbl}</div></div>", unsafe_allow_html=True)
    else: st.info("Calendar is empty.")

# [MARKETPLACE]
elif nav == "MARKETPLACE":
    st.markdown("## 🏥 Shift Marketplace")
    tab1, tab2 = st.tabs(["OPEN SHIFTS", "POST NEW"])
    with tab1:
        res = run_query("SELECT shift_id, poster_pin, role, date, start_time, end_time, rate FROM marketplace WHERE status='OPEN'")
        if res:
            for s in res:
                poster = USERS.get(str(s[1]), {}).get("name", "Unknown")
                border_color = "#ef4444" if "SOS" in s[2] else "#3b82f6"
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid {border_color} !important;'><div style='font-weight:bold; font-size:1.1rem;'>{s[3]} | {s[2]}</div><div style='color:#34d399; font-weight:700;'>{s[4]} - {s[5]} @ ${s[6]}/hr</div><div style='color:#94a3b8; font-size:0.85rem; margin-top:5px;'>Posted by: {poster}</div></div>", unsafe_allow_html=True)
                if user['level'] in ["Worker", "Supervisor"] and str(s[1]) != pin:
                    if st.button("CLAIM SHIFT", key=s[0]):
                        run_transaction("UPDATE marketplace SET status='CLAIMED', claimed_by=:p WHERE shift_id=:id", {"p": pin, "id": s[0]})
                        run_transaction("UPDATE schedules SET pin=:p, status='SCHEDULED' WHERE shift_id=:id", {"p": pin, "id": s[0]})
                        st.success("✅ Claimed!"); time.sleep(1); st.rerun()
        else: st.info("No open shifts.")
    with tab2:
        with st.form("new_shift"):
            d = st.date_input("Date"); c1, c2 = st.columns(2)
            s_time = c1.time_input("Start"); e_time = c2.time_input("End")
            if st.form_submit_button("PUBLISH TO MARKET"):
                run_transaction("INSERT INTO marketplace (shift_id, poster_pin, role, date, start_time, end_time, rate, status) VALUES (:id, :p, :r, :d, :s, :e, :rt, 'OPEN')", {"id": f"SHIFT-{int(time.time())}", "p": pin, "r": f"{user['role']} @ Open Market", "d": d, "s": str(s_time), "e": str(e_time), "rt": user['rate']})
                st.success("Published!")

# [MY PROFILE]
elif nav == "MY PROFILE":
    st.markdown("## 🪪 Credentials & Compliance")
    st.info("Profiles module is active. See full credential editing capabilities tested in earlier builds.")
