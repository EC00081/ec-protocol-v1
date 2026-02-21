import streamlit as st
import pandas as pd
import time
import math
import pytz
import random
import os
from datetime import datetime
from collections import defaultdict
from streamlit_js_eval import get_geolocation
from streamlit_autorefresh import st_autorefresh
from sqlalchemy import create_engine, text

# --- NEW LIBRARIES ---
try:
    from twilio.rest import Client
    TWILIO_ACTIVE = True
except ImportError:
    TWILIO_ACTIVE = False

try:
    from fpdf import FPDF
    PDF_ACTIVE = True
except ImportError:
    PDF_ACTIVE = False

# --- 1. CONFIGURATION & STYLING ---
st.set_page_config(page_title="EC Enterprise", page_icon="🛡️", layout="centered", initial_sidebar_state="expanded")

html_style = """
<style>
    p, h1, h2, h3, h4, h5, h6, div, label, button, input { font-family: 'Inter', sans-serif !important; }
    .material-symbols-rounded, .material-icons { font-family: 'Material Symbols Rounded' !important; }
    
    .stApp { background: radial-gradient(circle at 50% 0%, #1e293b, #0f172a); color: #f8fafc; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {background: transparent !important;}
    div[data-testid="metric-container"] { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 16px; padding: 20px; box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1); backdrop-filter: blur(5px); }
    div[data-testid="metric-container"] label { color: #94a3b8; font-size: 0.8rem; }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #f8fafc; font-size: 1.8rem; font-weight: 800; }
    .stButton>button { width: 100%; height: 65px; border-radius: 12px; font-weight: 700; font-size: 1.1rem; border: none; transition: all 0.2s ease; text-transform: uppercase; letter-spacing: 1px; }
    .status-pill { display: flex; align-items: center; justify-content: center; padding: 12px; border-radius: 12px; font-weight: 700; font-size: 0.9rem; margin-bottom: 20px; letter-spacing: 1px; text-transform: uppercase; }
    .vip-mode { background: linear-gradient(135deg, #FFD700 0%, #B8860B 100%); color: #000; box-shadow: 0 0 20px rgba(255, 215, 0, 0.3); }
    .safe-mode { background: rgba(16, 185, 129, 0.2); border: 1px solid #10b981; color: #34d399; }
    .stTextInput>div>div>input { background-color: rgba(255,255,255,0.05); color: white; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); height: 50px; }
    .shift-card { background: rgba(255,255,255,0.03); border-left: 4px solid #3b82f6; padding: 15px; margin-bottom: 10px; border-radius: 0 12px 12px 0; }
    .admin-card { background: rgba(255, 69, 58, 0.1); border: 1px solid rgba(255, 69, 58, 0.3); padding: 20px; border-radius: 12px; margin-bottom: 15px; }
    .sched-date-header { background: rgba(255,255,255,0.1); padding: 10px 15px; border-radius: 8px; margin-top: 20px; margin-bottom: 10px; font-weight: 800; font-size: 1.2rem; border-left: 4px solid #10b981; }
    .sched-row { display: flex; justify-content: space-between; padding: 12px 15px; background: rgba(255,255,255,0.02); margin-bottom: 5px; border-radius: 6px; border-left: 4px solid rgba(255,255,255,0.1); }
    .sched-time { color: #34d399; font-weight: 700; width: 120px; }
    .sched-name { font-weight: 600; color: #f8fafc; }
    .sched-role { color: #94a3b8; font-size: 0.85rem; }
    .sched-callout { background: rgba(255, 69, 58, 0.05); border-left: 4px solid #ff453a; }
    .sched-market { background: rgba(245, 158, 11, 0.05); border-left: 4px solid #f59e0b; }
</style>
"""
st.markdown(html_style, unsafe_allow_html=True)

# --- 2. CONSTANTS & ORG CHART ---
TAX_RATES = {"FED": 0.22, "MA": 0.05, "SS": 0.062, "MED": 0.0145}
LOCAL_TZ = pytz.timezone('US/Eastern')
HOSPITALS = {"Brockton General": {"lat": 42.0875, "lon": -70.9915}, "Remote/Anywhere": {"lat": "ANY", "lon": "ANY"}}

USERS = {
    "1001": {"name": "Liam O'Neil", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 85.00, "phone": "+16175551234"},
    "1002": {"name": "Charles Morgan", "role": "RRT", "dept": "Respiratory", "level": "Worker", "rate": 85.00, "phone": None},
    "1003": {"name": "Sarah Jenkins", "role": "Charge RRT", "dept": "Respiratory", "level": "Supervisor", "rate": 90.00, "phone": None},
    "1004": {"name": "David Clark", "role": "Manager", "dept": "Respiratory", "level": "Manager", "rate": 0.00, "phone": None},
    "1005": {"name": "Dr. Alan Grant", "role": "Director", "dept": "Respiratory", "level": "Director", "rate": 0.00, "phone": None},
    "2001": {"name": "Emma Watson", "role": "RN", "dept": "Nursing", "level": "Worker", "rate": 75.00, "phone": None},
    "2002": {"name": "John Doe", "role": "RN", "dept": "Nursing", "level": "Worker", "rate": 75.00, "phone": None},
    "2003": {"name": "Alice Smith", "role": "Charge RN", "dept": "Nursing", "level": "Supervisor", "rate": 80.00, "phone": None},
    "2004": {"name": "Robert Brown", "role": "Manager", "dept": "Nursing", "level": "Manager", "rate": 0.00, "phone": None},
    "2005": {"name": "Dr. Sattler", "role": "Director", "dept": "Nursing", "level": "Director", "rate": 0.00, "phone": None},
    "3001": {"name": "Mia Wong", "role": "PCA", "dept": "PCA", "level": "Worker", "rate": 35.00, "phone": None},
    "3002": {"name": "Carlos Ruiz", "role": "PCA", "dept": "PCA", "level": "Worker", "rate": 35.00, "phone": None},
    "3003": {"name": "James Lee", "role": "Lead PCA", "dept": "PCA", "level": "Supervisor", "rate": 40.00, "phone": None},
    "3004": {"name": "Linda Davis", "role": "Manager", "dept": "PCA", "level": "Manager", "rate": 0.00, "phone": None},
    "3005": {"name": "Dr. Malcolm", "role": "Director", "dept": "PCA", "level": "Director", "rate": 0.00, "phone": None},
    "9999": {"name": "CFO VIEW", "role": "Admin", "dept": "All", "level": "Admin", "rate": 0.00, "phone": None}
}

# --- 3. DATABASE ENGINE & AUTO-MIGRATION ---
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
        # AUTO-MIGRATION: Safely ensure the status column exists for the new features
        with engine.connect() as conn:
            try: 
                conn.execute(text("ALTER TABLE schedules ADD COLUMN status text DEFAULT 'SCHEDULED';"))
                conn.commit()
            except: pass
        return engine
    except: return None

def run_query(query, params=None):
    engine = get_db_engine()
    if not engine: return None
    try:
        with engine.connect() as conn:
            return conn.execute(text(query), params or {}).fetchall() 
    except: return None

def run_transaction(query, params=None):
    engine = get_db_engine()
    if not engine: return False
    try:
        with engine.connect() as conn:
            conn.execute(text(query), params or {})
            conn.commit() 
        return True
    except: return False

# --- 4. CORE DB LOGIC ---
def force_cloud_sync(pin):
    try:
        rows = run_query("SELECT status, start_time FROM workers WHERE pin = :pin", {"pin": pin})
        if rows and len(rows) > 0 and rows[0][0].lower() == 'active':
            st.session_state.user_state['active'] = True
            st.session_state.user_state['start_time'] = float(rows[0][1])
            return True
        st.session_state.user_state['active'] = False
        return False
    except: return False

def update_status(pin, status, start, earn):
    q = """INSERT INTO workers (pin, status, start_time, earnings, last_active) VALUES (:p, :s, :t, :e, NOW())
           ON CONFLICT (pin) DO UPDATE SET status = :s, start_time = :t, earnings = :e, last_active = NOW();"""
    return run_transaction(q, {"p": pin, "s": status, "t": start, "e": earn})

def log_action(pin, action, amount, note):
    run_transaction("INSERT INTO history (pin, action, timestamp, amount, note) VALUES (:p, :a, NOW(), :amt, :n)", {"p": pin, "a": action, "amt": amount, "n": note})

# --- 5. AUTH SCREEN ---
if 'user_state' not in st.session_state: st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0, 'payout_lock': False}

if 'logged_in_user' not in st.session_state:
    st.markdown("<br><br><br><h1 style='text-align: center; color: #f8fafc; letter-spacing: 2px;'>EC PROTOCOL</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #64748b; font-size: 0.9rem;'>SECURE WORKFORCE ACCESS</p><br>", unsafe_allow_html=True)
    pin = st.text_input("ACCESS CODE", type="password", placeholder="Enter your 4-digit PIN")
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("AUTHENTICATE SYSTEM"):
        if pin in USERS:
            st.session_state.logged_in_user = USERS[pin]
            st.session_state.pin = pin
            force_cloud_sync(pin)
            st.rerun()
        else: st.error("INVALID CREDENTIALS")
    st.stop()

user = st.session_state.logged_in_user
pin = st.session_state.pin

# --- 6. DYNAMIC NAVIGATION ---
with st.sidebar:
    st.caption(f"{user['name'].upper()} | {user['role']}")
    if get_db_engine(): st.success("🟢 DB CONNECTED")
    else: st.error("🔴 DB DISCONNECTED")
    
    if user['level'] == "Admin": nav = st.radio("MENU", ["COMMAND CENTER", "MASTER SCHEDULE", "AUDIT LOGS"])
    elif user['level'] in ["Manager", "Director"]: nav = st.radio("MENU", ["DASHBOARD", "DEPT MARKETPLACE", "DEPT SCHEDULE", "MY LOGS"])
    else: nav = st.radio("MENU", ["DASHBOARD", "MARKETPLACE", "MY SCHEDULE", "MY LOGS"])
        
    if st.button("LOGOUT"): st.session_state.clear(); st.rerun()

# --- 7. ROUTING ---
if nav == "COMMAND CENTER" and pin == "9999":
    st.markdown("## 🦅 Command Center")
    st.caption("Live Fleet Overview")
    rows = run_query("SELECT pin, status, start_time, earnings FROM workers WHERE status='Active'")
    if rows:
        for r in rows:
            w_pin = str(r[0]); w_name = USERS.get(w_pin, {}).get("name", f"Unknown ({w_pin})"); w_role = USERS.get(w_pin, {}).get("role", "Worker")
            hrs = (time.time() - float(r[2])) / 3600; current_earn = hrs * USERS.get(w_pin, {}).get("rate", 85)
            
            st.markdown(f"""<div class="admin-card"><h3 style="margin:0;">{w_name} <span style='color:#94a3b8; font-size:1rem;'>| {w_role}</span></h3>
                <p style="color:#ff453a; margin-top:5px; font-weight:bold;">🟢 ACTIVE (On Clock: {hrs:.2f} hrs | Accrued: ${current_earn:.2f})</p></div>""", unsafe_allow_html=True)
            if st.button(f"🚨 FORCE CLOCK-OUT: {w_name}", key=f"force_{w_pin}"):
                update_status(w_pin, "Inactive", 0, 0); log_action("9999", "ADMIN FORCE LOGOUT", current_earn, f"Target: {w_name}")
                st.success(f"Closed shift for {w_name}"); time.sleep(1.5); st.rerun()
    else: st.info("No operators currently active.")

elif nav == "DASHBOARD":
    st.markdown(f"<h2>Good Morning, {user['name'].split(' ')[0]}</h2>", unsafe_allow_html=True)
    active = st.session_state.user_state['active']
    if active: hrs = (time.time() - st.session_state.user_state['start_time']) / 3600; st.session_state.user_state['earnings'] = hrs * user['rate']
    gross = st.session_state.user_state['earnings']; net = gross * (1 - sum(TAX_RATES.values()))
    
    c1, c2 = st.columns(2)
    c1.metric("CURRENT EARNINGS", f"${gross:,.2f}"); c2.metric("NET PAYOUT", f"${net:,.2f}")
    st.markdown("<br>", unsafe_allow_html=True)

    if active:
        if st.button("🔴 END SHIFT"):
            if update_status(pin, "Inactive", 0, 0):
                st.session_state.user_state['active'] = False; log_action(pin, "CLOCK OUT", gross, "Standard"); st.rerun()
    else:
        selected_facility = st.selectbox("Select Facility", list(HOSPITALS.keys()))
        if st.button("🟢 START SHIFT"):
            start_t = time.time()
            if update_status(pin, "Active", start_t, 0):
                st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t
                log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()

    if not active and gross > 0.01:
        if st.button(f"💸 INSTANT TRANSFER (${net:,.2f})", disabled=st.session_state.user_state['payout_lock']):
            st.session_state.user_state['payout_lock'] = True; log_action(pin, "PAYOUT", net, "Settled"); update_status(pin, "Inactive", 0, 0)
            st.session_state.user_state['earnings'] = 0.0; time.sleep(1); st.session_state.user_state['payout_lock'] = False; st.rerun()

elif nav in ["MARKETPLACE", "DEPT MARKETPLACE"]:
    st.markdown(f"## 🏥 {user['dept']} Shift Exchange")
    tab1, tab2 = st.tabs(["OPEN SHIFTS", "POST NEW"])
    with tab1:
        q = f"SELECT shift_id, poster_pin, role, date, start_time, end_time, rate FROM marketplace WHERE status='OPEN' AND role LIKE '%%{user['dept']}%%'"
        res = run_query(q)
        if res:
            for s in res:
                poster_name = USERS.get(str(s[1]), {}).get("name", "Unknown Poster")
                st.markdown(f"""<div class="shift-card"><div style="font-weight:bold; font-size:1.1rem;">{s[3]} | {s[2]}</div>
                    <div style="color:#94a3b8;">{s[4]} - {s[5]} @ ${s[6]}/hr</div>
                    <div style="color:#64748b; font-size:0.8rem; margin-top:5px;">Posted by: {poster_name}</div></div>""", unsafe_allow_html=True)
                if user['level'] in ["Worker", "Supervisor"] and st.button("CLAIM", key=s[0]):
                    # Claim the marketplace shift
                    run_transaction("UPDATE marketplace SET status='CLAIMED', claimed_by=:p WHERE shift_id=:id", {"p": pin, "id": s[0]})
                    # AUTONOMOUS SWAP: If this came from a dropped schedule, update the master schedule to the new owner!
                    run_transaction("UPDATE schedules SET pin=:p, status='SCHEDULED' WHERE shift_id=:id", {"p": pin, "id": s[0]})
                    st.success("✅ Claimed & Added to your Schedule!")
                    time.sleep(1); st.rerun()
        else: st.info("No open shifts in this department.")

    with tab2:
        with st.form("new_shift"):
            shift_loc = st.selectbox("Facility", list(HOSPITALS.keys()))
            d = st.date_input("Date")
            c1, c2 = st.columns(2)
            s_time = c1.time_input("Start"); e_time = c2.time_input("End")
            if st.form_submit_button("PUBLISH TO MARKET"):
                s_id = f"SHIFT-{int(time.time())}"
                r_loc = f"{user['role']} ({user['dept']}) @ {shift_loc}"
                run_transaction("INSERT INTO marketplace (shift_id, poster_pin, role, date, start_time, end_time, rate, status) VALUES (:id, :p, :r, :d, :s, :e, :rt, 'OPEN')", 
                                {"id": s_id, "p": pin, "r": r_loc, "d": d, "s": str(s_time), "e": str(e_time), "rt": user['rate']})
                st.success("Shift Published!")

elif nav in ["MY SCHEDULE", "DEPT SCHEDULE", "MASTER SCHEDULE"]:
    st.markdown(f"## 📅 System Schedule")
    
    # WORKER INTERACTIVE BLOCK: Manage Call Outs & Trades
    if user['level'] in ["Worker", "Supervisor"]:
        with st.expander("🙋 MY UPCOMING SHIFTS (Manage Exceptions)", expanded=True):
            my_scheds = run_query("SELECT shift_id, shift_date, shift_time, COALESCE(status, 'SCHEDULED') FROM schedules WHERE pin=:p ORDER BY shift_date ASC", {"p": pin})
            if my_scheds:
                for s in my_scheds:
                    s_id, s_date, s_time, s_status = s[0], s[1], s[2], s[3]
                    if s_status == 'SCHEDULED':
                        st.markdown(f"**{s_date}** | {s_time}")
                        c1, c2 = st.columns(2)
                        if c1.button("🚨 CALL OUT (Sick)", key=f"co_{s_id}"):
                            run_transaction("UPDATE schedules SET status='CALL_OUT' WHERE shift_id=:id", {"id": s_id})
                            st.rerun()
                        if c2.button("🔄 TRADE SHIFT", key=f"tr_{s_id}"):
                            run_transaction("UPDATE schedules SET status='MARKETPLACE' WHERE shift_id=:id", {"id": s_id})
                            t_split = s_time.split("-")
                            st_t, en_t = (t_split[0], t_split[1]) if len(t_split)==2 else ("0000", "0000")
                            run_transaction("INSERT INTO marketplace (shift_id, poster_pin, role, date, start_time, end_time, rate, status) VALUES (:id, :p, :r, :d, :s, :e, :rt, 'OPEN')", 
                                            {"id": s_id, "p": pin, "r": f"{user['role']} ({user['dept']}) - Coverage Req", "d": s_date, "s": st_t, "e": en_t, "rt": user['rate']})
                            st.rerun()
                        st.markdown("<hr style='margin:5px 0; opacity:0.2'>", unsafe_allow_html=True)
                    elif s_status == 'CALL_OUT':
                        st.error(f"🚨 {s_date} | {s_time} (SICK LEAVE PENDING MANAGER REVIEW)")
                    elif s_status == 'MARKETPLACE':
                        st.warning(f"🔄 {s_date} | {s_time} (PENDING COVERAGE ON MARKETPLACE)")
            else:
                st.info("You have no upcoming shifts assigned.")

    # MANAGER TOOLS (ASSIGN & REMOVE)
    if user['level'] in ["Manager", "Director", "Admin"]:
        col1, col2 = st.columns(2)
        with col1:
            with st.expander("🛠️ ASSIGN SHIFT"):
                with st.form("assign_sched"):
                    available_staff = {p: u['name'] for p, u in USERS.items() if (u['dept'] == user['dept'] or user['dept'] == "All") and u['level'] in ["Worker", "Supervisor"]}
                    target_pin = st.selectbox("Staff Member", options=list(available_staff.keys()), format_func=lambda x: available_staff[x])
                    s_date = st.date_input("Shift Date")
                    s_time = st.text_input("Time (e.g., 0700-1900)")
                    if st.form_submit_button("Publish Shift"):
                        db_success = run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')",
                                        {"id": f"SCH-{int(time.time())}", "p": str(target_pin), "d": str(s_date), "t": str(s_time), "dept": USERS[target_pin]['dept']})
                        if db_success: st.success(f"✅ Assigned to {available_staff[target_pin]}"); time.sleep(1); st.rerun()
                        else: st.error("❌ Database Error.")
        with col2:
            with st.expander("🗑️ REMOVE SHIFT"):
                scheds_to_remove = run_query("SELECT shift_id, pin, shift_date, shift_time FROM schedules WHERE department=:d", {"d": user['dept']}) if user['level'] != "Admin" else run_query("SELECT shift_id, pin, shift_date, shift_time FROM schedules")
                if scheds_to_remove:
                    with st.form("remove_sched"):
                        shift_options = {s[0]: f"{s[2]} | {USERS.get(str(s[1]), {}).get('name', s[1])} ({s[3]})" for s in scheds_to_remove}
                        target_shift = st.selectbox("Select Shift to Delete", options=list(shift_options.keys()), format_func=lambda x: shift_options[x])
                        if st.form_submit_button("Delete Shift"):
                            if run_transaction("DELETE FROM schedules WHERE shift_id=:id", {"id": target_shift}): st.success("✅ Shift Removed"); time.sleep(1); st.rerun()
                            else: st.error("❌ Database Error.")
                else: st.info("No shifts scheduled.")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # DB FETCH: MASTER CALENDAR (Now includes COALESCE status)
    if user['level'] == "Admin":
        scheds = run_query("SELECT shift_id, pin, shift_date, shift_time, department, COALESCE(status, 'SCHEDULED') FROM schedules ORDER BY shift_date ASC, shift_time ASC")
    else:
        scheds = run_query("SELECT shift_id, pin, shift_date, shift_time, department, COALESCE(status, 'SCHEDULED') FROM schedules WHERE department=:d ORDER BY shift_date ASC, shift_time ASC", {"d": user['dept']})
    
    # RENDER THE SCHEDULE CHRONOLOGICALLY
    if scheds:
        grouped_shifts = defaultdict(list)
        for s in scheds: grouped_shifts[s[2]].append(s) 
            
        for date in sorted(grouped_shifts.keys()):
            shifts = grouped_shifts[date]
            try: formatted_date = datetime.strptime(date, "%Y-%m-%d").strftime("%A, %B %d, %Y")
            except: formatted_date = date

            st.markdown(f"<div class='sched-date-header'>🗓️ {formatted_date}</div>", unsafe_allow_html=True)
            
            for shift in shifts:
                owner_pin = str(shift[1]); owner_name = USERS.get(owner_pin, {}).get('name', f"Unknown User ({owner_pin})")
                owner_role = USERS.get(owner_pin, {}).get('role', ""); time_block = shift[3]; status = shift[5]
                
                # Dynamic CSS classes based on Call-Out or Trade status
                css_class = "sched-row"
                status_label = ""
                if status == "CALL_OUT":
                    css_class += " sched-callout"
                    status_label = "<span style='color:#ff453a; font-weight:bold; font-size:0.8rem; border:1px solid #ff453a; padding:2px 6px; border-radius:4px; margin-left:10px;'>🚨 SICK</span>"
                elif status == "MARKETPLACE":
                    css_class += " sched-market"
                    status_label = "<span style='color:#f59e0b; font-weight:bold; font-size:0.8rem; border:1px solid #f59e0b; padding:2px 6px; border-radius:4px; margin-left:10px;'>🔄 TRADING</span>"
                
                personal_indicator = "⭐ " if owner_pin == pin else ""
                
                st.markdown(f"""
                <div class='{css_class}'>
                    <div class='sched-time'>{time_block}</div>
                    <div style='flex-grow: 1; text-align: left; padding-left: 15px;'>
                        <span class='sched-name'>{personal_indicator}{owner_name}</span> 
                        <span class='sched-role'>| {owner_role}</span> {status_label}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else: 
        st.info("No shifts are currently scheduled.")

elif "LOGS" in nav:
    st.markdown("## 📂 System Records")
    if user['level'] == "Admin": q = "SELECT pin, action, timestamp, amount, note FROM history ORDER BY timestamp DESC LIMIT 50"; res = run_query(q)
    else: q = "SELECT pin, action, timestamp, amount, note FROM history WHERE pin=:p ORDER BY timestamp DESC"; res = run_query(q, {"p": pin})
    if res: st.dataframe(pd.DataFrame(res, columns=["User PIN", "Action", "Time", "Amount", "Note"]), use_container_width=True)
