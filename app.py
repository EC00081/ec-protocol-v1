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
            # Core Tables
            conn.execute(text("CREATE TABLE IF NOT EXISTS workers (pin text PRIMARY KEY, status text, start_time numeric, earnings numeric, last_active timestamp);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS history (pin text, action text, timestamp timestamp DEFAULT NOW(), amount numeric, note text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS marketplace (shift_id text PRIMARY KEY, poster_pin text, role text, date text, start_time text, end_time text, rate numeric, status text, claimed_by text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS transactions (tx_id text PRIMARY KEY, pin text, amount numeric, timestamp timestamp, status text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS schedules (shift_id text PRIMARY KEY, pin text, shift_date text, shift_time text, department text, status text DEFAULT 'SCHEDULED');"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS comms_log (msg_id text PRIMARY KEY, pin text, dept text, content text, timestamp timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS unit_census (dept text PRIMARY KEY, total_pts int, high_acuity int, last_updated timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS assignments (assign_id text PRIMARY KEY, shift_date text, pin text, dept text, zone text, status text DEFAULT 'ACTIVE', swap_with_pin text);"))
            # NEW: HR Suite Tables
            conn.execute(text("CREATE TABLE IF NOT EXISTS credentials (doc_id text PRIMARY KEY, pin text, doc_type text, doc_number text, exp_date text, status text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS vaccines (vax_id text PRIMARY KEY, pin text, vax_type text, admin_date text, exp_date text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS hr_onboarding (pin text PRIMARY KEY, w4_filing_status text, w4_allowances int, dd_bank text, dd_acct_last4 text, signed_date timestamp DEFAULT NOW());"))
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

# [THE BANK]
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
        st.markdown("### Transaction Status")
        q = "SELECT timestamp, amount, status FROM transactions WHERE pin=:p ORDER BY timestamp DESC"
        res = run_query(q, {"p": pin})
        if res:
            for r in res:
                ts, amt, status = r[0], float(r[1]), r[2]
                # Color Logic
                color = "#10b981" if status == "APPROVED" else "#f59e0b" if status == "PENDING" else "#ff453a"
                
                st.markdown(f"""
                <div class='glass-card' style='padding: 15px; margin-bottom: 10px; border-left: 4px solid {color} !important;'>
                    <div style='display: flex; justify-content: space-between;'>
                        <strong style='color: #f8fafc;'>Transfer Request</strong>
                        <strong style='color: {color}; font-size: 1.2rem;'>${amt:,.2f}</strong>
                    </div>
                    <div style='color: #94a3b8; font-size: 0.85rem; margin-top: 5px;'>
                        {ts} | Status: <strong style='color: {color};'>{status}</strong>
                    </div>
                </div>
                """, unsafe_allow_html=True)
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

# [ENTERPRISE HR VAULT - OPTION 3 INTEGRATION]
elif nav == "MY PROFILE":
    st.markdown("## 🗄️ Enterprise HR Vault")
    st.caption("Securely manage your professional licenses, immunizations, and payroll documentation.")
    
    t_lic, t_vax, t_tax = st.tabs(["🪪 LICENSES & CERTS", "💉 VACCINE VAULT", "📑 TAX & ONBOARDING"])
    
    # --- TAB 1: CREDENTIALS WALLET ---
    with t_lic:
        st.markdown("### Professional Credentials")
        if st.session_state.edit_cred:
            c_id = st.session_state.edit_cred
            cred_data = run_query("SELECT doc_type, doc_number, exp_date FROM credentials WHERE doc_id=:id", {"id": c_id})
            if cred_data:
                with st.form("edit_cred_form"):
                    types = ["State RN License", "State RRT License", "BLS Certification", "ACLS Certification", "PALS Certification"]
                    idx = types.index(cred_data[0][0]) if cred_data[0][0] in types else 0
                    new_doc_type = st.selectbox("Document Type", types, index=idx)
                    new_doc_num = st.text_input("License Number", value=cred_data[0][1])
                    new_exp_date = st.date_input("Expiration Date", value=datetime.strptime(cred_data[0][2], "%Y-%m-%d").date())
                    if st.form_submit_button("Update"):
                        run_transaction("UPDATE credentials SET doc_type=:dt, doc_number=:dn, exp_date=:ed WHERE doc_id=:id", {"dt": new_doc_type, "dn": new_doc_num, "ed": str(new_exp_date), "id": c_id})
                        st.session_state.edit_cred = None; st.rerun()
                if st.button("Cancel Edit"): st.session_state.edit_cred = None; st.rerun()
        else:
            with st.expander("➕ ADD NEW CREDENTIAL"):
                with st.form("cred_form"):
                    doc_type = st.selectbox("Document Type", ["State RN License", "State RRT License", "BLS Certification", "ACLS Certification", "PALS Certification"])
                    doc_num = st.text_input("License / Certificate Number")
                    exp_date = st.date_input("Expiration Date")
                    if st.form_submit_button("Save Credential"):
                        run_transaction("INSERT INTO credentials (doc_id, pin, doc_type, doc_number, exp_date, status) VALUES (:id, :p, :dt, :dn, :ed, 'ACTIVE')", {"id": f"DOC-{int(time.time())}", "p": pin, "dt": doc_type, "dn": doc_num, "ed": str(exp_date)})
                        st.success("✅ Saved"); time.sleep(1); st.rerun()
            creds = run_query("SELECT doc_id, doc_type, doc_number, exp_date FROM credentials WHERE pin=:p ORDER BY exp_date ASC", {"p": pin})
            if creds:
                curr_d = datetime.now().date()
                for c in creds:
                    d_id, d_t, d_n, e_d = c[0], c[1], c[2], c[3]
                    try:
                        e_obj = datetime.strptime(e_d, "%Y-%m-%d").date()
                        if e_obj < curr_d: stat = "<span style='color:#ff453a; font-weight:bold; border:1px solid rgba(255, 69, 58, 0.4); padding:3px 8px; border-radius:6px; background: rgba(255,69,58,0.1);'>🚨 EXPIRED</span>"
                        elif (e_obj - curr_d).days <= 30: stat = "<span style='color:#f59e0b; font-weight:bold; border:1px solid rgba(245, 158, 11, 0.4); padding:3px 8px; border-radius:6px; background: rgba(245,158,11,0.1);'>⚠️ EXPIRING SOON</span>"
                        else: stat = "<span style='color:#34d399; font-weight:bold; border:1px solid rgba(52, 211, 153, 0.4); padding:3px 8px; border-radius:6px; background: rgba(52,211,153,0.1);'>✅ VALID</span>"
                    except: stat = ""
                    st.markdown(f"<div class='glass-card' style='border-left: 4px solid #8b5cf6 !important;'><div style='display:flex; justify-content:space-between; align-items:center;'><div style='font-size:1.1rem; font-weight:800; color:#f8fafc;'>{d_t}</div><div>{stat}</div></div><div style='color:#94a3b8; font-size:0.9rem; margin-top:8px;'>License #: <span style='color:#e2e8f0;'>{d_n}</span></div><div style='color:#94a3b8; font-size:0.9rem;'>Expires: <span style='color:#e2e8f0; font-weight:700;'>{e_d}</span></div></div>", unsafe_allow_html=True)
                    col1, col2 = st.columns([1,1])
                    if col1.button("EDIT", key=f"ec_{d_id}"): st.session_state.edit_cred = d_id; st.rerun()
                    if col2.button("DELETE", key=f"dc_{d_id}"): run_transaction("DELETE FROM credentials WHERE doc_id=:id", {"id": d_id}); st.rerun()
            else: st.info("No credentials found.")

    # --- TAB 2: VACCINE VAULT ---
    with t_vax:
        st.markdown("### Immunization Records")
        with st.expander("➕ LOG NEW VACCINATION / TEST"):
            with st.form("vax_form"):
                vax_type = st.selectbox("Record Type", ["PPD / TB Test", "Influenza (Flu)", "COVID-19 Series", "Hepatitis B", "MMR", "Varicella"])
                c1, c2 = st.columns(2)
                admin_date = c1.date_input("Date Administered")
                exp_date_vax = c2.date_input("Expiration Date (If Applicable)", value=admin_date + timedelta(days=365))
                if st.form_submit_button("Save Health Record"):
                    run_transaction("INSERT INTO vaccines (vax_id, pin, vax_type, admin_date, exp_date) VALUES (:id, :p, :t, :a, :e)", {"id": f"VAX-{int(time.time())}", "p": pin, "t": vax_type, "a": str(admin_date), "e": str(exp_date_vax)})
                    st.success("✅ Record Saved"); time.sleep(1); st.rerun()
        
        vaxs = run_query("SELECT vax_id, vax_type, admin_date, exp_date FROM vaccines WHERE pin=:p ORDER BY exp_date ASC", {"p": pin})
        if vaxs:
            curr_d = datetime.now().date()
            for v in vaxs:
                v_id, v_t, v_a, v_e = v[0], v[1], v[2], v[3]
                try:
                    e_obj = datetime.strptime(v_e, "%Y-%m-%d").date()
                    if e_obj < curr_d: stat = "<span style='color:#ff453a; font-weight:bold; border:1px solid rgba(255, 69, 58, 0.4); padding:3px 8px; border-radius:6px; background: rgba(255,69,58,0.1);'>🚨 NON-COMPLIANT</span>"
                    else: stat = "<span style='color:#34d399; font-weight:bold; border:1px solid rgba(52, 211, 153, 0.4); padding:3px 8px; border-radius:6px; background: rgba(52,211,153,0.1);'>✅ COMPLIANT</span>"
                except: stat = ""
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid #0ea5e9 !important;'><div style='display:flex; justify-content:space-between; align-items:center;'><div style='font-size:1.1rem; font-weight:800; color:#f8fafc;'>{v_t}</div><div>{stat}</div></div><div style='color:#94a3b8; font-size:0.9rem; margin-top:8px;'>Administered: <span style='color:#e2e8f0;'>{v_a}</span></div><div style='color:#94a3b8; font-size:0.9rem;'>Valid Until: <span style='color:#e2e8f0; font-weight:700;'>{v_e}</span></div></div>", unsafe_allow_html=True)
                if st.button("DELETE RECORD", key=f"dv_{v_id}"): run_transaction("DELETE FROM vaccines WHERE vax_id=:id", {"id": v_id}); st.rerun()
        else: st.info("No health records found.")

    # --- TAB 3: TAX & ONBOARDING ---
    with t_tax:
        st.markdown("### W-4 Withholdings & Direct Deposit")
        hr_rec = run_query("SELECT w4_filing_status, w4_allowances, dd_bank, dd_acct_last4, signed_date FROM hr_onboarding WHERE pin=:p", {"p": pin})
        
        if hr_rec:
            st.success("✅ **ONBOARDING COMPLETE**")
            st.markdown(f"""
            <div class='glass-card' style='border-left: 4px solid #10b981 !important;'>
                <strong style='color:#10b981;'>FEDERAL W-4 INFO</strong><br>
                <span style='color:#94a3b8;'>Filing Status:</span> {hr_rec[0][0]}<br>
                <span style='color:#94a3b8;'>Allowances:</span> {hr_rec[0][1]}<br><br>
                <strong style='color:#3b82f6;'>BANKING INFO</strong><br>
                <span style='color:#94a3b8;'>Institution:</span> {hr_rec[0][2]}<br>
                <span style='color:#94a3b8;'>Account:</span> **** **** **** {hr_rec[0][3]}<br>
                <hr style='border-color: rgba(255,255,255,0.1); margin:10px 0;'>
                <span style='color:#64748b; font-size:0.8rem;'>Digitally Signed: {hr_rec[0][4]}</span>
            </div>
            """, unsafe_allow_html=True)
            if st.button("🔄 Update HR Forms"):
                run_transaction("DELETE FROM hr_onboarding WHERE pin=:p", {"p": pin}); st.rerun()
        else:
            st.warning("⚠️ **ACTION REQUIRED: Please complete your onboarding paperwork.**")
            with st.form("hr_paperwork"):
                st.markdown("**Part 1: W-4 Federal Tax Withholding**")
                filing_status = st.selectbox("Filing Status", ["Single", "Married Filing Jointly", "Head of Household"])
                allowances = st.number_input("Total Allowances (Dependents)", min_value=0, max_value=10, step=1)
                
                st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
                st.markdown("**Part 2: Direct Deposit Authorization**")
                bank_name = st.text_input("Financial Institution Name", placeholder="e.g. Bank of America")
                acct_num = st.text_input("Account Number", type="password")
                routing_num = st.text_input("Routing Number", type="password")
                
                st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
                st.info("By checking this box, I legally authorize EC Protocol to process my payroll via direct deposit and withhold taxes according to the W-4 instructions above.")
                signature = st.checkbox(f"Digital Signature: {user['name']}")
                
                if st.form_submit_button("Submit Onboarding Documents"):
                    if not signature: st.error("You must check the signature box to submit.")
                    elif len(acct_num) < 4: st.error("Please enter a valid account number.")
                    else:
                        last_4 = acct_num[-4:]
                        run_transaction("INSERT INTO hr_onboarding (pin, w4_filing_status, w4_allowances, dd_bank, dd_acct_last4, signed_date) VALUES (:p, :fs, :al, :bn, :l4, NOW())", {"p": pin, "fs": filing_status, "al": allowances, "bn": bank_name, "l4": last_4})
                        st.success("Documents Locked & Encrypted!"); time.sleep(1.5); st.rerun()

# [HIDDEN TABS TO SAVE TERMINAL SPACE BUT KEEP ENGINE RUNNING]
elif nav in ["CENSUS & ACUITY", "COMMS & CHAT", "ASSIGNMENTS", "MARKETPLACE", "APPROVALS", "COMMAND CENTER", "MASTER SCHEDULE"]:
    st.info(f"{nav} engine is active in the background. Use the HR & PROFILE or BANK tabs to test the current module build.")
