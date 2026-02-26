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

# --- EXTERNAL LIBRARIES ---
try:
    from fpdf import FPDF
    PDF_ACTIVE = True
except ImportError:
    PDF_ACTIVE = False

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

# --- 1. CONFIGURATION & STABLE CSS OVERHAUL ---
st.set_page_config(page_title="EC Protocol Enterprise", page_icon="⚡", layout="wide", initial_sidebar_state="collapsed")

html_style = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800;900&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
    
    /* COMPLETELY DISABLE AND HIDE THE SIDEBAR AND TOGGLE BUTTON */
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    #MainMenu {visibility: hidden;} 
    footer {visibility: hidden;} 
    [data-testid="stToolbar"] {visibility: hidden !important;} 
    header {background: transparent !important;}
    
    .stApp { background-color: #0b1120; background-image: radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.1) 0px, transparent 50%), radial-gradient(at 100% 0%, rgba(16, 185, 129, 0.05) 0px, transparent 50%); background-attachment: fixed; color: #f8fafc; }
    .block-container { padding-top: 1rem !important; padding-bottom: 2rem !important; max-width: 96% !important; }
    
    /* Floating Custom Header */
    .custom-header-pill { background: rgba(11, 17, 32, 0.85); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); padding: 15px 25px; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 30px rgba(0,0,0,0.3); }
    
    /* Glass Cards & Metrics */
    div[data-testid="metric-container"], .glass-card { background: rgba(30, 41, 59, 0.6) !important; backdrop-filter: blur(12px) !important; border: 1px solid rgba(255, 255, 255, 0.05) !important; border-radius: 16px; padding: 20px; margin-bottom: 15px; box-shadow: 0 4px 20px 0 rgba(0, 0, 0, 0.3); }
    div[data-testid="metric-container"] label { color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #f8fafc; font-size: 2rem; font-weight: 800; }
    
    /* Buttons */
    .stButton>button { width: 100%; height: 55px; border-radius: 12px; font-weight: 700; font-size: 1rem; border: none; transition: all 0.2s ease; box-shadow: 0 4px 15px rgba(0,0,0,0.2); letter-spacing: 0.5px; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.3); }
    
    /* Horizontal Radio Tabs Styling to look like an app menu */
    div[role="radiogroup"] { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; }
    
    /* Bounty Cards */
    .bounty-card { background: linear-gradient(145deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.95) 100%); border: 1px solid rgba(245, 158, 11, 0.3); border-left: 5px solid #f59e0b; border-radius: 16px; padding: 25px; margin-bottom: 20px; position: relative; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.4); transition: transform 0.2s ease; }
    .bounty-card:hover { transform: translateY(-3px); border: 1px solid rgba(245, 158, 11, 0.6); }
    .bounty-card::before { content: '⚡ SURGE ACTIVE'; position: absolute; top: 18px; right: -35px; background: #f59e0b; color: #000; font-size: 0.7rem; font-weight: 900; padding: 6px 40px; transform: rotate(45deg); letter-spacing: 1px; }
    .bounty-amount { font-size: 2.8rem; font-weight: 900; color: #10b981; margin: 10px 0; text-shadow: 0 0 25px rgba(16, 185, 129, 0.2); letter-spacing: -1px; }
    
    /* Empty States & FinTech */
    .empty-state { text-align: center; padding: 40px 20px; background: rgba(30, 41, 59, 0.3); border: 2px dashed rgba(255,255,255,0.1); border-radius: 16px; margin-top: 20px; margin-bottom: 20px; }
    .plaid-box { background: #111; border: 1px solid #333; border-radius: 12px; padding: 20px; text-align: center; }
    .stripe-box { background: linear-gradient(135deg, #635bff 0%, #423ed8 100%); border-radius: 12px; padding: 25px; color: white; margin-bottom: 20px; box-shadow: 0 10px 25px rgba(99, 91, 255, 0.4); }
    
    /* Schedule Rows */
    .sched-date-header { background: rgba(16, 185, 129, 0.1); padding: 10px 15px; border-radius: 8px; margin-top: 25px; margin-bottom: 15px; font-weight: 800; font-size: 1rem; border-left: 4px solid #10b981; color: #34d399; text-transform: uppercase; }
    .sched-row { display: flex; justify-content: space-between; align-items: center; padding: 15px; margin-bottom: 8px; background: rgba(30, 41, 59, 0.5); border-radius: 8px; border-left: 3px solid rgba(255,255,255,0.1); }
    .sched-time { color: #34d399; font-weight: 800; min-width: 100px; font-size: 1rem; }

    @media (max-width: 768px) {
        .sched-row { flex-direction: column; align-items: flex-start; }
        .sched-time { margin-bottom: 5px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 5px; width: 100%; }
        div[data-testid="stMetricValue"] { font-size: 1.5rem !important; }
        .bounty-amount { font-size: 2.2rem; }
    }
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
            conn.execute(text("CREATE TABLE IF NOT EXISTS hr_onboarding (pin text PRIMARY KEY, w4_filing_status text, w4_allowances int, dd_bank text, dd_acct_last4 text, signed_date timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS pto_requests (req_id text PRIMARY KEY, pin text, start_date text, end_date text, reason text, status text DEFAULT 'PENDING', submitted timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS account_security (pin text PRIMARY KEY, password text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS credentials (doc_id text PRIMARY KEY, pin text, doc_type text, doc_number text, exp_date text, status text);"))
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
    res = run_query("SELECT amount FROM history WHERE pin=:p AND action='CLOCK OUT' AND EXTRACT(YEAR FROM timestamp) = :y", {"p": pin, "y": datetime.now().year})
    return sum([float(r[0]) for r in res if r[0]]) if res else 0.0

def get_period_gross(pin, start_date, end_date):
    res = run_query("SELECT amount FROM history WHERE pin=:p AND action='CLOCK OUT' AND timestamp >= :s AND timestamp <= :e", {"p": pin, "s": start_date, "e": datetime.combine(end_date, datetime.max.time())})
    return sum([float(r[0]) for r in res if r[0]]) if res else 0.0

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1); dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- 4. PDF ENGINES ---
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

# --- 5. SECURE AUTH SCREEN ---
if 'user_state' not in st.session_state: st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0}

if 'logged_in_user' not in st.session_state:
    st.markdown("<br><br><br><br><h1 style='text-align: center; color: #f8fafc; letter-spacing: 4px; font-weight: 900; font-size: 3rem;'>EC PROTOCOL</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #10b981; letter-spacing: 3px; font-weight:600;'>ENTERPRISE HEALTHCARE LOGISTICS</p><br>", unsafe_allow_html=True)
    with st.container():
        st.markdown("<div class='glass-card' style='max-width: 500px; margin: 0 auto;'>", unsafe_allow_html=True)
        login_email = st.text_input("ENTERPRISE EMAIL", placeholder="name@hospital.com")
        login_password = st.text_input("SECURE PASSWORD", type="password", placeholder="••••••••")
        st.markdown("<br>", unsafe_allow_html=True)
        
        if st.button("AUTHENTICATE CONNECTION"):
            auth_pin = None
            for p, d in USERS.items():
                if d.get("email") == login_email.lower():
                    db_pw_res = run_query("SELECT password FROM account_security WHERE pin=:p", {"p": p})
                    active_password = db_pw_res[0][0] if db_pw_res else d.get("password")
                    if login_password == active_password:
                        auth_pin = p; break
            
            if auth_pin:
                st.session_state.logged_in_user = USERS[auth_pin]
                st.session_state.pin = auth_pin
                force_cloud_sync(auth_pin)
                st.rerun()
            else: st.error("❌ INVALID CREDENTIALS OR NETWORK ERROR")
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

user = st.session_state.logged_in_user
pin = st.session_state.pin

# --- 6. TOP NAVIGATION AND HEADER (NO SIDEBAR) ---
c1, c2 = st.columns([8, 2])
with c1:
    st.markdown(f"""
    <div class='custom-header-pill'>
        <div style='font-weight:900; font-size:1.4rem; letter-spacing:2px; color:#f8fafc; display:flex; align-items:center;'>
            <span style='color:#10b981; font-size:1.8rem; margin-right:8px;'>⚡</span> EC PROTOCOL
        </div>
        <div style='text-align:right;'>
            <div style='font-size:0.95rem; font-weight:800; color:#f8fafc;'>{user['name']}</div>
            <div style='font-size:0.75rem; color:#38bdf8; text-transform:uppercase; letter-spacing:1px;'>{user['role']} | {user['dept']}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
with c2:
    st.markdown("<br>", unsafe_allow_html=True) # spacing alignment
    if st.button("🚪 LOGOUT"):
        st.session_state.clear()
        st.rerun()

# Define tabs based on user level
if user['level'] == "Admin": menu_items = ["COMMAND CENTER", "FINANCIAL FORECAST", "APPROVALS"]
elif user['level'] in ["Manager", "Director"]: menu_items = ["DASHBOARD", "CENSUS & ACUITY", "MARKETPLACE", "SCHEDULE", "THE BANK", "APPROVALS", "MY PROFILE"]
else: menu_items = ["DASHBOARD", "MARKETPLACE", "SCHEDULE", "THE BANK", "MY PROFILE"]

st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)
nav = st.radio("NAVIGATION", menu_items, horizontal=True, label_visibility="collapsed")
st.markdown("<hr style='border-color: rgba(255,255,255,0.05); margin-top: 5px; margin-bottom: 20px;'>", unsafe_allow_html=True)

# --- 8. MASTER ROUTING ---

if nav == "DASHBOARD":
    st.markdown(f"<h2 style='font-weight: 800;'>Status Terminal</h2>", unsafe_allow_html=True)
    if st.button("🔄 Refresh Dashboard"): st.rerun()
    
    if user['level'] in ["Manager", "Director"]:
        active_count = run_query("SELECT COUNT(*) FROM workers WHERE status='Active'")[0][0] if run_query("SELECT COUNT(*) FROM workers WHERE status='Active'") else 0
        shifts_count = run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'")[0][0] if run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'") else 0
        tx_count = run_query("SELECT COUNT(*) FROM transactions WHERE status='PENDING_MGR'")[0][0] if run_query("SELECT COUNT(*) FROM transactions WHERE status='PENDING_MGR'") else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("Live Staff", active_count)
        c2.metric("Market Bounties", shifts_count, f"{shifts_count} Critical" if shifts_count > 0 else "Fully Staffed", delta_color="inverse")
        c3.metric("Approvals", tx_count)
        st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)

    active = st.session_state.user_state.get('active', False)
    running_earn = 0.0
    if active: running_earn = ((time.time() - st.session_state.user_state['start_time']) / 3600) * user['rate']
    display_gross = st.session_state.user_state.get('earnings', 0.0) + running_earn
    c1, c2 = st.columns(2)
    c1.metric("SHIFT ACCRUAL", f"${display_gross:,.2f}")
    c2.metric("NET ESTIMATE", f"${display_gross * (1 - sum(TAX_RATES.values())):,.2f}")
    st.markdown("<br>", unsafe_allow_html=True)

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
            st.info("Identity verification required to initiate shift.")
            camera_photo = st.camera_input("Take a photo to verify identity")
            loc = get_geolocation()
            if camera_photo and loc:
                user_lat, user_lon = loc['coords']['latitude'], loc['coords']['longitude']
                fac_lat, fac_lon = HOSPITALS[selected_facility]["lat"], HOSPITALS[selected_facility]["lon"]
                
                if selected_facility != "Remote/Anywhere":
                    df_map = pd.DataFrame({'lat': [user_lat, fac_lat], 'lon': [user_lon, fac_lon], 'color': [[59, 130, 246, 200], [16, 185, 129, 200]], 'radius': [20, GEOFENCE_RADIUS]})
                    st.pydeck_chart(pdk.Deck(layers=[pdk.Layer("ScatterplotLayer", df_map, get_position='[lon, lat]', get_color='color', get_radius='radius')], initial_view_state=pdk.ViewState(latitude=user_lat, longitude=user_lon, zoom=15, pitch=45), map_style='mapbox://styles/mapbox/dark-v10'))
                    
                    if haversine_distance(user_lat, user_lon, fac_lat, fac_lon) <= GEOFENCE_RADIUS:
                        st.success(f"✅ Geofence Confirmed.")
                        start_pin = st.text_input("Enter PIN to Clock In", type="password", key="start_pin")
                        if st.button("PUNCH IN") and start_pin == pin:
                            start_t = time.time()
                            if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), user_lat, user_lon):
                                st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()
                    else: st.error("❌ Geofence Failed. You are too far from the facility.")
                else:
                    st.success("✅ Remote Check-in Authorized.")
                    start_pin = st.text_input("Enter PIN to Clock In", type="password", key="start_pin_rem")
                    if st.button("PUNCH IN (REMOTE)") and start_pin == pin:
                        start_t = time.time()
                        if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), user_lat, user_lon):
                            st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: Remote"); st.rerun()
        else:
            st.caption("✨ VIP Security Override Active")
            start_pin = st.text_input("Enter PIN to Clock In", type="password", key="vip_start_pin")
            if st.button("PUNCH IN") and start_pin == pin:
                start_t = time.time()
                if update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), 0.0, 0.0):
                    st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()

elif nav == "COMMAND CENTER" and user['level'] == "Admin":
    if st.button("🔄 Refresh Data Link"): st.rerun()
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
            agency_avoidance = agency_cost - total_spend
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Internal Labor Spend", f"${total_spend:,.2f}")
            c2.metric("Projected Agency Cost", f"${agency_cost:,.2f}")
            c3.metric("Agency Avoidance Savings", f"${agency_avoidance:,.2f}")
            
            col_chart1, col_chart2 = st.columns(2)
            with col_chart1:
                st.plotly_chart(px.pie(df.groupby('Dept')['Amount'].sum().reset_index(), values='Amount', names='Dept', hole=0.6, template="plotly_dark").update_layout(margin=dict(t=20, b=20, l=20, r=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"), use_container_width=True)
            with col_chart2:
                st.plotly_chart(go.Figure(go.Indicator(mode="gauge+number", value=agency_avoidance, title={'text': "Capital Saved ($)", 'font': {'size': 16, 'color': '#94a3b8'}}, gauge={'axis': {'range': [None, agency_cost]}, 'bar': {'color': "#10b981"}, 'bgcolor': "rgba(255,255,255,0.05)", 'steps': [{'range': [0, total_spend], 'color': "rgba(239,68,68,0.3)"}, {'range': [total_spend, agency_cost], 'color': "rgba(16,185,129,0.1)"}]})).update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", font={'color': "white"}, margin=dict(t=40, b=20, l=20, r=20)), use_container_width=True)
            
            st.plotly_chart(px.area(df.groupby('Date')['Amount'].sum().reset_index(), x="Date", y="Amount", template="plotly_dark").update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=20, b=0)), use_container_width=True)
            st.download_button(label="📥 Export Raw Ledger (CSV)", data=df.to_csv(index=False).encode('utf-8'), file_name='ec_ledger.csv', mime='text/csv')
        else: st.info("Awaiting shift completion data to render financial models.")
    with t_fleet:
        active_workers = run_query("SELECT pin, start_time, earnings, lat, lon FROM workers WHERE status='Active'")
        if active_workers:
            map_data = []
            for w in active_workers:
                w_pin, w_start, w_lat, w_lon = str(w[0]), float(w[1]), w[3], w[4]
                w_name = USERS.get(w_pin, {}).get("name", "Unknown")
                hrs = (time.time() - w_start) / 3600
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid #10b981 !important;'><h4 style='margin:0;'>{w_name}</h4><span style='color:#10b981; font-weight:bold;'>🟢 ON CLOCK ({hrs:.2f} hrs)</span></div>", unsafe_allow_html=True)
                if w_lat and w_lon: map_data.append({"name": w_name, "lat": float(w_lat), "lon": float(w_lon)})
            if map_data:
                df_fleet = pd.DataFrame(map_data)
                st.pydeck_chart(pdk.Deck(layers=[pdk.Layer("ScatterplotLayer", df_fleet, get_position='[lon, lat]', get_color='[16, 185, 129, 200]', get_radius=100)], initial_view_state=pdk.ViewState(latitude=df_fleet['lat'].mean(), longitude=df_fleet['lon'].mean(), zoom=11, pitch=45), map_style='mapbox://styles/mapbox/dark-v10'))
        else: st.info("No active operators in the field.")

elif nav == "FINANCIAL FORECAST" and user['level'] == "Admin":
    st.markdown("## 📊 Predictive Payroll Outflow")
    if st.button("🔄 Refresh Forecast"): st.rerun()
    
    scheds = run_query("SELECT pin FROM schedules WHERE status='SCHEDULED'")
    base_outflow = sum((USERS.get(str(s[0]), {}).get('rate', 0.0) * 12) for s in scheds) if scheds else 0.0
    open_markets = run_query("SELECT rate FROM marketplace WHERE status='OPEN'")
    critical_outflow = sum((float(m[0]) * 12) for m in open_markets) if open_markets else 0.0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Scheduled Baseline", f"${base_outflow:,.2f}")
    c2.metric("Critical SOS Liability", f"${critical_outflow:,.2f}", delta_color="inverse")
    c3.metric("Total Forecasted Outflow", f"${base_outflow + critical_outflow:,.2f}")
    st.markdown("<br><hr style='border-color: rgba(255,255,255,0.1);'><br>", unsafe_allow_html=True)
    full_scheds = run_query("SELECT shift_id, pin, shift_date, shift_time, department FROM schedules WHERE status='SCHEDULED' ORDER BY shift_date ASC")
    if full_scheds:
        for s in full_scheds:
            st.markdown(f"<div class='sched-row'><div class='sched-time'>{s[2]}</div><div style='flex-grow: 1; padding-left: 15px;'><span class='sched-name'>{USERS.get(str(s[1]), {}).get('name', f'User {s[1]}')}</span> | {s[4]}</div></div>", unsafe_allow_html=True)
    else: st.info("No baseline shifts scheduled.")

elif nav == "CENSUS & ACUITY":
    st.markdown(f"## 📊 {user['dept']} Census & Staffing")
    if st.button("🔄 Refresh Census Board"): st.rerun()
    
    c_data = run_query("SELECT total_pts, high_acuity, last_updated FROM unit_census WHERE dept=:d", {"d": user['dept']})
    curr_pts, curr_high = (c_data[0][0], c_data[0][1]) if c_data else (0, 0)

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
                    run_transaction("INSERT INTO unit_census (dept, total_pts, high_acuity) VALUES (:d, :t, :h) ON CONFLICT (dept) DO UPDATE SET total_pts=:t, high_acuity=:h, last_updated=NOW()", {"d": user['dept'], "t": new_t, "h": new_h})
                    st.success("Census Updated!"); time.sleep(1); st.rerun()

    with st.expander("🛡️ JCAHO / DPH COMPLIANCE EXPORT", expanded=False):
        with st.form("jcaho_audit_form"):
            audit_date = st.date_input("Select Audit Date", value=date.today())
            if st.form_submit_button("Generate Audit Record") and PDF_ACTIVE:
                st.session_state.audit_pdf = generate_jcaho_audit(audit_date, user['dept'])
                st.session_state.audit_filename = f"JCAHO_Audit_{user['dept']}_{audit_date}.pdf"
                st.success("✅ Secure Audit Record Generated!")
        if 'audit_pdf' in st.session_state: st.download_button("📄 Download Official Audit PDF", data=st.session_state.audit_pdf, file_name=st.session_state.audit_filename, mime="application/pdf")

elif nav == "APPROVALS":
    st.markdown("## 📥 Approval Gateway")
    if st.button("🔄 Refresh Queue"): st.rerun()
    
    if user['level'] == "Admin":
        st.markdown("### Stage 2: Treasury Release (CFO Verification)")
        pending_cfo = run_query("SELECT tx_id, pin, amount, timestamp FROM transactions WHERE status='PENDING_CFO' ORDER BY timestamp ASC")
        if pending_cfo:
            for tx in pending_cfo:
                t_id, w_name, t_amt = tx[0], USERS.get(str(tx[1]), {}).get("name", "Unknown"), float(tx[2])
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid #3b82f6 !important;'><h4>{w_name} | ${t_amt:,.2f}</h4></div>", unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                if c1.button("💸 RELEASE FUNDS", key=f"cfo_{t_id}"): 
                    run_transaction("UPDATE transactions SET status='APPROVED' WHERE tx_id=:id", {"id": t_id})
                    target_phone = USERS.get(str(tx[1]), {}).get('phone')
                    if target_phone: send_sms(target_phone, f"EC PROTOCOL: Your payout of ${t_amt:,.2f} has been fully authorized and released.")
                    st.rerun()
                if c2.button("❌ RETURN TO MGR", key=f"den_{t_id}"): run_transaction("UPDATE transactions SET status='PENDING_MGR' WHERE tx_id=:id", {"id": t_id}); st.rerun()
        else: st.info("No funds pending CFO authorization.")
    else:
        tab_fin, tab_pto = st.tabs(["🕒 VERIFY HOURS", "🏝️ PTO REQUESTS"])
        with tab_fin:
            st.markdown("### Stage 1: Clinical Verification (Batch)")
            pending_mgr = run_query("SELECT tx_id, pin, amount, timestamp FROM transactions WHERE status='PENDING_MGR' ORDER BY timestamp ASC")
            if pending_mgr:
                with st.form("batch_verify_form"):
                    selections = {tx[0]: st.checkbox(f"**{USERS.get(str(tx[1]), {}).get('name')}** — ${float(tx[2]):,.2f}") for tx in pending_mgr}
                    if st.form_submit_button("☑️ BATCH VERIFY SELECTED"):
                        for t_id, is_selected in selections.items():
                            if is_selected: run_transaction("UPDATE transactions SET status='PENDING_CFO' WHERE tx_id=:id", {"id": t_id})
                        st.success("✅ Pushed to CFO Treasury."); time.sleep(1.5); st.rerun()
            else: st.info("No shift hours pending verification.")
        with tab_pto:
            pending_pto = run_query("SELECT req_id, pin, start_date, end_date FROM pto_requests WHERE status='PENDING'")
            if pending_pto:
                for p in pending_pto:
                    if st.button(f"APPROVE PTO: {USERS.get(str(p[1]), {}).get('name')} ({p[2]} to {p[3]})", key=p[0]): run_transaction("UPDATE pto_requests SET status='APPROVED' WHERE req_id=:id", {"id": p[0]}); st.rerun()
            else: st.info("No pending PTO requests.")

elif nav == "MARKETPLACE":
    st.markdown("<h2 style='font-weight:900; margin-bottom:5px;'>⚡ INTERNAL SHIFT MARKETPLACE</h2>", unsafe_allow_html=True)
    if st.button("🔄 Refresh Market"): st.rerun()
    
    st.caption("Active surge bounties. Claim critical shifts instantly. Rates reflect 1.5x incentive multipliers.")
    st.markdown("<br>", unsafe_allow_html=True)
    
    open_shifts = run_query("SELECT shift_id, role, date, start_time, rate FROM marketplace WHERE status='OPEN' ORDER BY date ASC")
    if open_shifts:
        for shift in open_shifts:
            s_id, s_role, s_date, s_time, s_rate = shift[0], shift[1], shift[2], shift[3], float(shift[4])
            est_payout = s_rate * 12
            
            st.markdown(f"""
            <div class='bounty-card'>
                <div style='display:flex; justify-content:space-between; align-items:flex-start;'>
                    <div>
                        <div style='color:#94a3b8; font-weight:800; text-transform:uppercase; letter-spacing:1px; font-size:0.9rem;'>{s_date} <span style='color:#38bdf8;'>| {s_time}</span></div>
                        <div style='font-size:1.4rem; font-weight:800; color:#f8fafc; margin-top:5px;'>{s_role}</div>
                        <div class='bounty-amount'>${est_payout:,.2f}</div>
                        <div style='color:#94a3b8; font-size:0.9rem;'>Calculated Base: ${s_rate:,.2f}/hr (12hr shift)</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button(f"⚡ CLAIM THIS SHIFT (${est_payout:,.0f})", key=f"claim_{s_id}"):
                run_transaction("UPDATE marketplace SET status='CLAIMED', claimed_by=:p WHERE shift_id=:id", {"p": pin, "id": s_id})
                run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{s_id}", "p": pin, "d": s_date, "t": s_time, "dept": user['dept']})
                log_action(pin, "CLAIMED SHIFT", est_payout, f"Claimed bounty shift for {s_date}")
                st.success("✅ Shift Successfully Claimed! It has been locked to your upcoming schedule."); time.sleep(2); st.rerun()
    else:
        st.markdown("<div class='empty-state'><div style='font-size:3rem; margin-bottom:10px;'>🛡️</div><h3 style='color:#f8fafc; margin-bottom:10px;'>No Surge Bounties Active</h3><p style='color:#94a3b8;'>The unit is currently fully staffed. Check back later or turn on SMS push notifications.</p></div>", unsafe_allow_html=True)

elif nav == "SCHEDULE":
    st.markdown("## 📅 Intelligent Scheduling")
    if st.button("🔄 Refresh Schedule"): st.rerun()
    
    if user['level'] in ["Manager", "Director", "Admin"]: tab_mine, tab_hist, tab_master, tab_ai = st.tabs(["🙋 MY UPCOMING", "🕰️ WORKED HISTORY", "🏥 MASTER ROSTER", "🤖 AI SCHEDULER"])
    else: tab_mine, tab_hist, tab_master = st.tabs(["🙋 MY UPCOMING", "🕰️ WORKED HISTORY", "🏥 MASTER ROSTER"])
        
    with tab_mine:
        my_scheds = run_query("SELECT shift_id, shift_date, shift_time, COALESCE(status, 'SCHEDULED') FROM schedules WHERE pin=:p AND shift_date >= :today ORDER BY shift_date ASC", {"p": pin, "today": str(date.today())})
        if my_scheds:
            for s in my_scheds:
                if s[3] == 'SCHEDULED':
                    st.markdown(f"<div class='glass-card' style='border-left: 4px solid #10b981 !important;'><div style='font-size:1.1rem; font-weight:700; color:#f8fafc;'>{s[1]} <span style='color:#34d399;'>| {s[2]}</span></div></div>", unsafe_allow_html=True)
                    col1, col2 = st.columns(2)
                    if col1.button("🚨 CALL OUT", key=f"co_{s[0]}"): run_transaction("UPDATE schedules SET status='CALL_OUT' WHERE shift_id=:id", {"id": s[0]}); st.rerun()
                    if col2.button("🔄 TRADE", key=f"tr_{s[0]}"): run_transaction("UPDATE schedules SET status='MARKETPLACE' WHERE shift_id=:id", {"id": s[0]}); st.rerun()
                elif s[3] == 'CALL_OUT': st.error(f"🚨 {s[1]} | {s[2]} (SICK LEAVE PENDING)")
                elif s[3] == 'MARKETPLACE': st.warning(f"🔄 {s[1]} | {s[2]} (ON MARKETPLACE)")
        else:
            open_count = run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'")[0][0] if run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'") else 0
            if open_count > 0:
                st.markdown(f"<div class='empty-state' style='border-color: rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.05);'><h3 style='color:#f8fafc; margin-bottom:10px;'>Your upcoming schedule is clear.</h3><p style='color:#94a3b8; margin-bottom:10px; font-size:1.1rem;'>There are currently <strong style='color:#f59e0b; font-size:1.3rem;'>{open_count} critical surge shifts</strong> available.</p><p style='color:#10b981; font-weight:800;'>Navigate to the MARKETPLACE to claim 1.5x Pay.</p></div>", unsafe_allow_html=True)
            else: st.markdown("<div class='empty-state'><h3 style='color:#f8fafc;'>Your schedule is clear.</h3><p style='color:#94a3b8;'>Take some time to rest.</p></div>", unsafe_allow_html=True)

    with tab_hist:
        past_shifts = run_query("SELECT timestamp, amount, note FROM history WHERE pin=:p AND action='CLOCK OUT' ORDER BY timestamp DESC LIMIT 15", {"p": pin})
        if past_shifts:
            for r in past_shifts:
                ts, amt, note = r[0], float(r[1]), r[2]
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid #64748b !important;'><div style='display: flex; justify-content: space-between;'><strong style='color: #f8fafc;'>{note}</strong><strong style='color: #38bdf8;'>${amt:,.2f}</strong></div><div style='color: #94a3b8; font-size: 0.85rem;'>{ts}</div></div>", unsafe_allow_html=True)
        else: st.info("No worked shift history found.")

    with tab_master:
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
            with st.form("ai_scheduler"):
                c1, c2 = st.columns(2)
                s_date = c1.date_input("Target Shift Date")
                s_time = c2.text_input("Shift Time", value="0700-1900")
                req_dept = st.selectbox("Department", ["Respiratory", "ICU", "Emergency"])
                if st.form_submit_button("Analyze Optimal Staffing"):
                    st.session_state.ai_date = s_date; st.session_state.ai_time = s_time; st.session_state.ai_dept = req_dept; st.rerun()
            
            if 'ai_date' in st.session_state:
                st.markdown(f"#### AI Recommendations for {st.session_state.ai_date}")
                workers_in_dept = {p: d for p, d in USERS.items() if d['dept'] == st.session_state.ai_dept and d['level'] in ['Worker', 'Supervisor']}
                worker_stats = []
                for w_pin, w_data in workers_in_dept.items():
                    res = run_query("SELECT amount FROM history WHERE pin=:p AND action='CLOCK OUT' AND timestamp >= NOW() - INTERVAL '7 days'", {"p": w_pin})
                    total_earned = sum([float(r[0]) for r in res]) if res else 0.0
                    hrs = total_earned / w_data['rate'] if w_data['rate'] > 0 else 0
                    worker_stats.append({"pin": w_pin, "name": w_data['name'], "hrs": hrs, "rate": w_data['rate']})
                worker_stats = sorted(worker_stats, key=lambda x: x['hrs'])
                for idx, stat in enumerate(worker_stats[:3]):
                    color = "#10b981" if stat['hrs'] < 36 else "#f59e0b"
                    st.markdown(f"<div class='glass-card' style='border-left: 4px solid {color} !important; padding: 15px; margin-bottom: 10px;'><div style='display:flex; justify-content:space-between; align-items:center;'><div><strong style='font-size:1.1rem; color:#f8fafc;'>Match #{idx+1}: {stat['name']}</strong><br><span style='color:#94a3b8; font-size:0.9rem;'>Trailing 7-Day Hours: {stat['hrs']:.1f} hrs | Base Rate: ${stat['rate']:.2f}/hr</span></div></div></div>", unsafe_allow_html=True)
                    if st.button(f"⚡ DISPATCH TO {stat['name'].upper()}", key=f"ai_dispatch_{stat['pin']}"):
                        run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{int(time.time())}", "p": stat['pin'], "d": str(st.session_state.ai_date), "t": st.session_state.ai_time, "dept": st.session_state.ai_dept})
                        target_phone = USERS.get(stat['pin'], {}).get('phone')
                        if target_phone: send_sms(target_phone, f"EC PROTOCOL: You have been assigned a new optimal shift on {st.session_state.ai_date} ({st.session_state.ai_time}). Check app.")
                        st.success(f"✅ Shift successfully locked in for {stat['name']}!"); del st.session_state.ai_date; time.sleep(2); st.rerun()

elif nav == "THE BANK":
    st.markdown("## 🏦 The Bank")
    if st.button("🔄 Refresh Bank Ledger"): st.rerun()
    
    bank_info = run_query("SELECT dd_bank, dd_acct_last4 FROM hr_onboarding WHERE pin=:p", {"p": pin})
    has_bank = bank_info and bank_info[0][0] and bank_info[0][1]
    
    banked_gross = st.session_state.user_state.get('earnings', 0.0)
    banked_net = banked_gross * (1 - sum(TAX_RATES.values()))
    
    if has_bank:
        b_name, b_last4 = bank_info[0][0], bank_info[0][1]
        st.markdown(f"""
        <div class='stripe-box'>
            <div style='display:flex; justify-content:space-between; align-items:center;'>
                <span style='font-size:0.9rem; font-weight:600; text-transform:uppercase; letter-spacing:1px; opacity:0.8;'>Available Balance</span>
                <span style='font-size:0.8rem; background:rgba(255,255,255,0.2); padding:4px 8px; border-radius:4px;'>EC Protocol Payroll</span>
            </div>
            <h1 style='font-size:3.5rem; margin:10px 0 5px 0;'>${banked_net:,.2f}</h1>
            <p style='margin:0; font-size:0.9rem; opacity:0.9;'>Gross Accrued: ${banked_gross:,.2f} • Tax Withheld: ${banked_gross - banked_net:,.2f}</p>
            <div style='margin-top:20px; padding-top:15px; border-top:1px solid rgba(255,255,255,0.2); display:flex; align-items:center;'>
                <span style='font-size:1.2rem; margin-right:10px;'>🏦</span> 
                <span style='font-size:0.95rem; font-weight:600;'>{b_name} •••• {b_last4}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        if banked_net > 0.01 and not st.session_state.user_state.get('active', False):
            if st.button("💸 TRANSFER TO BANK (STRIPE)", key="stripe_btn", use_container_width=True):
                tx_id = f"TX-{int(time.time())}"
                if run_transaction("INSERT INTO transactions (tx_id, pin, amount, timestamp, status) VALUES (:id, :p, :a, NOW(), 'PENDING_MGR')", {"id": tx_id, "p": pin, "a": banked_net}):
                    update_status(pin, "Inactive", 0, 0.0); st.session_state.user_state['earnings'] = 0.0
                    st.success("✅ Withdrawal Requested! Awaiting Manager & CFO verification."); time.sleep(1.5); st.rerun()
        elif st.session_state.user_state.get('active', False): st.info("You must clock out of your active shift before transferring funds.")
            
    else:
        st.markdown(f"<div class='glass-card' style='text-align:center;'><h3 style='color:#f8fafc; margin-bottom:5px;'>${banked_net:,.2f} Available</h3><p style='color:#94a3b8; font-size:0.9rem;'>You must securely link a financial institution to withdraw funds.</p></div>", unsafe_allow_html=True)
        with st.expander("🔗 Securely Link Bank Account (Powered by Plaid)", expanded=True):
            st.markdown("<div class='plaid-box'><h4 style='margin:0 0 10px 0; color:white;'>EC Protocol uses Plaid to link your bank</h4><p style='color:#888; font-size:0.85rem; margin-bottom:20px;'>Secure, encrypted, and compliant. We never see your login credentials.</p></div>", unsafe_allow_html=True)
            with st.form("plaid_mock_form"):
                st.selectbox("Select Institution", ["Chase", "Bank of America", "Wells Fargo", "Capital One", "Navy Federal"])
                acct_num = st.text_input("Account Number (Mock)", type="password")
                rout_num = st.text_input("Routing Number (Mock)", type="password")
                if st.form_submit_button("Authenticate & Link Account"):
                    if len(acct_num) > 3:
                        run_transaction("INSERT INTO hr_onboarding (pin, dd_bank, dd_acct_last4) VALUES (:p, :b, :l4) ON CONFLICT (pin) DO UPDATE SET dd_bank=:b, dd_acct_last4=:l4", {"p": pin, "b": "Chase", "l4": acct_num[-4:]})
                        st.success("✅ Secure Connection Established!"); time.sleep(1.5); st.rerun()
                    else: st.error("Please enter a valid mock account number.")

    st.markdown("<br>", unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["WITHDRAWAL HISTORY", "SHIFT LOGS", "PAY STUBS"])
    with tab1:
        res = run_query("SELECT timestamp, amount, status FROM transactions WHERE pin=:p ORDER BY timestamp DESC", {"p": pin})
        if res:
            for r in res:
                ts, amt, status = r[0], float(r[1]), r[2]
                display_status = "VERIFYING HOURS" if status == "PENDING_MGR" else "AWAITING CFO RELEASE" if status == "PENDING_CFO" else status
                color = "#10b981" if status == "APPROVED" else "#f59e0b" if "PENDING" in status else "#ff453a"
                st.markdown(f"<div class='glass-card' style='padding: 15px; margin-bottom: 10px; border-left: 4px solid {color} !important;'><div style='display: flex; justify-content: space-between;'><strong style='color: #f8fafc;'>Transfer Request</strong><strong style='color: {color};'>${amt:,.2f}</strong></div><div style='color: #94a3b8; font-size: 0.85rem; margin-top: 5px;'>{ts} | Status: <strong style='color:{color};'>{display_status}</strong></div></div>", unsafe_allow_html=True)
        else: st.info("No withdrawal history.")
    with tab2:
        res = run_query("SELECT timestamp, amount, note FROM history WHERE pin=:p AND action='CLOCK OUT' ORDER BY timestamp DESC LIMIT 30", {"p": pin})
        if res:
            for r in res:
                ts, amt, note = r[0], float(r[1]), r[2]
                st.markdown(f"<div class='glass-card' style='padding: 15px; margin-bottom: 10px; border-left: 4px solid #64748b !important;'><div style='display: flex; justify-content: space-between;'><strong style='color: #f8fafc;'>Shift Completed</strong><strong style='color: #38bdf8;'>${amt:,.2f}</strong></div><div style='color: #94a3b8; font-size: 0.85rem;'>{ts} | {note}</div></div>", unsafe_allow_html=True)
        else: st.info("No shifts worked yet.")
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
        if 'pdf_data' in st.session_state: st.download_button("📄 Download PDF Pay Stub", data=st.session_state.pdf_data, file_name=st.session_state.pdf_filename, mime="application/pdf")

elif nav == "MY PROFILE":
    st.markdown("## 🗄️ Enterprise HR Vault")
    if st.button("🔄 Refresh HR Profile"): st.rerun()
    
    t_lic, t_vax, t_tax, t_pto, t_sec = st.tabs(["🪪 LICENSES", "💉 VACCINES", "📑 ONBOARDING", "🏝️ TIME OFF", "🔐 SECURITY"])
    
    with t_sec:
        st.markdown("### Account Security")
        with st.form("update_password_form"):
            current_pw = st.text_input("Current Password", type="password")
            new_pw = st.text_input("New Password", type="password")
            confirm_pw = st.text_input("Confirm New Password", type="password")
            if st.form_submit_button("Update Password"):
                db_pw_res = run_query("SELECT password FROM account_security WHERE pin=:p", {"p": pin})
                active_password = db_pw_res[0][0] if db_pw_res else USERS[pin]["password"]
                if current_pw != active_password: st.error("❌ Current password incorrect.")
                elif new_pw != confirm_pw: st.error("❌ New passwords do not match.")
                elif len(new_pw) < 8: st.error("❌ Password must be at least 8 characters long.")
                else:
                    run_transaction("INSERT INTO account_security (pin, password) VALUES (:p, :pw) ON CONFLICT (pin) DO UPDATE SET password=:pw", {"p": pin, "pw": new_pw})
                    st.success("✅ Password successfully updated!"); time.sleep(2); st.rerun()
    with t_pto:
        with st.form("pto_form"):
            c1, c2 = st.columns(2)
            pto_start = c1.date_input("Start Date", min_value=date.today())
            pto_end = c2.date_input("End Date", min_value=pto_start)
            pto_reason = st.text_input("Reason / Notes (Optional)")
            if st.form_submit_button("Submit PTO Request to Manager"):
                run_transaction("INSERT INTO pto_requests (req_id, pin, start_date, end_date, reason) VALUES (:id, :p, :sd, :ed, :r)", {"id": f"PTO-{int(time.time())}", "p": pin, "sd": str(pto_start), "ed": str(pto_end), "r": pto_reason})
                st.success("✅ PTO Request Submitted!"); time.sleep(1.5); st.rerun()
        my_pto = run_query("SELECT start_date, end_date, status, reason FROM pto_requests WHERE pin=:p ORDER BY submitted DESC", {"p": pin})
        if my_pto:
            for req in my_pto:
                sd, ed, stat, rsn = req[0], req[1], req[2], req[3]
                color = "#10b981" if stat == "APPROVED" else "#f59e0b" if stat == "PENDING" else "#ff453a"
                st.markdown(f"<div class='glass-card' style='padding: 15px; margin-bottom: 10px; border-left: 4px solid {color} !important;'><div style='display: flex; justify-content: space-between;'><strong style='color: #f8fafc;'>{sd} to {ed}</strong><strong style='color: {color};'>{stat}</strong></div><div style='color: #94a3b8; font-size: 0.85rem; margin-top: 5px;'>Notes: {rsn}</div></div>", unsafe_allow_html=True)
    with t_lic:
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
    with t_vax: st.info("Vaccine Vault Active. Use add tools above to load immunization docs.")
    with t_tax:
        hr_rec = run_query("SELECT w4_filing_status FROM hr_onboarding WHERE pin=:p", {"p": pin})
        if hr_rec: st.success("✅ **ONBOARDING COMPLETE**")
        else: st.warning("⚠️ **ACTION REQUIRED: Please complete onboarding.**")
