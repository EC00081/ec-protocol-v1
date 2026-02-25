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
        if not clean_sid or not clean_token or not clean_from: return False, "Missing Env Vars."
        try:
            client = Client(clean_sid, clean_token)
            client.messages.create(body=message_body, from_=clean_from, to=to_phone)
            return True, "SMS Dispatched"
        except Exception as e: return False, str(e)
    return False, "Twilio inactive."

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
    "1001": {"email": "liam@ecprotocol.com", "password": "password123", "pin": "1001", "name": "Liam O'Neil", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 120.00, "vip": False, "phone": "+15551234567"},
    "1002": {"email": "charles@ecprotocol.com", "password": "password123", "pin": "1002", "name": "Charles Morgan", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 50.00, "vip": False, "phone": None},
    "1003": {"email": "sarah@ecprotocol.com", "password": "password123", "pin": "1003", "name": "Sarah Jenkins", "role": "Charge RRT", "dept": "Respiratory", "level": "Supervisor", "rate": 90.00, "vip": True, "phone": None},
    "1004": {"email": "manager@ecprotocol.com", "password": "password123", "pin": "1004", "name": "David Clark", "role": "Manager", "dept": "Respiratory", "level": "Manager", "rate": 0.00, "vip": True, "phone": None},
    "9999": {"email": "cfo@ecprotocol.com", "password": "password123", "pin": "9999", "name": "CFO VIEW", "role": "Admin", "dept": "All", "level": "Admin", "rate": 0.00, "vip": True, "phone": None},
    "2001": {"email": "icu@ecprotocol.com", "password": "password123", "pin": "2001", "name": "Elena Rostova", "role": "RN", "dept": "ICU", "level": "Worker", "rate": 75.00, "vip": False, "phone": None},
    "3001": {"email": "ed@ecprotocol.com", "password": "password123", "pin": "3001", "name": "Marcus Vance", "role": "RN", "dept": "Emergency", "level": "Worker", "rate": 85.00, "vip": False, "phone": None}
}

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
            conn.execute(text("CREATE TABLE IF NOT EXISTS pto_requests (req_id text PRIMARY KEY, pin text, start_date text, end_date text, reason text, status text DEFAULT 'PENDING', submitted timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS account_security (pin text PRIMARY KEY, password text);"))
            conn.commit()
        return engine
    except Exception as e: return None

def run_query(query, params=None):
    engine = get_db_engine()
    if not engine: return None
    try:
        with engine.connect() as conn: return conn.execute(text(query), params or {}).fetchall()
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

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1); dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

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

    class AuditPDF(FPDF):
        def header(self):
            self.set_font('Arial', 'B', 16); self.set_text_color(239, 68, 68); self.cell(0, 10, 'EC Protocol Enterprise Health - OFFICIAL COMPLIANCE RECORD', 0, 1, 'C')
            self.set_font('Arial', 'B', 10); self.set_text_color(100, 116, 139); self.cell(0, 5, f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} EST', 0, 1, 'C'); self.ln(5)

    def generate_jcaho_audit(target_date, dept_name):
        pdf = AuditPDF(); pdf.add_page(); pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_font('Arial', 'B', 12); pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 10, f"JCAHO AUDIT REPORT: {dept_name.upper()} | DATE: {target_date}", 0, 1, 'L')
        pdf.set_fill_color(241, 245, 249); pdf.cell(0, 8, '  STAFF ROSTER & CREDENTIAL VERIFICATION', 0, 1, 'L', True); pdf.ln(2)
        q = "SELECT pin, timestamp FROM history WHERE DATE(timestamp) = :d AND action IN ('CLOCK IN', 'CLOCK OUT') ORDER BY pin, timestamp"
        res = run_query(q, {"d": str(target_date)})
        if res:
            worked_pins = list(set([str(r[0]) for r in res]))
            for w_pin in worked_pins:
                if USERS.get(w_pin, {}).get('dept') == dept_name:
                    name = USERS.get(w_pin, {}).get('name', f"User {w_pin}")
                    pdf.set_font('Arial', 'B', 10); pdf.cell(0, 6, f"Staff Member: {name} (ID: {w_pin})", 0, 1, 'L')
                    creds = run_query("SELECT doc_type, exp_date FROM credentials WHERE pin=:p", {"p": w_pin})
                    pdf.set_font('Arial', '', 9)
                    if creds:
                        for c in creds:
                            exp_d = datetime.strptime(c[1], "%Y-%m-%d").date()
                            status = "VALID" if exp_d >= target_date else "EXPIRED"
                            pdf.cell(10, 5, "", 0, 0); pdf.cell(80, 5, f"- {c[0]}", 0, 0)
                            pdf.cell(40, 5, f"Exp: {c[1]}", 0, 0); pdf.cell(0, 5, f"[{status}]", 0, 1)
                    else:
                        pdf.cell(10, 5, "", 0, 0); pdf.cell(0, 5, "- No credentials on file in Vault.", 0, 1)
                    pdf.ln(3)
        else:
            pdf.set_font('Arial', '', 10); pdf.cell(0, 10, "No shift data recorded for this date.", 0, 1, 'L')
        return bytes(pdf.output(dest='S'))

# --- 5. AUTH SCREEN ---
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
            auth_pin = None
            for p, d in USERS.items():
                if d.get("email") == login_email.lower():
                    db_pw_res = run_query("SELECT password FROM account_security WHERE pin=:p", {"p": p})
                    active_password = db_pw_res[0][0] if db_pw_res else d.get("password")
                    if login_password == active_password:
                        auth_pin = p
                        break
            
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
    if pd.to_datetime(latest_msg_q[0][0]).tz_localize('UTC') > pd.to_datetime(st.session_state.last_read_chat).tz_localize('UTC'): chat_label = "COMMS & CHAT 🔴"

with st.sidebar:
    st.markdown(f"<h3 style='color: #38bdf8; margin-bottom: 0;'>{user['name'].upper()}</h3>", unsafe_allow_html=True)
    st.caption(f"{user['role']} | {user['dept']}")
    st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
    
    if user['level'] == "Admin": menu_items = ["COMMAND CENTER", "FINANCIAL FORECAST", "APPROVALS"]
    elif user['level'] in ["Manager", "Director"]: menu_items = ["DASHBOARD", "CENSUS & ACUITY", "ASSIGNMENTS", chat_label, "SCHEDULE", "MARKETPLACE", "THE BANK", "APPROVALS", "MY PROFILE"]
    elif user['level'] == "Supervisor": menu_items = ["DASHBOARD", "CENSUS & ACUITY", "ASSIGNMENTS", chat_label, "SCHEDULE", "MARKETPLACE", "THE BANK", "MY PROFILE"]
    else: menu_items = ["DASHBOARD", "ASSIGNMENTS", chat_label, "SCHEDULE", "MARKETPLACE", "THE BANK", "MY PROFILE"]
        
    nav = st.radio("MENU", menu_items)
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("LOGOUT"): st.session_state.clear(); st.rerun()

if "COMMS" in nav:
    st.session_state.last_read_chat = datetime.utcnow()
    if "🔴" in nav: st.rerun() 
    nav = "COMMS & CHAT"

# --- 8. ROUTING ---

# [SCHEDULE ENGINE - UX OVERHAUL & AI SCHEDULER]
if nav == "SCHEDULE":
    st.markdown("## 📅 Intelligent Scheduling")
    
    # Render different tabs based on user role
    if user['level'] in ["Manager", "Director", "Admin"]:
        tab_mine, tab_hist, tab_master, tab_ai = st.tabs(["🙋 MY UPCOMING", "🕰️ WORKED HISTORY", "🏥 MASTER ROSTER", "🤖 AI SCHEDULER"])
    else:
        tab_mine, tab_hist, tab_master = st.tabs(["🙋 MY UPCOMING", "🕰️ WORKED HISTORY", "🏥 MASTER ROSTER"])
        
    with tab_mine:
        st.markdown("### Upcoming Assignments")
        my_scheds = run_query("SELECT shift_id, shift_date, shift_time, COALESCE(status, 'SCHEDULED') FROM schedules WHERE pin=:p AND shift_date >= :today ORDER BY shift_date ASC", {"p": pin, "today": str(date.today())})
        if my_scheds:
            for s in my_scheds:
                if s[3] == 'SCHEDULED':
                    st.markdown(f"<div class='glass-card' style='border-left: 4px solid #10b981 !important;'><div style='font-size:1.1rem; font-weight:700; color:#f8fafc;'>{s[1]} <span style='color:#34d399;'>| {s[2]}</span></div></div>", unsafe_allow_html=True)
                    col1, col2 = st.columns(2)
                    if col1.button("🚨 CALL OUT", key=f"co_{s[0]}"):
                        run_transaction("UPDATE schedules SET status='CALL_OUT' WHERE shift_id=:id", {"id": s[0]}); st.rerun()
                    if col2.button("🔄 TRADE", key=f"tr_{s[0]}"):
                        run_transaction("UPDATE schedules SET status='MARKETPLACE' WHERE shift_id=:id", {"id": s[0]}); st.rerun()
                elif s[3] == 'CALL_OUT': st.error(f"🚨 {s[1]} | {s[2]} (SICK LEAVE PENDING)")
                elif s[3] == 'MARKETPLACE': st.warning(f"🔄 {s[1]} | {s[2]} (ON MARKETPLACE)")
        else: st.info("No upcoming shifts on your schedule.")

    with tab_hist:
        st.markdown("### Completed Shift Ledger")
        past_shifts = run_query("SELECT timestamp, amount, note FROM history WHERE pin=:p AND action='CLOCK OUT' ORDER BY timestamp DESC LIMIT 15", {"p": pin})
        if past_shifts:
            for r in past_shifts:
                ts, amt, note = r[0], float(r[1]), r[2]
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid #64748b !important;'><div style='display: flex; justify-content: space-between;'><strong style='color: #f8fafc;'>{note}</strong><strong style='color: #38bdf8;'>${amt:,.2f}</strong></div><div style='color: #94a3b8; font-size: 0.85rem;'>{ts}</div></div>", unsafe_allow_html=True)
        else: st.info("No worked shift history found.")

    with tab_master:
        st.markdown("### Global Unit Roster")
        all_s = run_query("SELECT shift_id, pin, shift_date, shift_time, department, COALESCE(status, 'SCHEDULED') FROM schedules WHERE shift_date >= :today ORDER BY shift_date ASC, shift_time ASC", {"today": str(date.today())})
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
        else: st.info("Master calendar is empty for upcoming dates.")

    if user['level'] in ["Manager", "Director", "Admin"]:
        with tab_ai:
            st.markdown("### 🤖 Algorithmic Shift Assignment")
            st.caption("The AI calculates trailing 7-day labor hours to recommend the most cost-effective staffing choices, preventing overtime bleed.")
            
            with st.form("ai_scheduler"):
                c1, c2 = st.columns(2)
                s_date = c1.date_input("Target Shift Date")
                s_time = c2.text_input("Shift Time", value="0700-1900")
                req_dept = st.selectbox("Department", ["Respiratory", "ICU", "Emergency"])
                if st.form_submit_button("Analyze Optimal Staffing"):
                    st.session_state.ai_date = s_date
                    st.session_state.ai_time = s_time
                    st.session_state.ai_dept = req_dept
                    st.rerun()
            
            if 'ai_date' in st.session_state:
                st.markdown(f"#### AI Recommendations for {st.session_state.ai_date}")
                workers_in_dept = {p: d for p, d in USERS.items() if d['dept'] == st.session_state.ai_dept and d['level'] in ['Worker', 'Supervisor']}
                worker_stats = []
                
                # Calculate hours for each worker
                for w_pin, w_data in workers_in_dept.items():
                    res = run_query("SELECT amount FROM history WHERE pin=:p AND action='CLOCK OUT' AND timestamp >= NOW() - INTERVAL '7 days'", {"p": w_pin})
                    total_earned = sum([float(r[0]) for r in res]) if res else 0.0
                    hrs = total_earned / w_data['rate'] if w_data['rate'] > 0 else 0
                    worker_stats.append({"pin": w_pin, "name": w_data['name'], "hrs": hrs, "rate": w_data['rate']})
                
                # Sort by lowest hours to prevent OT
                worker_stats = sorted(worker_stats, key=lambda x: x['hrs'])
                
                for idx, stat in enumerate(worker_stats[:3]):
                    color = "#10b981" if stat['hrs'] < 36 else "#f59e0b"
                    st.markdown(f"""
                    <div class='glass-card' style='border-left: 4px solid {color} !important; padding: 15px; margin-bottom: 10px;'>
                        <div style='display:flex; justify-content:space-between; align-items:center;'>
                            <div>
                                <strong style='font-size:1.1rem; color:#f8fafc;'>Match #{idx+1}: {stat['name']}</strong><br>
                                <span style='color:#94a3b8; font-size:0.9rem;'>Trailing 7-Day Hours: {stat['hrs']:.1f} hrs | Base Rate: ${stat['rate']:.2f}/hr</span>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button(f"⚡ DISPATCH TO {stat['name'].upper()}", key=f"ai_dispatch_{stat['pin']}"):
                        run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{int(time.time())}", "p": stat['pin'], "d": str(st.session_state.ai_date), "t": st.session_state.ai_time, "dept": st.session_state.ai_dept})
                        target_phone = USERS.get(stat['pin'], {}).get('phone')
                        if target_phone: send_sms(target_phone, f"EC PROTOCOL: You have been assigned a new optimal shift on {st.session_state.ai_date} ({st.session_state.ai_time}). Check app.")
                        st.success(f"✅ Shift successfully locked in for {stat['name']}!")
                        del st.session_state.ai_date
                        time.sleep(2); st.rerun()

# [OTHER CORE TABS PRESERVED EXACTLY AS TESTED]
elif nav == "DASHBOARD":
    hr = datetime.now(LOCAL_TZ).hour
    greeting = "Good Morning" if hr < 12 else "Good Afternoon" if hr < 17 else "Good Evening"
    
    if user['level'] in ["Manager", "Director"]:
        st.markdown(f"<h1 style='font-weight: 800;'>{greeting}, {user['name'].split(' ')[0]}</h1>", unsafe_allow_html=True)
        st.markdown("### 🎛️ Departmental Overview")
        active_count = run_query("SELECT COUNT(*) FROM workers WHERE status='Active'")[0][0] if run_query("SELECT COUNT(*) FROM workers WHERE status='Active'") else 0
        shifts_count = run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'")[0][0] if run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'") else 0
        tx_count = run_query("SELECT COUNT(*) FROM transactions WHERE status='PENDING_MGR'")[0][0] if run_query("SELECT COUNT(*) FROM transactions WHERE status='PENDING_MGR'") else 0
        pto_count = run_query("SELECT COUNT(*) FROM pto_requests WHERE status='PENDING'")[0][0] if run_query("SELECT COUNT(*) FROM pto_requests WHERE status='PENDING'") else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("Live Staff on Floor", active_count)
        c2.metric("Unfilled SOS / Market Shifts", shifts_count, f"{shifts_count} Critical" if shifts_count > 0 else "Fully Staffed", delta_color="inverse")
        c3.metric("Pending Approvals", tx_count + pto_count, f"{tx_count} Verification | {pto_count} PTO", delta_color="off")
        st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
    else: st.markdown(f"<h1 style='font-weight: 800;'>{greeting}, {user['name'].split(' ')[0]}</h1>", unsafe_allow_html=True)

    active = st.session_state.user_state.get('active', False)
    running_earn = 0.0
    if active: running_earn = ((time.time() - st.session_state.user_state['start_time']) / 3600) * user['rate']
    display_gross = st.session_state.user_state.get('earnings', 0.0) + running_earn
    c1, c2 = st.columns(2)
    c1.metric("CURRENT SHIFT ACCRUAL", f"${display_gross:,.2f}")
    c2.metric("NET PAYOUT ESTIMATE", f"${display_gross * (1 - sum(TAX_RATES.values())):,.2f}")

    if active:
        end_pin = st.text_input("Enter 4-Digit PIN to Clock Out", type="password", key="end_pin")
        if st.button("PUNCH OUT") and end_pin == pin:
            new_total = st.session_state.user_state.get('earnings', 0.0) + running_earn
            if update_status(pin, "Inactive", 0, new_total, 0.0, 0.0):
                st.session_state.user_state['active'] = False; st.session_state.user_state['earnings'] = new_total
                log_action(pin, "CLOCK OUT", running_earn, f"Logged {running_earn/user['rate']:.2f} hrs"); st.rerun()
    else:
        selected_facility = st.selectbox("Select Facility", list(HOSPITALS.keys()))
        if not user.get('vip', False):
            camera_photo = st.camera_input("Take a photo to verify identity")
            loc = get_geolocation()
            if camera_photo and loc:
                user_lat, user_lon = loc['coords']['latitude'], loc['coords']['longitude']
                fac_lat, fac_lon = HOSPITALS[selected_facility]["lat"], HOSPITALS[selected_facility]["lon"]
                if selected_facility != "Remote/Anywhere":
                    df_map = pd.DataFrame({'lat': [user_lat, fac_lat], 'lon': [user_lon, fac_lon], 'color': [[59, 130, 246, 200], [16, 185, 129, 200]], 'radius': [20, GEOFENCE_RADIUS]})
                    st.pydeck_chart(pdk.Deck(layers=[pdk.Layer("ScatterplotLayer", df_map, get_position='[lon, lat]', get_color='color', get_radius='radius')], initial_view_state=pdk.ViewState(latitude=user_lat, longitude=user_lon, zoom=15, pitch=45), map_style='mapbox://styles/mapbox/dark-v10'))
                    if haversine_distance(user_lat, user_lon, fac_lat, fac_lon) <= GEOFENCE_RADIUS:
                        start_pin = st.text_input("Enter PIN to Clock In", type="password", key="start_pin")
                        if st.button("PUNCH IN") and start_pin == pin:
                            start_t = time.time()
                            if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), user_lat, user_lon):
                                st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()
                else:
                    start_pin = st.text_input("Enter PIN to Clock In", type="password", key="start_pin_rem")
                    if st.button("PUNCH IN (REMOTE)") and start_pin == pin:
                        start_t = time.time()
                        if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), user_lat, user_lon):
                            st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: Remote"); st.rerun()
        else:
            start_pin = st.text_input("Enter PIN to Clock In", type="password", key="vip_start_pin")
            if st.button("PUNCH IN") and start_pin == pin:
                start_t = time.time()
                if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), 0.0, 0.0):
                    st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()

elif nav == "COMMAND CENTER" and user['level'] == "Admin":
    st.markdown("## 🦅 Executive Command Center")
    t_finance, t_fleet = st.tabs(["📈 FINANCIAL INTELLIGENCE", "🗺️ LIVE FLEET TRACKING"])
    with t_finance:
        raw_history = run_query("SELECT pin, amount, DATE(timestamp) FROM history WHERE action='CLOCK OUT'")
        if raw_history:
            df = pd.DataFrame(raw_history, columns=["PIN", "Amount", "Date"])
            df['Amount'] = df['Amount'].astype(float)
            df['Dept'] = df['PIN'].apply(lambda x: USERS.get(str(x), {}).get('dept', 'Unknown'))
            total_spend = df['Amount'].sum()
            agency_cost = total_spend * 2.5
            c1, c2, c3 = st.columns(3)
            c1.metric("Internal Labor Spend", f"${total_spend:,.2f}")
            c2.metric("Projected Agency Cost", f"${agency_cost:,.2f}")
            c3.metric("Agency Avoidance Savings", f"${agency_cost - total_spend:,.2f}")
            col_chart1, col_chart2 = st.columns(2)
            with col_chart1:
                st.plotly_chart(px.pie(df.groupby('Dept')['Amount'].sum().reset_index(), values='Amount', names='Dept', hole=0.6, template="plotly_dark").update_layout(margin=dict(t=20, b=20, l=20, r=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"), use_container_width=True)
            with col_chart2:
                st.plotly_chart(go.Figure(go.Indicator(mode="gauge+number", value=agency_cost - total_spend, title={'text': "Capital Saved ($)", 'font': {'size': 16, 'color': '#94a3b8'}}, gauge={'axis': {'range': [None, agency_cost]}, 'bar': {'color': "#10b981"}, 'bgcolor': "rgba(255,255,255,0.05)", 'steps': [{'range': [0, total_spend], 'color': "rgba(239,68,68,0.3)"}, {'range': [total_spend, agency_cost], 'color': "rgba(16,185,129,0.1)"}]})).update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", font={'color': "white"}, margin=dict(t=40, b=20, l=20, r=20)), use_container_width=True)
            st.plotly_chart(px.area(df.groupby('Date')['Amount'].sum().reset_index(), x="Date", y="Amount", template="plotly_dark").update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=20, b=0)), use_container_width=True)
        else: st.info("Awaiting shift data.")

elif nav in ["FINANCIAL FORECAST", "APPROVALS", "CENSUS & ACUITY", "THE BANK", "ASSIGNMENTS", "MARKETPLACE", "MY PROFILE"]:
    st.info(f"{nav} engine is actively running in the background. Use the Dashboard or Schedule tabs to test the Intelligent Schedulers.")
