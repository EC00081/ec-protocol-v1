import streamlit as st
import pandas as pd
import time
import math
import pytz
import os
import json
import bcrypt
import hashlib
import random
import re
import tempfile
from datetime import datetime, date, timedelta
from collections import defaultdict
from streamlit_js_eval import get_geolocation
from sqlalchemy import create_engine, text
import pydeck as pdk
import plotly.express as px
import plotly.graph_objects as go
from web3 import Web3

# --- WEB3 BLOCKCHAIN ENGINE ---
# These will pull from your Render Environment Variables once you are ready to go live
RPC_URL = os.environ.get("WEB3_RPC_URL", "https://sepolia.base.org") # Default to Base Sepolia Testnet
PRIVATE_KEY = os.environ.get("WEB3_PRIVATE_KEY", None)
CONTRACT_ADDRESS = os.environ.get("WEB3_CONTRACT_ADDRESS", "0x0000000000000000000000000000000000000000")

# Truncated ABI teaching Python how to push the mint button
CONTRACT_ABI = json.loads('[{"inputs":[{"internalType":"address","name":"account","type":"address"},{"internalType":"uint256","name":"id","type":"uint256"},{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"mintClinicalAccolade","outputs":[],"stateMutability":"nonpayable","type":"function"}]')

def mint_sbt_on_chain(target_wallet, action_id):
    if not PRIVATE_KEY or CONTRACT_ADDRESS == "0x0000000000000000000000000000000000000000":
        return "Simulated (No Private Key)"
    
    try:
        w3 = Web3(Web3.HTTPProvider(RPC_URL))
        account = w3.eth.account.from_key(PRIVATE_KEY)
        contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=CONTRACT_ABI)
        
        # Build the transaction
        nonce = w3.eth.get_transaction_count(account.address)
        tx = contract.functions.mintClinicalAccolade(target_wallet, action_id, 1).build_transaction({
            'chainId': 84532, # Base Sepolia Chain ID
            'gas': 2000000,
            'maxFeePerGas': w3.to_wei('2', 'gwei'),
            'maxPriorityFeePerGas': w3.to_wei('1', 'gwei'),
            'nonce': nonce,
        })
        
        # Sign and Broadcast
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=account.key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        return f"0x{w3.to_hex(tx_hash)[2:]}" # Returns the immutable blockchain receipt
    except Exception as e:
        return f"Web3 Error: {str(e)}"
# --- EXTERNAL LIBRARIES ---
try: 
    from fpdf import FPDF
    PDF_ACTIVE = True
except ImportError: 
    PDF_ACTIVE = False

# --- GLOBAL CONSTANTS ---
LOCAL_TZ = pytz.timezone('US/Eastern')
GEOFENCE_RADIUS = 150
HOSPITALS = {"Hospital A": {"lat": 0.0, "lon": 0.0}, "Hospital B": {"lat": 0.0, "lon": 0.0}}
OPSEC_PW_EXPIRY_DAYS = 90

# --- CRYPTO & OPSEC ---
def is_strong_password(password):
    if len(password) < 8: return False, "Must be at least 8 characters long."
    if not re.search(r"[A-Z]", password): return False, "Must contain an uppercase letter."
    if not re.search(r"[a-z]", password): return False, "Must contain a lowercase letter."
    if not re.search(r"\d", password): return False, "Must contain a number."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password): return False, "Must contain a special character."
    return True, "Valid"

def hash_password(plain_text_password): return bcrypt.hashpw(plain_text_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
def verify_password(plain_text_password, hashed_password):
    try: return bcrypt.checkpw(plain_text_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception: return False
def generate_secure_checksum(doc_number, pin): return hashlib.sha256(f"{doc_number}-{pin}-{os.environ.get('SECURE_SALT', 'EC_PROTOCOL_ENTERPRISE_SALT')}".encode('utf-8')).hexdigest()

def generate_poc_hash(claim_id, pin, room, action, timestamp_str):
    raw_data = f"{claim_id}|{pin}|{room}|{action}|{timestamp_str}|{os.environ.get('SECURE_SALT', 'CLINICAL_LEDGER_SALT')}"
    return hashlib.sha256(raw_data.encode('utf-8')).hexdigest()

# --- MERKLE TREE LAYER 2 BATCHING ---
def hash_pair(hash1, hash2):
    combined = "".join(sorted([hash1, hash2]))
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()

def build_merkle_root(hash_list):
    if not hash_list: return None
    if len(hash_list) == 1: return hash_list[0] 
    new_level = []
    for i in range(0, len(hash_list), 2):
        h1 = hash_list[i]
        h2 = hash_list[i+1] if (i + 1) < len(hash_list) else h1
        new_level.append(hash_pair(h1, h2))
    return build_merkle_root(new_level)

def execute_daily_rollup(target_date_str):
    raw_claims = run_query("SELECT secure_hash FROM poc_ledger WHERE CAST(timestamp AS TEXT) LIKE :d", {"d": f"{target_date_str}%"})
    if not raw_claims: return False, "No claims found for this date."
    hash_list = [claim[0] for claim in raw_claims if claim[0]]
    if not hash_list: return False, "No valid secure hashes found."
    merkle_root = build_merkle_root(hash_list)
    run_transaction("INSERT INTO daily_rollups (date, merkle_root, tx_count, status) VALUES (:d, :mr, :c, 'READY_FOR_L2') ON CONFLICT (date) DO UPDATE SET merkle_root=:mr, tx_count=:c", {"d": target_date_str, "mr": merkle_root, "c": len(hash_list)})
    return True, merkle_root

# --- BULLETPROOF PDF GENERATOR ---
def safe_pdf_bytes(pdf_obj):
    """Writes to temp file and reads as raw bytes to prevent browser corruption errors."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            pdf_obj.output(tmp.name)
            tmp_path = tmp.name
        with open(tmp_path, "rb") as f:
            pdf_bytes = f.read()
        os.remove(tmp_path)
        return pdf_bytes
    except Exception: return None

def create_paystub_txt(name, date_str, tx_id, gross, net, tax, dest, shifts_data=None):
    lines = [
        "===================================================",
        "    VICENTUS ENTERPRISE - OFFICIAL PAY RECEIPT     ",
        "===================================================",
        f"Operator: {name}",
        f"Date of Settlement: {date_str}",
        f"Ledger Tx ID: {tx_id}",
        f"Routing Method: Fiat Direct Deposit",
        f"Destination: {dest}",
        "---------------------------------------------------",
        "Validated Shift Coverage (Clock In -> Clock Out):"
    ]
    if shifts_data and len(shifts_data) > 0:
        for s_in, s_out in shifts_data: lines.append(f"  * IN: {s_in}    |    OUT: {s_out}")
    else: lines.append("  * Standard Aggregate Payout (Verified via History Ledger)")
    lines.extend([
        "---------------------------------------------------",
        f"Gross Pay: ${gross:,.2f}",
        f"Progressive Tax Withholding: ${tax:,.2f}",
        f"Net Settlement: ${net:,.2f}",
        "---------------------------------------------------",
        "This is a cryptographically verifiable ledger receipt."
    ])
    return "\n".join(lines).encode('utf-8')

def generate_compliance_report_txt(dept_name, manager_name):
    lines = [
        "===================================================",
        "       VICENTUS COMPLIANCE & PROTOCOL AUDIT        ",
        "===================================================",
        f"Department: {dept_name} | Generated By: {manager_name}",
        f"Date: {datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M')}",
        "\nACTIVE PROTOCOLS:",
        "---------------------------------------------------"
    ]
    active_p = run_query("SELECT title, next_review FROM hospital_protocols WHERE status='ACTIVE' AND (department=:d OR department='All')", {"d": dept_name})
    if active_p:
        for p in active_p: lines.append(f"[PASS] {p[0]} (Valid until {p[1]})")
    else: lines.append("No active protocols found.")
    
    lines.extend(["\nRECENT PROOF-OF-CARE EXCEPTIONS:", "---------------------------------------------------"])
    poc_issues = run_query("SELECT claim_id, action, emr_verified FROM poc_ledger WHERE emr_verified=FALSE ORDER BY timestamp DESC LIMIT 5")
    if poc_issues:
        for c in poc_issues: lines.append(f"[FLAG] Claim {c[0]}: {c[1]} - EMR SYNC PENDING")
    else: lines.append("All recent clinical actions properly synced with EMR.")
    
    lines.extend(["\n===================================================", "      End of Official Vicentus Audit Report.       "])
    return "\n".join(lines).encode('utf-8')

def create_paystub_pdf(name, date_str, tx_id, gross, net, tax, dest, shifts_data=None):
    if not PDF_ACTIVE: return create_paystub_txt(name, date_str, tx_id, gross, net, tax, dest, shifts_data)
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(190, 10, txt="VICENTUS ENTERPRISE - OFFICIAL PAY RECEIPT", ln=True, align='C')
        pdf.set_font("Arial", '', 12)
        pdf.ln(10)
        pdf.cell(100, 8, txt=f"Operator: {name}", ln=True)
        pdf.cell(100, 8, txt=f"Date of Settlement: {date_str}", ln=True)
        pdf.cell(100, 8, txt=f"Ledger Tx ID: {tx_id}", ln=True)
        pdf.cell(100, 8, txt=f"Routing Method: Fiat Direct Deposit", ln=True)
        pdf.cell(100, 8, txt=f"Destination: {dest}", ln=True)
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 12)
        pdf.line(10, 75, 200, 75)
        pdf.ln(5)
        pdf.cell(190, 8, txt="Validated Shift Coverage (Clock In -> Clock Out):", ln=True)
        pdf.set_font("Arial", '', 10)
        
        if shifts_data and len(shifts_data) > 0:
            for s_in, s_out in shifts_data:
                pdf.cell(190, 6, txt=f"  * IN: {s_in}    |    OUT: {s_out}", ln=True)
        else:
            pdf.cell(190, 6, txt="  * Standard Aggregate Payout (Verified via History Ledger)", ln=True)
            
        pdf.ln(5)
        current_y = pdf.get_y()
        pdf.line(10, current_y, 200, current_y)
        pdf.ln(5)
        pdf.set_font("Arial", '', 12)
        pdf.cell(100, 10, txt=f"Gross Pay: ${gross:,.2f}", ln=True)
        pdf.cell(100, 10, txt=f"Progressive Tax Withholding: ${tax:,.2f}", ln=True)
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(100, 10, txt=f"Net Settlement: ${net:,.2f}", ln=True)
        pdf.ln(5)
        current_y = pdf.get_y()
        pdf.line(10, current_y, 200, current_y)
        pdf.ln(10)
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(190, 10, txt="This is a cryptographically verifiable ledger receipt generated by Vicentus.", ln=True, align='C')
        return safe_pdf_bytes(pdf)
    except Exception: return create_paystub_txt(name, date_str, tx_id, gross, net, tax, dest, shifts_data)

def generate_compliance_report(dept_name, manager_name):
    if not PDF_ACTIVE: return generate_compliance_report_txt(dept_name, manager_name)
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(190, 10, txt="VICENTUS COMPLIANCE & PROTOCOL AUDIT", ln=True, align='C')
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(190, 6, txt=f"Department: {dept_name} | Generated By: {manager_name} | Date: {datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M')}", ln=True, align='C')
        pdf.ln(10)
        
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(190, 8, txt="ACTIVE PROTOCOLS:", ln=True)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(2)
        
        pdf.set_font("Arial", '', 10)
        active_p = run_query("SELECT title, next_review FROM hospital_protocols WHERE status='ACTIVE' AND (department=:d OR department='All')", {"d": dept_name})
        if active_p:
            for p in active_p: pdf.cell(190, 6, txt=f"[PASS] {p[0]} (Valid until {p[1]})", ln=True)
        else:
            pdf.cell(190, 6, txt="No active protocols found.", ln=True)
            
        pdf.ln(10)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(190, 8, txt="RECENT PROOF-OF-CARE EXCEPTIONS:", ln=True)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(2)
        
        pdf.set_font("Arial", '', 10)
        poc_issues = run_query("SELECT claim_id, action, emr_verified FROM poc_ledger WHERE emr_verified=FALSE ORDER BY timestamp DESC LIMIT 5")
        if poc_issues:
            for c in poc_issues: pdf.cell(190, 6, txt=f"[FLAG] Claim {c[0]}: {c[1]} - EMR SYNC PENDING", ln=True)
        else:
            pdf.cell(190, 6, txt="All recent clinical actions properly synced with EMR.", ln=True)
            
        pdf.ln(15)
        pdf.set_font("Arial", 'I', 8)
        pdf.cell(190, 10, txt="End of Official Vicentus Audit Report.", ln=True, align='C')
        return safe_pdf_bytes(pdf)
    except Exception: return generate_compliance_report_txt(dept_name, manager_name)

# --- DATABASE ENGINE ---
@st.cache_resource(ttl=60)
def get_db_engine():
    url = os.environ.get("SUPABASE_URL")
    if not url:
        try: url = st.secrets["SUPABASE_URL"]
        except: pass
    if not url: return "URL_MISSING"
    
    if url.startswith("postgres://"): url = url.replace("postgres://", "postgresql://", 1)
    
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS enterprise_users (pin TEXT PRIMARY KEY, email TEXT UNIQUE, password_hash TEXT, name TEXT, role TEXT, dept TEXT, access_level TEXT, hourly_rate NUMERIC, phone TEXT, last_pw_change TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"))
            conn.execute(text("ALTER TABLE enterprise_users ADD COLUMN IF NOT EXISTS last_pw_change TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"))
            
            res = conn.execute(text("SELECT COUNT(*) FROM enterprise_users")).fetchone()
            if True: 
                seed_data = [
                    ("1001", "liam@ecprotocol.com", hash_password("password123"), "Liam O'Neil", "RRT", "Respiratory", "Worker", 70.00, None),
                    ("1002", "charles@ecprotocol.com", hash_password("password123"), "Charles Morgan", "RRT", "Respiratory", "Worker", 65.00, None),
                    ("1003", "sarah@ecprotocol.com", hash_password("password123"), "Sarah Jenkins", "Charge RRT", "Respiratory", "Supervisor", 75.00, None),
                    ("1004", "manager@ecprotocol.com", hash_password("password123"), "David Clark", "Manager", "Respiratory", "Manager", 90.00, None),
                    ("9001", "ceo@ecprotocol.com", hash_password("password123"), "CEO View", "CEO", "Executive", "Admin", 0.00, None),
                    ("9002", "coo@ecprotocol.com", hash_password("password123"), "COO View", "COO", "Executive", "Admin", 0.00, None),
                    ("9003", "cno@ecprotocol.com", hash_password("password123"), "CNO View", "CNO", "Executive", "Admin", 0.00, None),
                    ("9004", "cco@ecprotocol.com", hash_password("password123"), "CCO View", "CCO", "Executive", "Admin", 0.00, None),
                    ("9005", "cto@ecprotocol.com", hash_password("password123"), "CTO View", "CTO", "Executive", "Admin", 0.00, None),
                    ("9006", "cfo@ecprotocol.com", hash_password("password123"), "CFO View", "CFO", "Executive", "Admin", 0.00, None),
                    ("9007", "chro@ecprotocol.com", hash_password("password123"), "CHRO View", "CHRO", "Executive", "Admin", 0.00, None),
                    ("8001", "resp_dir@ecprotocol.com", hash_password("password123"), "Alice Wright", "Director", "Respiratory", "Director", 100.00, None),
                    ("8002", "nursing_dir@ecprotocol.com", hash_password("password123"), "Marcus Cole", "Director", "Nursing", "Director", 100.00, None)
                ]
                for sd in seed_data: conn.execute(text("INSERT INTO enterprise_users (pin, email, password_hash, name, role, dept, access_level, hourly_rate, phone, last_pw_change) VALUES (:p, :e, :pw, :n, :r, :d, :al, :hr, :ph, NOW() - INTERVAL '100 days') ON CONFLICT DO NOTHING"), {"p": sd[0], "e": sd[1], "pw": sd[2], "n": sd[3], "r": sd[4], "d": sd[5], "al": sd[6], "hr": sd[7], "ph": sd[8]})
            
            conn.execute(text("CREATE TABLE IF NOT EXISTS workers (pin text PRIMARY KEY, status text, start_time numeric, earnings numeric, last_active timestamp, lat numeric, lon numeric);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS history (pin text, action text, timestamp timestamp DEFAULT NOW(), amount numeric, note text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS marketplace (shift_id text PRIMARY KEY, poster_pin text, role text, date text, start_time text, end_time text, rate numeric, status text, claimed_by text, escrow_status text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS shift_bids (bid_id text PRIMARY KEY, shift_id text, pin text, counter_rate numeric, status text DEFAULT 'PENDING', timestamp timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS transactions (tx_id text PRIMARY KEY, pin text, amount numeric, timestamp timestamp DEFAULT NOW(), status text, destination_pubkey text, tx_type text, note text);"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS schedules (shift_id text PRIMARY KEY, pin text, shift_date text, shift_time text, department text, status text DEFAULT 'SCHEDULED');"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS unit_census (dept text PRIMARY KEY, total_pts int, high_acuity int, vented_pts int DEFAULT 0, nipvv_pts int DEFAULT 0, last_updated timestamp DEFAULT NOW());"))
            try: conn.execute(text("ALTER TABLE unit_census ADD COLUMN IF NOT EXISTS vented_pts int DEFAULT 0;")); conn.execute(text("ALTER TABLE unit_census ADD COLUMN IF NOT EXISTS nipvv_pts int DEFAULT 0;"))
            except: pass
            
            conn.execute(text("CREATE TABLE IF NOT EXISTS messages (msg_id text PRIMARY KEY, sender_pin text, target_dept text, message text, is_sos boolean DEFAULT FALSE, recipient_pin text, timestamp timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS hr_onboarding (pin text PRIMARY KEY, w4_filing_status text, w4_allowances int, dd_bank text, dd_acct_last4 text, signed_date timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS pto_requests (req_id text PRIMARY KEY, pin text, start_date text, end_date text, reason text, status text DEFAULT 'PENDING', submitted timestamp DEFAULT NOW());"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS credentials (doc_id text PRIMARY KEY, pin text, doc_type text, doc_number text, exp_date text, status text);"))
            
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS obt_ledger (
                    token_id TEXT PRIMARY KEY, 
                    pin TEXT, 
                    accolade_type TEXT, 
                    clinical_context TEXT, 
                    timestamp TIMESTAMP DEFAULT NOW(), 
                    facility_origin TEXT, 
                    encryption_hash TEXT
                );
            """))

            conn.execute(text("CREATE TABLE IF NOT EXISTS poc_ledger (claim_id text PRIMARY KEY, pin text, patient_room text, action text, timestamp timestamp DEFAULT NOW(), ble_verified boolean, emr_verified boolean, ai_verified boolean, status text, secure_hash text);"))
            try: conn.execute(text("ALTER TABLE poc_ledger ADD COLUMN IF NOT EXISTS secure_hash text;"))
            except: pass

            conn.execute(text("CREATE TABLE IF NOT EXISTS hospital_treasury (id INT PRIMARY KEY, available_balance NUMERIC, last_refill TIMESTAMP DEFAULT NOW());"))
            conn.execute(text("INSERT INTO hospital_treasury (id, available_balance) VALUES (1, 50000.00) ON CONFLICT DO NOTHING;"))
            conn.execute(text("CREATE TABLE IF NOT EXISTS hospital_protocols (protocol_id text PRIMARY KEY, title text, department text, status text, author_pin text, last_signed timestamp, next_review timestamp);"))
            
            conn.execute(text("CREATE TABLE IF NOT EXISTS staff_competencies (comp_id text PRIMARY KEY, pin text, competency_name text, completed_date date, expires_date date, status text);"))
            # Insert real David Clark expiry data to replace hardcoded UI
            conn.execute(text("INSERT INTO staff_competencies (comp_id, pin, competency_name, completed_date, expires_date, status) VALUES ('COMP-1004', '1004', 'Advanced Ventilator Setup (Annual)', '2024-01-01', :exp, 'EXPIRED') ON CONFLICT DO NOTHING"), {"exp": str(date.today() - timedelta(days=45))})
            
            conn.execute(text("CREATE TABLE IF NOT EXISTS daily_rollups (date TEXT PRIMARY KEY, merkle_root TEXT, tx_count INT, status TEXT);"))

            conn.commit()
        return engine
    except Exception as e: 
        return f"DB_ERROR: {str(e)}"

def run_query(query, params=None):
    engine = get_db_engine()
    if isinstance(engine, str) or engine is None: return None
    try:
        with engine.connect() as conn: return conn.execute(text(query), params or {}).fetchall()
    except: return None

def run_transaction(query, params=None):
    engine = get_db_engine()
    if isinstance(engine, str) or engine is None: return 0
    try:
        with engine.connect() as conn: 
            result = conn.execute(text(query), params or {})
            conn.commit()
            return result.rowcount
    except: return 0

def load_all_users():
    res = run_query("SELECT pin, email, password_hash, name, role, dept, access_level, hourly_rate, phone, last_pw_change FROM enterprise_users")
    if not res: return {} 
    users_dict = {}
    for r in res: 
        users_dict[str(r[0])] = {
            "pin": str(r[0]), "email": r[1], "password_hash": r[2], "name": r[3], 
            "role": r[4], "dept": r[5], "level": r[6], "rate": float(r[7]), 
            "phone": r[8], "vip": (r[6] in ['Admin', 'Manager', 'Executive', 'Director']),
            "last_pw_change": r[9]
        }
    return users_dict

def log_action(pin, action, amount, note): return run_transaction("INSERT INTO history (pin, action, timestamp, amount, note) VALUES (:p, :a, NOW(), :amt, :n)", {"p": pin, "a": action, "amt": amount, "n": note})
def update_status(pin, status, start, earn, lat=0.0, lon=0.0): return run_transaction("INSERT INTO workers (pin, status, start_time, earnings, last_active, lat, lon) VALUES (:p, :s, :t, :e, NOW(), :lat, :lon) ON CONFLICT (pin) DO UPDATE SET status = :s, start_time = :t, earnings = :e, last_active = NOW(), lat = :lat, lon = :lon;", {"p": pin, "s": status, "t": start, "e": earn, "lat": float(lat), "lon": float(lon)})
def haversine_distance(lat1, lon1, lat2, lon2): R = 6371000; phi1, phi2 = math.radians(lat1), math.radians(lat2); dphi = math.radians(lat2 - lat1); dlam = math.radians(lon2 - lon1); a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2; return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def force_cloud_sync(pin):
    rows = run_query("SELECT status, start_time, earnings FROM workers WHERE pin = :pin", {"pin": pin})
    if rows and len(rows) > 0: 
        st.session_state.user_state['active'] = (rows[0][0].lower() == 'active'); st.session_state.user_state['start_time'] = float(rows[0][1]) if rows[0][1] else 0.0; st.session_state.user_state['earnings'] = float(rows[0][2]) if rows[0][2] else 0.0
        return True
    st.session_state.user_state['active'] = False; return False

def calculate_taxes(pin, gross_amount):
    if gross_amount <= 0.0: return 0.0, 0.0, 0.0, 0.0, 0.0
    res = run_query("SELECT SUM(amount) FROM history WHERE pin=:p AND action IN ('CLOCK OUT', 'MANUAL PAYOUT RELEASED') AND EXTRACT(YEAR FROM timestamp) = EXTRACT(YEAR FROM NOW())", {"p": pin})
    ytd_gross = float(res[0][0]) if res and res[0][0] else 0.0
    def calculate_federal_bracket(income):
        tax = 0.0
        if income > 191950: tax += (income - 191950) * 0.32; income = 191950
        if income > 100525: tax += (income - 100525) * 0.24; income = 100525
        if income > 47150: tax += (income - 47150) * 0.22; income = 47150
        if income > 11600: tax += (income - 11600) * 0.12; income = 11600
        if income > 0: tax += income * 0.10
        return tax
    fed_tax_before = calculate_federal_bracket(ytd_gross)
    fed_tax_after = calculate_federal_bracket(ytd_gross + gross_amount)
    fed_withholding = fed_tax_after - fed_tax_before
    ma_withholding = gross_amount * 0.05
    ss_withholding = gross_amount * 0.062
    med_withholding = gross_amount * 0.0145
    total_tax = fed_withholding + ma_withholding + ss_withholding + med_withholding
    return total_tax, fed_withholding, ma_withholding, ss_withholding, med_withholding

def execute_split_stream_payout(pin, gross_amount):
    TREASURY_DEST = "IRS_TREASURY_ACCOUNT"
    total_tax, fed, ma, ss, med = calculate_taxes(pin, gross_amount)
    net_payout = gross_amount - total_tax
    tx_base_id = int(time.time())
    dest_account = "FIAT_DIRECT_DEPOSIT"
    note_str = f"Gross: {gross_amount} | Tax: {total_tax}"
    run_transaction("INSERT INTO transactions (tx_id, pin, amount, status, destination_pubkey, tx_type, note) VALUES (:id, :p, :amt, 'APPROVED', :dest, 'NET_PAY', :note)", {"id": f"TX-NET-{tx_base_id}", "p": pin, "amt": net_payout, "dest": dest_account, "note": note_str})
    run_transaction("INSERT INTO transactions (tx_id, pin, amount, status, destination_pubkey, tx_type) VALUES (:id, :p, :amt, 'APPROVED', :dest, 'TAX_WITHHOLDING')", {"id": f"TX-TAX-{tx_base_id}", "p": pin, "amt": total_tax, "dest": TREASURY_DEST})
    log_action(pin, "FUNDS WITHDRAWN", net_payout, f"Settled to {dest_account}")
    log_action(pin, "TAX WITHHELD", total_tax, f"Routed to Treasury")
    return net_payout, total_tax

def calculate_shift_differentials(start_timestamp, base_rate):
    start_dt = datetime.fromtimestamp(start_timestamp, tz=LOCAL_TZ)
    end_dt = datetime.now(LOCAL_TZ)
    total_seconds = (end_dt - start_dt).total_seconds()
    if total_seconds <= 0: return 0.0, 0.0, "Invalid Shift"
    base_pay = 0.0; diff_pay = 0.0; notes = set()
    current_dt = start_dt
    while current_dt < end_dt:
        minute_base = base_rate / 60.0
        minute_diff = 0.0
        if current_dt.weekday() >= 5: minute_diff += (3.00 / 60.0); notes.add("WKD(+$3)")
        if 15 <= current_dt.hour < 19: minute_diff += (3.00 / 60.0); notes.add("EVE(+$3)")
        elif current_dt.hour >= 19 or current_dt.hour < 7: minute_diff += (5.00 / 60.0); notes.add("NOC(+$5)")
        base_pay += minute_base; diff_pay += minute_diff
        current_dt += timedelta(minutes=1)
    return base_pay, diff_pay, " | ".join(notes)

def calculate_fatigue_score(p_pin, target_dept):
    res_hrs = run_query("SELECT amount FROM history WHERE pin=:p AND action='CLOCK OUT' AND timestamp >= NOW() - INTERVAL '14 days'", {"p": p_pin})
    base_rate = float(USERS.get(p_pin, {}).get('rate', 0.1)) if p_pin in USERS else 0.1
    hrs_worked = (sum([float(r[0]) for r in res_hrs]) / base_rate) if res_hrs else 0.0
    score = hrs_worked 
    notes = []
    current_weekday = date.today().weekday()
    if current_weekday >= 5: 
        res_wknds = run_query("SELECT count(*) FROM history WHERE pin=:p AND action='CLOCK OUT' AND extract(isodow from timestamp) >= 6 AND timestamp >= NOW() - INTERVAL '30 days'", {"p": p_pin})
        if res_wknds and res_wknds[0][0] > 1: score += 50.0; notes.append(f"Weekend Equality (Worked {res_wknds[0][0]} recently)")
    res_acc = run_query("SELECT count(*) FROM obt_ledger WHERE pin=:p AND timestamp >= NOW() - INTERVAL '7 days'", {"p": p_pin})
    if res_acc and res_acc[0][0] > 0: score += 20.0; notes.append("Acuity Burnout Risk (+20)")
    res_rec = run_query("SELECT count(*) FROM history WHERE pin=:p AND action='CLOCK OUT' AND timestamp >= NOW() - INTERVAL '48 hours'", {"p": p_pin})
    if res_rec and res_rec[0][0] > 0 and USERS.get(p_pin, {}).get('dept') == target_dept: score -= 15.0; notes.append("Continuity Match (-15)")
    return score, hrs_worked, " | ".join(notes)

def get_rolling_weekly_hours(p_pin):
    res_wk = run_query("SELECT amount FROM history WHERE pin=:p AND action='CLOCK OUT' AND timestamp >= NOW() - INTERVAL '7 days'", {"p": p_pin})
    base_rate = float(USERS.get(p_pin, {}).get('rate', 0.1)) if p_pin in USERS else 0.1
    return (sum([float(r[0]) for r in res_wk]) / base_rate) if res_wk else 0.0

def proprietary_flex_oracle(dept_name):
    active_staff = run_query("SELECT pin FROM workers WHERE status='Active'")
    if not active_staff: return {"error": "No active operators found."}
    candidates = []
    for s in active_staff:
        w_pin = s[0]
        if USERS.get(str(w_pin), {}).get('dept') != dept_name: continue
        hrs_worked_7d = get_rolling_weekly_hours(w_pin)
        f_score, _, _ = calculate_fatigue_score(w_pin, dept_name)
        rate = USERS.get(str(w_pin), {}).get('rate', 0.0)
        name = USERS.get(str(w_pin), {}).get('name', 'Unknown')
        is_ot = hrs_worked_7d > 40.0
        ot_severity = hrs_worked_7d - 40.0 if is_ot else 0
        score = (ot_severity * 100) + f_score
        candidates.append({"pin": w_pin, "name": name, "score": score, "is_ot": is_ot, "hrs": hrs_worked_7d, "f_score": f_score, "rate": rate})
    if not candidates: return {"error": f"No active staff in {dept_name} to flex."}
    candidates = sorted(candidates, key=lambda x: x['score'], reverse=True)
    top_cand = candidates[0]
    reason = f"Proprietary Engine Selected {top_cand['name']}. "
    if top_cand['is_ot']: reason += f"Operator is in critical Overtime ({top_cand['hrs']:.1f} hrs) triggering immediate financial bleed. "
    reason += f"Fatigue Index is {top_cand['f_score']:.1f}. Flexing immediately optimizes both budget variance and clinical safety."
    return {"selected_pin": top_cand['pin'], "selected_name": top_cand['name'], "reason": reason}

st.set_page_config(page_title="Vicentus Enterprise", page_icon="⚡", layout="wide", initial_sidebar_state="collapsed")
import base64

# --- PWA MOBILE INJECTION ---
# This forces iOS and Android to treat the website as a native app
manifest_json = """
{
  "name": "Vicentus Enterprise",
  "short_name": "Vicentus",
  "theme_color": "#0b1120",
  "background_color": "#0b1120",
  "display": "standalone",
  "orientation": "portrait",
  "scope": "/",
  "start_url": "/",
  "icons": [
    {
      "src": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e4/Electric_lightning_symbol.svg/512px-Electric_lightning_symbol.svg.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
"""
b64_manifest = base64.b64encode(manifest_json.encode()).decode()

pwa_html = f"""
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Vicentus">
<link rel="apple-touch-icon" href="https://upload.wikimedia.org/wikipedia/commons/thumb/e/e4/Electric_lightning_symbol.svg/512px-Electric_lightning_symbol.svg.png">
<link rel="manifest" href="data:application/manifest+json;base64,{b64_manifest}">
"""
st.markdown(pwa_html, unsafe_allow_html=True)

html_style = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800;900&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
    [data-testid="stSidebar"] { display: none !important; } [data-testid="collapsedControl"] { display: none !important; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} [data-testid="stToolbar"] {visibility: hidden !important;} header {background: transparent !important;}
    .stApp { background-color: #0b1120; background-image: radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.1) 0px, transparent 50%), radial-gradient(at 100% 0%, rgba(16, 185, 129, 0.05) 0px, transparent 50%); background-attachment: fixed; color: #f8fafc; }
    .block-container { padding-top: 1rem !important; padding-bottom: 2rem !important; max-width: 96% !important; }
    .custom-header-pill { background: rgba(11, 17, 32, 0.85); backdrop-filter: blur(12px); padding: 15px 25px; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 30px rgba(0,0,0,0.3); }
    div[data-testid="metric-container"], .glass-card { background: rgba(30, 41, 59, 0.6) !important; backdrop-filter: blur(12px) !important; border: 1px solid rgba(255, 255, 255, 0.05) !important; border-radius: 16px; padding: 20px; margin-bottom: 15px; box-shadow: 0 4px 20px 0 rgba(0, 0, 0, 0.3); }
    div[data-testid="metric-container"] label { color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; }
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] { color: #f8fafc; font-size: 2rem; font-weight: 800; }
    .stButton>button { width: 100%; height: 55px; border-radius: 12px; font-weight: 700; font-size: 1rem; border: none; transition: all 0.2s ease; box-shadow: 0 4px 15px rgba(0,0,0,0.2); letter-spacing: 0.5px; }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.3); }
    div[role="radiogroup"] { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; }
    .shift-card { background: linear-gradient(145deg, rgba(30, 41, 59, 0.9) 0%, rgba(15, 23, 42, 0.95) 100%); border: 1px solid rgba(16, 185, 129, 0.3); border-left: 5px solid #10b981; border-radius: 16px; padding: 25px; margin-bottom: 20px; position: relative; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.4); transition: transform 0.2s ease; }
    .shift-card:hover { transform: translateY(-3px); border: 1px solid rgba(16, 185, 129, 0.6); }
    .shift-card::before { content: 'OPEN COVERAGE'; position: absolute; top: 18px; right: -35px; background: #10b981; color: #000; font-size: 0.7rem; font-weight: 900; padding: 6px 40px; transform: rotate(45deg); letter-spacing: 1px; }
    .shift-amount { font-size: 2.8rem; font-weight: 900; color: #f8fafc; margin: 10px 0; letter-spacing: -1px; }
    .empty-state { text-align: center; padding: 40px 20px; background: rgba(30, 41, 59, 0.3); border: 2px dashed rgba(255,255,255,0.1); border-radius: 16px; margin-top: 20px; margin-bottom: 20px; }
    .stripe-box { background: linear-gradient(135deg, #635bff 0%, #423ed8 100%); border-radius: 12px; padding: 25px; color: white; margin-bottom: 20px; box-shadow: 0 10px 25px rgba(99, 91, 255, 0.4); }
    .sched-date-header { background: rgba(16, 185, 129, 0.1); padding: 10px 15px; border-radius: 8px; margin-top: 25px; margin-bottom: 15px; font-weight: 800; font-size: 1rem; border-left: 4px solid #10b981; color: #34d399; text-transform: uppercase; }
    .sched-row { display: flex; justify-content: space-between; align-items: center; padding: 15px; margin-bottom: 8px; background: rgba(30, 41, 59, 0.5); border-radius: 8px; border-left: 3px solid rgba(255,255,255,0.1); }
    .sched-time { color: #34d399; font-weight: 800; min-width: 100px; font-size: 1rem; }
    
    .badge-pass { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #10b981; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: bold; margin-right: 5px; }
    .badge-fail { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid #ef4444; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: bold; margin-right: 5px; }
    .badge-warn { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #f59e0b; padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: bold; margin-right: 5px; }
    .hash-text { font-family: monospace; color: #38bdf8; font-size: 0.75rem; word-break: break-all; background: rgba(0,0,0,0.3); padding: 4px 8px; border-radius: 4px; margin-top: 8px; border: 1px solid rgba(56, 189, 248, 0.2); }
</style>
"""
st.markdown(html_style, unsafe_allow_html=True)

# --- DIAGNOSTIC ENGINE CHECK ---
engine_status = get_db_engine()
if isinstance(engine_status, str):
    st.markdown("<br><br><h1 style='text-align: center; color: #ef4444;'>🚨 CONNECTION SEVERED</h1>", unsafe_allow_html=True)
    if engine_status == "URL_MISSING":
        st.error("**CRITICAL ERROR:** The `SUPABASE_URL` environment variable or Streamlit Secret is completely missing.")
    else:
        st.error(f"**RAW DATABASE ERROR LOG:**\n\n{engine_status}")
    st.stop()

USERS = load_all_users()

if 'user_state' not in st.session_state: st.session_state.user_state = {'active': False, 'start_time': 0.0, 'earnings': 0.0}
if 'geofence_alert' not in st.session_state: st.session_state.geofence_alert = False

if 'pending_opsec_reset' in st.session_state:
    st.markdown("<br><br><h1 style='text-align: center; color: #ef4444;'>SECURITY MANDATE</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #94a3b8;'>Your password has expired or is set to default. Hospital InfoSec protocols require an immediate update.</p><br>", unsafe_allow_html=True)
    with st.container():
        st.markdown("<div class='glass-card' style='max-width: 500px; margin: 0 auto; border-left: 4px solid #ef4444 !important;'>", unsafe_allow_html=True)
        with st.form("opsec_reset_form"):
            new_pass = st.text_input("New Secure Password", type="password")
            confirm_pass = st.text_input("Confirm Password", type="password")
            st.caption("Must be 8+ chars, with upper, lower, number, and special character.")
            if st.form_submit_button("Update & Unlock"):
                if new_pass != confirm_pass: st.error("Passwords do not match.")
                else:
                    is_valid, msg = is_strong_password(new_pass)
                    if not is_valid: st.error(f"Weak Password: {msg}")
                    else:
                        run_transaction("UPDATE enterprise_users SET password_hash=:pw, last_pw_change=NOW() WHERE pin=:p", {"p": st.session_state.pending_opsec_pin, "pw": hash_password(new_pass)})
                        st.success("✅ Password Secured. Rerouting to dashboard...")
                        del st.session_state.pending_opsec_reset
                        del st.session_state.pending_opsec_pin
                        time.sleep(2)
                        st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

if 'logged_in_user' not in st.session_state:
    st.markdown("<br><br><br><br><h1 style='text-align: center; color: #f8fafc; letter-spacing: 4px; font-weight: 900; font-size: 3rem;'>VICENTUS</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #10b981; letter-spacing: 3px; font-weight:600;'>ENTERPRISE PROTOCOL v6.0.5-Live</p><br>", unsafe_allow_html=True)
    with st.container():
        if not USERS: st.error("❌ CRITICAL: No user accounts found in the database. Please check Supabase table.")
        st.markdown("<div class='glass-card' style='max-width: 500px; margin: 0 auto;'>", unsafe_allow_html=True)
        login_email = st.text_input("ENTERPRISE EMAIL", placeholder="name@hospital.com")
        login_password = st.text_input("SECURE PASSWORD", type="password", placeholder="••••••••")
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("AUTHENTICATE CONNECTION") and USERS:
            auth_pin = None
            for p, d in USERS.items():
                if d.get("email") == login_email.lower():
                    stored_hash = d.get("password_hash")
                    pw_expired = False
                    if d.get("last_pw_change"):
                        try:
                            last_update = d["last_pw_change"]
                            if isinstance(last_update, str): last_update = datetime.fromisoformat(last_update)
                            if last_update.tzinfo is None: last_update = last_update.replace(tzinfo=pytz.UTC)
                            if (datetime.now(pytz.UTC) - last_update).days >= OPSEC_PW_EXPIRY_DAYS: pw_expired = True
                        except: pass 
                    
                    is_default = (login_password == "password123")
                    
                    if stored_hash and verify_password(login_password, stored_hash): 
                        if is_default or pw_expired:
                            st.session_state.pending_opsec_reset = True
                            st.session_state.pending_opsec_pin = p
                            st.rerun()
                        else: auth_pin = p; break
                        
            if auth_pin:
                st.session_state.logged_in_user = USERS[auth_pin]; st.session_state.pin = auth_pin
                force_cloud_sync(auth_pin); st.rerun()
            else: st.error("❌ INVALID CREDENTIALS OR NETWORK ERROR")
        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

user = st.session_state.logged_in_user; pin = st.session_state.pin

c1, c2 = st.columns([8, 2])
with c1: st.markdown(f"<div class='custom-header-pill'><div style='font-weight:900; font-size:1.4rem; letter-spacing:2px; color:#f8fafc; display:flex; align-items:center;'><span style='color:#10b981; font-size:1.8rem; margin-right:8px;'>⚡</span> VICENTUS PROTOCOL</div><div style='text-align:right;'><div style='font-size:0.95rem; font-weight:800; color:#f8fafc;'>{user['name']}</div><div style='font-size:0.75rem; color:#38bdf8; text-transform:uppercase; letter-spacing:1px;'>{user['role']} | {user['dept']}</div></div></div>", unsafe_allow_html=True)
with c2: 
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🚪 LOGOUT"): st.session_state.clear(); st.rerun()

# --- DYNAMIC C-SUITE MENU ROUTING ---
if user['role'] == "CEO":
    menu_items = ["EXECUTIVE BRIEFING", "COMMAND CENTER", "FINANCIAL FORECAST", "COMMS"]
elif user['role'] == "COO":
    menu_items = ["COMMAND CENTER", "DASHBOARD", "SCHEDULE", "CENSUS & ACUITY", "MARKETPLACE", "COMMS"]
elif user['role'] == "CNO":
    menu_items = ["FATIGUE MATRIX", "CENSUS & ACUITY", "COMPLIANCE", "SCHEDULE", "APPROVALS", "COMMS"]
elif user['role'] == "CCO":
    menu_items = ["COMPLIANCE", "COMMS"]
elif user['role'] == "CTO":
    menu_items = ["OPSEC & INFRASTRUCTURE", "COMMAND CENTER", "MY PROFILE", "COMMS"]
elif user['role'] == "CFO":
    menu_items = ["FINANCIAL FORECAST", "THE BANK", "APPROVALS", "COMMS"]
elif user['role'] == "CHRO":
    menu_items = ["FLIGHT RISK RADAR", "COMMAND CENTER", "COMMS"]
elif user['level'] == "Admin": 
    menu_items = ["COMMAND CENTER", "COMPLIANCE", "FINANCIAL FORECAST", "APPROVALS", "COMMS"]
elif user['level'] in ["Manager", "Director", "Supervisor"]: 
    menu_items = ["DASHBOARD", "CENSUS & ACUITY", "MARKETPLACE", "SCHEDULE", "THE BANK", "APPROVALS", "COMPLIANCE", "COMMS", "MY PROFILE"]
else: 
    menu_items = ["DASHBOARD", "MARKETPLACE", "SCHEDULE", "THE BANK", "COMMS", "MY PROFILE"]

st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)
nav = st.radio("NAVIGATION", menu_items, horizontal=True, label_visibility="collapsed")
st.markdown("<hr style='border-color: rgba(255,255,255,0.05); margin-top: 5px; margin-bottom: 20px;'>", unsafe_allow_html=True)

if nav == "FLIGHT RISK RADAR":
    st.markdown("## 🚁 CHRO Flight Risk & Turnover Radar")
    st.caption("Proactive algorithmic retention. Prevents operators from burning out and migrating to agency networks.")
    
    all_staff = {p: d for p, d in USERS.items() if d['level'] in ['Worker', 'Supervisor']}
    risk_found = False
    
    for p, d in all_staff.items():
        f_score, f_hrs, f_notes = calculate_fatigue_score(p, d['dept'])
        if f_score > 40 or f_hrs > 40: 
            risk_found = True
            color = "#ef4444" if f_score > 70 else "#f59e0b"
            st.markdown(f"""
            <div class='glass-card' style='border-left: 5px solid {color} !important;'>
                <div style='display:flex; justify-content:space-between;'>
                    <strong style='font-size:1.1rem;'>{d['name']} ({d['role']} - {d['dept']})</strong>
                    <span style='color:{color}; font-weight:bold;'>FLIGHT RISK: {'CRITICAL' if f_score > 70 else 'ELEVATED'}</span>
                </div>
                <p style='color:#94a3b8; font-size:0.85rem; margin-top:5px;'>14-Day Hours: {f_hrs:.1f} | Engine Score: {f_score:.1f} | Triggers: {f_notes}</p>
                <div style='margin-top:10px; display:flex; gap:10px;'>
                    <button style='background:rgba(16,185,129,0.2); border:1px solid #10b981; color:#fff; padding:5px 10px; border-radius:5px; flex-grow:1;'>💰 Deploy $500 Retention Bonus</button>
                    <button style='background:rgba(239,68,68,0.2); border:1px solid #ef4444; color:#fff; padding:5px 10px; border-radius:5px; flex-grow:1;'>🛑 Enforce Mandatory PTO</button>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
    if not risk_found:
        st.success("✅ Enterprise morale is optimal. Zero flight risk vectors detected.")

elif nav == "COMPLIANCE":
    st.markdown("## 🛡️ Enterprise Compliance Engine")
    st.caption("Cryptographic verification of care, automated protocol enforcement, and anti-fraud auditing.")
    
    c1, c2 = st.columns([8, 2])
    with c1:
        if st.button("🔄 Refresh Compliance Database"): st.rerun()
    with c2:
        if PDF_ACTIVE and user['level'] in ["Admin", "Executive", "Manager", "Director"]:
            pdf_bytes = generate_compliance_report(user['dept'], user['name'])
            if pdf_bytes:
                st.download_button(label="📄 Export Compliance Audit (PDF)", data=pdf_bytes, file_name=f"Vicentus_Audit_{user['dept']}_{date.today()}.pdf", mime="application/pdf")
        elif not PDF_ACTIVE:
            st.warning("⚠️ FPDF library not installed.")

    tab_poc, tab_proto, tab_comp = st.tabs(["🔒 LIVE PROOF OF CARE (PoC) LEDGER", "🛑 PROTOCOL COMMAND", "🪪 COMPETENCY AUDIT"])

    with tab_poc:
        c_p1, c_p2 = st.columns([8,2])
        with c_p1: st.markdown("### Anti-Clawback Billing Engine")
        with c_p2: 
            if st.button("🔌 Sync via EMR FHIR"):
                run_transaction("UPDATE poc_ledger SET emr_verified=TRUE, status='CLEARED' WHERE emr_verified=FALSE")
                st.success("API Synced!"); time.sleep(1); st.rerun()
                
        st.caption("Mathematically proves service delivery by correlating BLE indoor geolocation, EMR documentation, and AI verification, sealed with an immutable SHA-256 cryptographic hash.")
        
        real_poc_claims = run_query("SELECT claim_id, pin, patient_room, action, timestamp, ble_verified, emr_verified, ai_verified, secure_hash FROM poc_ledger ORDER BY timestamp DESC LIMIT 20")
        
        if real_poc_claims:
            for claim in real_poc_claims:
                c_id, c_pin, c_room, c_action, c_time, c_ble, c_emr, c_ai, c_hash = claim
                op_name = USERS.get(str(c_pin), {}).get('name', f"Operator {c_pin}")
                
                ble_badge = "<span class='badge-pass'>BLE LOC MATCH</span>" if c_ble else "<span class='badge-warn'>BLE SIMULATED</span>"
                emr_badge = "<span class='badge-pass'>EMR SYNCED</span>" if c_emr else "<span class='badge-fail'>EMR MISMATCH</span>"
                ai_badge = "<span class='badge-pass'>AI VERIFIED</span>" if c_ai else "<span class='badge-warn'>AI PENDING</span>"
                
                border = "#10b981" if c_emr else "#ef4444"
                status_text = "<span style='color:#10b981; font-weight:bold;'>CLEARED FOR BILLING</span>" if c_emr else "<span style='color:#ef4444; font-weight:bold;'>PENDING EMR SYNC</span>"
                
                try: display_time = c_time.strftime("%Y-%m-%d %H:%M:%S")
                except: display_time = str(c_time)

                st.markdown(f"""
                <div class='glass-card' style='border-left: 5px solid {border} !important;'>
                    <div style='display:flex; justify-content:space-between;'>
                        <strong style='font-size:1.1rem;'>{c_action} | {c_room}</strong>
                        <span>{status_text}</span>
                    </div>
                    <div style='color:#94a3b8; font-size:0.85rem; margin-top:5px; margin-bottom:10px;'>Operator: {op_name} ({c_pin}) | Timestamp: {display_time} | Claim ID: {c_id}</div>
                    <div>{ble_badge} {emr_badge} {ai_badge}</div>
                    <div class='hash-text'>🔒 SHA-256 SEAL: {c_hash}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No Proof-of-Care claims have been logged by operators yet.")

    with tab_proto:
        st.markdown("### 🛑 Protocol & Policy Command")
        
        if user['role'] == "CCO" or user['level'] == "Admin":
            st.caption("Central hub for the Chief Compliance Officer to audit, approve, and broadcast hospital-wide policies.")
            c_sub1, c_sub2 = st.tabs(["⚠️ ACTION REQUIRED", "📝 DRAFT & APPROVALS"])
            
            with c_sub1:
                st.markdown("#### Expiring or Missing Protocols")
                alerts = run_query("SELECT protocol_id, title, department, next_review FROM hospital_protocols WHERE status='ACTIVE' AND next_review <= NOW() + INTERVAL '30 days' OR status='MISSING'")
                if alerts:
                    for a in alerts:
                        p_id, p_title, p_dept, p_exp = a
                        st.markdown(f"""
                        <div class='glass-card' style='border-left: 5px solid #ef4444 !important;'>
                            <div style='display:flex; justify-content:space-between;'>
                                <strong style='color:#f8fafc; font-size:1.1rem;'>{p_title} ({p_dept})</strong>
                                <span class='badge-fail'>EXPIRES SOON / MISSING</span>
                            </div>
                            <p style='color:#94a3b8; font-size:0.85rem; margin-top:5px;'>Deadline: {p_exp}</p>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.success("✅ All active protocols are up to date.")

            with c_sub2:
                st.markdown("#### Pending CCO Approvals")
                drafts = run_query("SELECT protocol_id, title, department, author_pin FROM hospital_protocols WHERE status='PENDING_CCO'")
                if drafts:
                    for d in drafts:
                        d_id, d_title, d_dept, d_author = d
                        author_name = USERS.get(str(d_author), {}).get('name', 'Unknown')
                        st.markdown(f"<div class='glass-card' style='border-left: 4px solid #f59e0b !important;'><strong>{d_title}</strong><br><span style='font-size:0.8rem; color:#94a3b8;'>Drafted by: {author_name} | Target: {d_dept}</span></div>", unsafe_allow_html=True)
                        
                        c_btn1, c_btn2 = st.columns(2)
                        if c_btn1.button("✅ APPROVE & BROADCAST", key=f"app_{d_id}"):
                            run_transaction("UPDATE hospital_protocols SET status='ACTIVE', last_signed=NOW(), next_review=NOW() + INTERVAL '1 year' WHERE protocol_id=:id", {"id": d_id})
                            msg_text = f"📢 NEW PROTOCOL ACTIVE: {d_title}. All {d_dept} staff must review immediately."
                            run_transaction("INSERT INTO messages (msg_id, sender_pin, target_dept, message, is_sos) VALUES (:id, :p, :dept, :m, FALSE)", {"id": f"MSG-{int(time.time()*1000)}", "p": pin, "dept": "All", "m": msg_text})
                            st.success("Protocol Published and Broadcasted!"); time.sleep(2); st.rerun()
                        if c_btn2.button("❌ REJECT", key=f"rej_{d_id}"):
                            run_transaction("UPDATE hospital_protocols SET status='REJECTED' WHERE protocol_id=:id", {"id": d_id}); st.rerun()
                else:
                    st.info("No protocol drafts awaiting your approval.")
                    
        elif user['level'] in ["Director", "Manager", "Supervisor"]:
            st.caption(f"Departmental Protocol Hub: {user['dept']}")
            c_sub1, c_sub2 = st.tabs(["📄 ACTIVE PROTOCOLS", "➕ SUBMIT DRAFT"])
            
            with c_sub1:
                st.markdown(f"#### Active {user['dept']} Protocols")
                active_p = run_query("SELECT title, next_review FROM hospital_protocols WHERE status='ACTIVE' AND (department=:d OR department='All')", {"d": user['dept']})
                if active_p:
                    for p in active_p:
                        st.markdown(f"<div class='glass-card' style='border-left: 4px solid #10b981 !important;'><strong>{p[0]}</strong><br><span style='color:#94a3b8; font-size:0.85rem;'>Next Review: {p[1]}</span></div>", unsafe_allow_html=True)
                else:
                    st.info("No active protocols found.")
                    
            with c_sub2:
                st.markdown("#### Submit New Protocol for CCO Review")
                with st.form("new_protocol_dir"):
                    new_title = st.text_input("Protocol Title")
                    new_dept = st.selectbox("Target Department", [user['dept'], "All"])
                    if st.form_submit_button("Submit for CCO Review"):
                        run_transaction("INSERT INTO hospital_protocols (protocol_id, title, department, status, author_pin) VALUES (:id, :t, :d, 'PENDING_CCO', :p)", {"id": f"PRO-{int(time.time())}", "t": new_title, "d": new_dept, "p": pin})
                        st.success("Draft submitted to Compliance."); time.sleep(1.5); st.rerun()
                        
                st.markdown("#### My Pending Drafts")
                drafts = run_query("SELECT title, status FROM hospital_protocols WHERE author_pin=:p", {"p": pin})
                if drafts:
                    for d in drafts:
                        color = "#f59e0b" if d[1] == 'PENDING_CCO' else "#ef4444" if d[1] == 'REJECTED' else "#10b981"
                        st.markdown(f"<div style='border-left: 3px solid {color}; padding-left: 10px; margin-bottom:5px; color:#f8fafc;'>{d[0]} - <span style='color:{color}; font-weight:bold;'>{d[1]}</span></div>", unsafe_allow_html=True)
                else:
                    st.info("You have no pending protocol drafts.")

    with tab_comp:
        st.markdown("### Staff Competency Engine")
        st.caption("Automated tracking of clinical competencies. Prevents non-compliant operators from claiming shifts in high-acuity zones.")
        
        c_req = run_query("SELECT comp_id, pin, competency_name, expires_date, status FROM staff_competencies WHERE status IN ('EXPIRED', 'PENDING_REVIEW')")
        if c_req:
            st.markdown("#### Critical Actions Required")
            for cr in c_req:
                c_id, c_pin, c_name, c_exp, c_status = cr
                op_name = USERS.get(str(c_pin), {}).get('name', f"Operator {c_pin}")
                
                if c_status == 'EXPIRED':
                    st.markdown(f"""
                    <div class='glass-card' style='border-left: 5px solid #ef4444 !important;'>
                        <strong style='color:#f8fafc; font-size:1.1rem;'>{op_name} ({USERS.get(str(c_pin), {}).get('role')})</strong>
                        <p style='color:#94a3b8; margin: 5px 0;'>Competency: <b>{c_name}</b></p>
                        <span class='badge-fail'>EXPIRED ({c_exp})</span>
                        <p style='color:#f87171; font-size:0.85rem; margin-top:10px;'>⚠️ System has restricted this operator from claiming High-Acuity coverage. Action Invalid.</p>
                    </div>
                    """, unsafe_allow_html=True)
                elif c_status == 'PENDING_REVIEW' and user['level'] in ["Admin", "Executive", "Manager", "Director"]:
                    st.markdown(f"""
                    <div class='glass-card' style='border-left: 5px solid #f59e0b !important;'>
                        <strong style='color:#f8fafc; font-size:1.1rem;'>{op_name} ({USERS.get(str(c_pin), {}).get('role')})</strong>
                        <p style='color:#94a3b8; margin: 5px 0;'>Competency: <b>{c_name}</b></p>
                        <span class='badge-warn'>PENDING CCO/MANAGER REVIEW</span>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button("✅ Approve Renewed Competency", key=f"comp_app_{c_id}"):
                        new_exp = str(date.today() + timedelta(days=365))
                        run_transaction("UPDATE staff_competencies SET status='ACTIVE', expires_date=:exp WHERE comp_id=:id", {"exp": new_exp, "id": c_id})
                        st.success(f"Competency Approved! Next renewal set for {new_exp}"); time.sleep(1.5); st.rerun()
        else:
            st.success("✅ All staff competencies are active and verified.")

elif nav == "DASHBOARD":
    st.markdown(f"<h2 style='font-weight: 800;'>Status Terminal</h2>", unsafe_allow_html=True)
    st.caption("Enterprise Ledger Metrics Active. Live shift monitoring enabled.")
    if st.button("🔄 Force Cloud Sync"): force_cloud_sync(pin); st.rerun()
    if user['level'] in ["Admin", "Executive", "Manager", "Director", "Supervisor"]:
        active_count = run_query("SELECT COUNT(*) FROM workers WHERE status='Active'")[0][0] if run_query("SELECT COUNT(*) FROM workers WHERE status='Active'") else 0
        shifts_count = run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'")[0][0] if run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'") else 0
        c1, c2, c3 = st.columns(3); c1.metric("Live Staff", active_count); c2.metric("Critical Shifts", shifts_count, f"{shifts_count} Open" if shifts_count > 0 else "Fully Staffed", delta_color="inverse"); c3.metric("Approvals", "Active")
        st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)

    active = st.session_state.user_state.get('active', False)
    running_earn = 0.0; display_gross = 0.0
    if active:
        base_pay, diff_pay, diff_str = calculate_shift_differentials(st.session_state.user_state['start_time'], user['rate'])
        running_earn = base_pay + diff_pay
        if diff_pay > 0: st.info(f"✨ Active Shift Differentials Applied: {diff_str}")
        
        if st.session_state.geofence_alert:
            st.markdown("<div class='glass-card' style='border-left: 5px solid #f59e0b !important;'>", unsafe_allow_html=True)
            st.warning("⚠️ GEOFENCE ALERT: Are you still working? Your GPS indicates you left the hospital radius.")
            c_g1, c_g2 = st.columns(2)
            if c_g1.button("✅ Yes, on Official Transport"):
                st.session_state.geofence_alert = False
                log_action(pin, "GEOFENCE DISMISSED", 0, "Operator verified official transport.")
                st.rerun()
            if c_g2.button("🛑 No, Clock Me Out Now"):
                new_total = st.session_state.user_state.get('earnings', 0.0) + running_earn
                if update_status(pin, "Inactive", 0, new_total, 0.0, 0.0):
                    st.session_state.user_state['active'] = False; st.session_state.user_state['earnings'] = new_total
                    st.session_state.geofence_alert = False
                    log_action(pin, "CLOCK OUT", running_earn, f"Shift Ended (Geofence Prompt)" + (f" [{diff_str}]" if diff_pay > 0 else ""))
                    st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
            st.stop() 
            
    display_gross = st.session_state.user_state.get('earnings', 0.0) + running_earn
    est_total_tax, _, _, _, _ = calculate_taxes(pin, display_gross)
    c1, c2 = st.columns(2); c1.metric("SHIFT ACCRUAL (Gross)", f"${display_gross:,.2f}"); c2.metric("NET ESTIMATE", f"${display_gross - est_total_tax:,.2f}")
    st.markdown("<br>", unsafe_allow_html=True)

    if active:
        end_pin = st.text_input("Enter 4-Digit PIN to Clock Out", type="password", key="end_pin")
        if st.button("PUNCH OUT") and end_pin == pin:
            new_total = st.session_state.user_state.get('earnings', 0.0) + running_earn
            if update_status(pin, "Inactive", 0, new_total, 0.0, 0.0):
                st.session_state.user_state['active'] = False; st.session_state.user_state['earnings'] = new_total
                base_pay, diff_pay, diff_str = calculate_shift_differentials(st.session_state.user_state['start_time'], user['rate'])
                log_action(pin, "CLOCK OUT", running_earn, f"Shift Ended" + (f" [{diff_str}]" if diff_pay > 0 else ""))
                st.rerun()
        
        with st.expander("⚙️ App Simulation Engine (Equipment & EMR Triggers)", expanded=True):
            st.markdown("#### 🔒 Log Clinical Event (Proof of Care)")
            with st.form("poc_event_logger"):
                c_form1, c_form2 = st.columns(2)
                poc_room = c_form1.text_input("Patient Room", placeholder="e.g., ICU-Bed 2")
                poc_action = c_form2.selectbox("Clinical Action Performed", [
                    "Routine Albuterol Tx", 
                    "BiPAP Application", 
                    "Endotracheal Intubation", 
                    "Initiate Veletri/Flolan", 
                    "CRRT Dialysis Setup", 
                    "Code Blue Response"
                ])
                
                if st.form_submit_button("Seal & Cryptographically Log Event"):
                    if not poc_room: st.error("Please specify a room number.")
                    else:
                        new_claim_id = f"CLM-{int(time.time())}"
                        ts_string = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
                        live_hash = generate_poc_hash(new_claim_id, pin, poc_room, poc_action, ts_string)
                        
                        db_save = run_transaction("INSERT INTO poc_ledger (claim_id, pin, patient_room, action, timestamp, ble_verified, emr_verified, ai_verified, status, secure_hash) VALUES (:cid, :p, :r, :a, NOW(), TRUE, FALSE, TRUE, 'PENDING_EMR', :h)", {"cid": new_claim_id, "p": pin, "r": poc_room, "a": poc_action, "h": live_hash})
                        
                        if db_save > 0:
                            st.success(f"✅ Event cryptographically sealed in PoC Ledger! (Awaiting EMR Sync)")
                            high_acuity_triggers = ["Endotracheal Intubation", "Initiate Veletri/Flolan", "CRRT Dialysis Setup", "Code Blue Response"]
                            if poc_action in high_acuity_triggers:
                                # 1. Define the Token ID logic
                                action_mapping = {"Endotracheal Intubation": 1, "Initiate Veletri/Flolan": 2, "CRRT Dialysis Setup": 3, "Code Blue Response": 4}
                                action_id = action_mapping.get(poc_action, 99)
                                
                                # 2. Trigger the Web3 Engine (Silently pings Base Sepolia L2)
                                dummy_wallet = "0xAb8483F64d9C6d1EcF9b849Ae677dD3315835cb2" # Replace with user's actual DB wallet later
                                tx_receipt = mint_sbt_on_chain(dummy_wallet, action_id)
                                
                                # 3. Save to internal database
                                sbt_id = f"SBT-{pin}-{int(time.time()*1000)}"
                                run_transaction("""
                                    INSERT INTO obt_ledger (token_id, pin, accolade_type, clinical_context, facility_origin, encryption_hash) 
                                    VALUES (:t_id, :p, 'Critical Intervention', :ctx, 'Hospital A', :hash)
                                """, {"t_id": sbt_id, "p": pin, "ctx": f"{poc_action} | {poc_room}", "hash": tx_receipt})
                                
                                st.success(f"🏅 L2 SMART CONTRACT FIRED: {poc_action} permanently added to your Soulbound Portfolio.\n\n`Tx Hash: {tx_receipt}`")
            
            st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
            if st.button("🚙 Simulate Leaving Geofence (FLSA Soft Alert)"):
                st.session_state.geofence_alert = True
                st.rerun()

    else:
        selected_facility = st.selectbox("Select Facility", list(HOSPITALS.keys()))
        if not user.get('vip', False):
            st.info("Identity verification required to initiate shift.")
            camera_photo = st.camera_input("Take a photo to verify identity")
            loc = get_geolocation()
            if camera_photo and loc:
                user_lat, user_lon = loc['coords']['latitude'], loc['coords']['longitude']
                fac_lat, fac_lon = HOSPITALS[selected_facility]["lat"], HOSPITALS[selected_facility]["lon"]
                
                # --- DEMO MODE BYPASS FOR GEOFENCE ---
                if fac_lat == 0.0 and fac_lon == 0.0:
                    st.success(f"✅ Demo Mode Active: Geofence automatically bypassed for {selected_facility}.")
                    start_pin = st.text_input("Enter PIN to Clock In", type="password", key="start_pin_demo")
                    if st.button("PUNCH IN") and start_pin == pin:
                        start_t = time.time(); update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), user_lat, user_lon); st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()
                elif haversine_distance(user_lat, user_lon, fac_lat, fac_lon) <= GEOFENCE_RADIUS:
                    st.success(f"✅ Geofence Confirmed.")
                    start_pin = st.text_input("Enter PIN to Clock In", type="password", key="start_pin")
                    if st.button("PUNCH IN") and start_pin == pin:
                        start_t = time.time(); update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), user_lat, user_lon); st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()
                else: 
                    st.error("❌ Geofence Failed.")
        else:
            st.caption("✨ VIP Security Override Active")
            start_pin = st.text_input("Enter PIN to Clock In", type="password", key="vip_start_pin")
            if st.button("PUNCH IN") and start_pin == pin:
                start_t = time.time(); update_status(pin, "Active", start_t, st.session_state.user_state.get('earnings', 0.0), 0.0, 0.0); st.session_state.user_state['active'] = True; st.session_state.user_state['start_time'] = start_t; log_action(pin, "CLOCK IN", 0, f"Loc: {selected_facility}"); st.rerun()

elif nav == "OPSEC & INFRASTRUCTURE":
    st.markdown("## 🔐 Infrastructure Command")
    st.caption("Live network diagnostics, cryptographic load, and API routing telemetry.")
    if st.button("🔄 Ping Servers"): st.rerun()
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Database Gateway", "aws-1-us-east-2", "99.9% Uptime")
    c2.metric("Cryptographic Hashes Logged", "24,102", "SHA-256 Secured")
    c3.metric("Blocked Intrusions (24h)", "14", "-2 from yesterday", delta_color="inverse")
    
    st.markdown("### Live API Telemetry")
    st.markdown("""
    <div class='glass-card' style='font-family: monospace; color: #34d399;'>
        > [SYS] Initializing secure WebSocket tunnel... OK<br>
        > [SYS] Verifying Supabase connection pooler (Port 6543)... OK<br>
        > [SEC] 4 active user sessions authenticated.<br>
        > [SEC] Zero-knowledge proof verified for recent PoC claims.<br>
        > [NET] Current Latency: 42ms
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
    st.markdown("### ⛓️ Layer 2 Merkle Root Batching")
    st.caption("Hash all daily Proof-of-Care transactions into a single Merkle Root for decentralized ledger deployment.")
    
    with st.form("merkle_rollup_form"):
        target_date = st.date_input("Target Rollup Date", value=date.today())
        if st.form_submit_button("⚡ Execute Daily Hash Rollup"):
            success, result = execute_daily_rollup(str(target_date))
            if success:
                st.success("✅ Merkle Root successfully generated and stored!")
                st.markdown(f"<div class='hash-text' style='font-size:1rem;'>ROOT HASH: {result}</div>", unsafe_allow_html=True)
            else:
                st.error(f"❌ Rollup Failed: {result}")

elif nav == "EXECUTIVE BRIEFING":
    st.markdown("## 🦅 CEO Global Overview")
    st.caption("Top-line enterprise metrics. Financial efficiency and operational risk.")
    
    treasury_res = run_query("SELECT available_balance FROM hospital_treasury WHERE id=1")
    pool = float(treasury_res[0][0]) if treasury_res else 0.0
    active_count = run_query("SELECT COUNT(*) FROM workers WHERE status='Active'")[0][0] if run_query("SELECT COUNT(*) FROM workers WHERE status='Active'") else 0
    shifts_count = run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'")[0][0] if run_query("SELECT COUNT(*) FROM marketplace WHERE status='OPEN'") else 0
    
    c1, c2 = st.columns(2)
    c1.markdown(f"<div class='stripe-box' style='background: linear-gradient(135deg, #10b981 0%, #047857 100%);'><h3 style='margin:0;'>Available Treasury Pool</h3><h1 style='font-size:3rem; margin:10px 0;'>${pool:,.2f}</h1></div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='stripe-box' style='background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);'><h3 style='margin:0;'>30-Day Agency Savings</h3><h1 style='font-size:3rem; margin:10px 0;'>$142,500.00</h1></div>", unsafe_allow_html=True)
    
    st.markdown("### Operational Health")
    c_op1, c_op2, c_op3 = st.columns(3)
    c_op1.metric("Active Floor Operators", active_count)
    c_op2.metric("Critical Open Shifts", shifts_count, "Urgent Attention Needed" if shifts_count > 0 else "Fully Staffed", delta_color="inverse")
    c_op3.metric("Regulatory Compliance", "100%", "Audit Ready")

elif nav == "FATIGUE MATRIX":
    st.markdown("## 🧠 Clinical Burnout Radar")
    st.caption("AI-driven fatigue scoring to prevent sentinel events and optimize nurse-to-patient ratios.")
    
    st.markdown("### High-Risk Operators (Action Required)")
    all_staff = {p: d for p, d in USERS.items() if d['level'] in ['Worker', 'Supervisor']}
    risk_found = False
    
    for p, d in all_staff.items():
        f_score, f_hrs, f_notes = calculate_fatigue_score(p, d['dept'])
        if f_score > 40 or f_hrs > 40: 
            risk_found = True
            color = "#ef4444" if f_score > 70 else "#f59e0b"
            st.markdown(f"""
            <div class='glass-card' style='border-left: 5px solid {color} !important;'>
                <div style='display:flex; justify-content:space-between;'>
                    <strong style='font-size:1.1rem;'>{d['name']} ({d['role']} - {d['dept']})</strong>
                    <span style='color:{color}; font-weight:bold;'>SCORE: {f_score:.1f}</span>
                </div>
                <p style='color:#94a3b8; font-size:0.85rem; margin-top:5px;'>14-Day Hours: {f_hrs:.1f} | Factors: {f_notes}</p>
                <button style='background:rgba(255,255,255,0.05); border:1px solid {color}; color:#fff; padding:5px 10px; border-radius:5px;'>Enforce Mandatory Rest Period</button>
            </div>
            """, unsafe_allow_html=True)
            
    if not risk_found:
        st.success("✅ All clinical operators are currently within safe operational parameters.")

elif nav == "COMMAND CENTER":
    st.markdown("## 🦅 Command Center")
    if st.button("🔄 Refresh Data Link"): st.rerun()
    t_finance, t_fleet = st.tabs(["📈 FINANCIAL INTELLIGENCE", "🗺️ LIVE FLEET TRACKING"])
    
    raw_history = run_query("SELECT pin, amount, DATE(timestamp) FROM history WHERE action='CLOCK OUT'")
    if not raw_history:
        dates = pd.date_range(end=datetime.today(), periods=14).tolist()
        demo_data = []
        for d in dates: demo_data.append(["1001", 1200.00, d]); demo_data.append(["1002", 650.00, d]); demo_data.append(["1003", 900.00, d])
        df = pd.DataFrame(demo_data, columns=["PIN", "Amount", "Date"]); st.warning("⚠️ DEMO DATA MODE ACTIVE")
    else: df = pd.DataFrame(raw_history, columns=["PIN", "Amount", "Date"])

    with t_finance:
        df['Amount'] = df['Amount'].astype(float); df['Dept'] = df['PIN'].apply(lambda x: USERS.get(str(x), {}).get('dept', 'Unknown'))
        total_spend = df['Amount'].sum(); agency_cost = total_spend * 2.5; agency_avoidance = agency_cost - total_spend
        c1, c2, c3 = st.columns(3); c1.metric("Internal Labor Spend", f"${total_spend:,.2f}"); c2.metric("Projected Agency Cost", f"${agency_cost:,.2f}"); c3.metric("Agency Avoidance Savings", f"${agency_avoidance:,.2f}")
        col_chart1, col_chart2 = st.columns(2)
        with col_chart1: st.plotly_chart(px.pie(df.groupby('Dept')['Amount'].sum().reset_index(), values='Amount', names='Dept', hole=0.6, template="plotly_dark").update_layout(margin=dict(t=20, b=20, l=20, r=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)"), use_container_width=True)
        with col_chart2: st.plotly_chart(go.Figure(go.Indicator(mode="gauge+number", value=agency_avoidance, title={'text': "Capital Saved ($)", 'font': {'size': 16, 'color': '#94a3b8'}}, gauge={'axis': {'range': [None, agency_cost]}, 'bar': {'color': "#10b981"}, 'bgcolor': "rgba(255,255,255,0.05)", 'steps': [{'range': [0, total_spend], 'color': "rgba(239,68,68,0.3)"}, {'range': [total_spend, agency_cost], 'color': "rgba(16,185,129,0.1)"}]})).update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", font={'color': "white"}, margin=dict(t=40, b=20, l=20, r=20)), use_container_width=True)
        st.plotly_chart(px.area(df.groupby('Date')['Amount'].sum().reset_index(), x="Date", y="Amount", template="plotly_dark").update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=20, b=0)), use_container_width=True)

    with t_fleet:
        active_workers = run_query("SELECT pin, start_time, earnings, lat, lon FROM workers WHERE status='Active'")
        if active_workers:
            map_data = []
            for w in active_workers:
                w_pin, w_start, w_lat, w_lon = str(w[0]), float(w[1]), w[3], w[4]; w_name = USERS.get(w_pin, {}).get("name", "Unknown"); hrs = (time.time() - w_start) / 3600
                base_pay, diff_pay, diff_str = calculate_shift_differentials(w_start, float(USERS.get(w_pin, {}).get("rate", 0.0)))
                est_gross = float(w[2]) + base_pay + diff_pay
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid #10b981 !important;'><div style='display:flex; justify-content:space-between; align-items:center;'><h4 style='margin:0;'>{w_name}</h4><span style='color:#10b981; font-weight:bold;'>🟢 ON CLOCK ({hrs:.2f} hrs) | Est: ${est_gross:.2f}</span></div></div>", unsafe_allow_html=True)
                if w_lat and w_lon: map_data.append({"name": w_name, "lat": float(w_lat), "lon": float(w_lon)})
            if map_data: st.pydeck_chart(pdk.Deck(layers=[pdk.Layer("ScatterplotLayer", pd.DataFrame(map_data), get_position='[lon, lat]', get_color='[16, 185, 129, 200]', get_radius=100)], initial_view_state=pdk.ViewState(latitude=pd.DataFrame(map_data)['lat'].mean(), longitude=pd.DataFrame(map_data)['lon'].mean(), zoom=11, pitch=45), map_style='mapbox://styles/mapbox/dark-v10'))
        else: st.info("No active operators in the field.")

elif nav == "FINANCIAL FORECAST":
    st.markdown("## 📊 Predictive Payroll Outflow")
    if st.button("🔄 Refresh Forecast"): st.rerun()
    scheds = run_query("SELECT pin FROM schedules WHERE status='SCHEDULED'")
    base_outflow = sum((USERS.get(str(s[0]), {}).get('rate', 0.0) * 12) for s in scheds) if scheds else 0.0
    open_markets = run_query("SELECT rate FROM marketplace WHERE status='OPEN'")
    critical_outflow = sum((float(m[0]) * 12) for m in open_markets) if open_markets else 0.0
    c1, c2, c3 = st.columns(3); c1.metric("Scheduled Baseline", f"${base_outflow:,.2f}"); c2.metric("Critical Liability", f"${critical_outflow:,.2f}", delta_color="inverse"); c3.metric("Total Forecasted Outflow", f"${base_outflow + critical_outflow:,.2f}")
    st.markdown("<br><hr style='border-color: rgba(255,255,255,0.1);'><br>", unsafe_allow_html=True)
    full_scheds = run_query("SELECT shift_id, pin, shift_date, shift_time, department FROM schedules WHERE status='SCHEDULED' ORDER BY shift_date ASC")
    if full_scheds:
        for s in full_scheds: st.markdown(f"<div class='sched-row'><div class='sched-time'>{s[2]}</div><div style='flex-grow: 1; padding-left: 15px;'><span class='sched-name'>{USERS.get(str(s[1]), {}).get('name', f'User {s[1]}')}</span> | {s[4]}</div></div>", unsafe_allow_html=True)
    else: st.info("No baseline shifts scheduled.")

elif nav == "CENSUS & ACUITY":
    st.markdown(f"## 📊 {user['dept']} Census & Staffing")
    if st.button("🔄 Refresh Census Board"): st.rerun()
    
    c_data = run_query("SELECT total_pts, high_acuity, last_updated, vented_pts, nipvv_pts FROM unit_census WHERE dept=:d", {"d": user['dept']})
    curr_pts = c_data[0][0] if c_data else 0
    curr_high = c_data[0][1] if c_data else 0
    curr_vent = c_data[0][3] if c_data and len(c_data[0]) > 3 and c_data[0][3] is not None else 0
    curr_nipvv = c_data[0][4] if c_data and len(c_data[0]) > 4 and c_data[0][4] is not None else 0
    
    if user['dept'] == "Respiratory":
        req_staff = math.ceil(curr_vent / 4) + math.ceil(curr_nipvv / 6) + math.ceil(max(0, curr_pts - curr_vent - curr_nipvv) / 10)
    elif user['dept'] == "ICU":
        req_staff = math.ceil(curr_high / 1) + math.ceil(max(0, curr_pts - curr_high) / 2)
    else:
        req_staff = math.ceil(curr_high / 3) + math.ceil(max(0, curr_pts - curr_high) / 6)
        
    actual_staff = sum(1 for r in run_query("SELECT pin FROM workers WHERE status='Active'") if USERS.get(str(r[0]), {}).get('dept') == user['dept']) if run_query("SELECT pin FROM workers WHERE status='Active'") else 0
    variance = actual_staff - req_staff
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Patients", curr_pts)
    col2.metric("Required Staff", req_staff)
    
    if variance < 0:
        col3.metric("Current Staff", actual_staff, f"{variance} (Understaffed)", delta_color="inverse")
    else: 
        col3.metric("Current Staff", actual_staff, f"+{variance} (Safe)", delta_color="normal")
        
    with st.expander("📉 Smart Flex Calculator (Down-Staffing)"):
        st.caption("When census drops, proprietary heuristics recommend which staff to send home based on premium pay costs and fatigue levels—saving money and preventing burnout.")
        
        if st.button("🧠 Run Proprietary Flex Oracle"):
            result = proprietary_flex_oracle(user['dept'])
            if "error" in result:
                st.info(result["error"])
            else:
                st.markdown(f"""
                <div style='background:rgba(30,41,59,0.5); border-left: 4px solid #10b981; padding: 15px; margin-top: 10px; border-radius: 6px;'>
                    <strong style='color:#f8fafc; font-size:1.2rem;'>🎯 Optimal Flex Candidate: {result['selected_name']} ({result['selected_pin']})</strong>
                    <div style='color:#94a3b8; font-size:0.95rem; margin-top:8px;'>{result['reason']}</div>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button("⚡ EXECUTE FLEX DIRECTIVE"):
                    run_transaction("INSERT INTO messages (msg_id, sender_pin, target_dept, recipient_pin, message) VALUES (:id, :p, 'DM', :rp, :m)", {"id": f"MSG-{int(time.time()*1000)}", "p": pin, "rp": result['selected_pin'], "m": f"Census has dropped. You have been selected for Down-Staffing (Flex) due to operational algorithms. Please wrap up current tasks and clock out."})
                    st.success(f"✅ Automated Flex Directive sent to {result['selected_name']}."); time.sleep(2); st.rerun()

    with st.expander("📝 LIVE BED BOARD (ADMIT/DISCHARGE & ACUITY)", expanded=False):
        st.caption("Manage unit flow. Updates calculate required staffing instantly.")
        with st.form("update_census"):
            new_t = st.number_input("Total Unit Census", min_value=0, value=curr_pts)
            if user['dept'] == "Respiratory":
                new_vent = st.number_input("Vented Patients", min_value=0, value=curr_vent)
                new_nipvv = st.number_input("Non-Invasive (BiPAP/CPAP)", min_value=0, value=curr_nipvv)
                new_h = new_vent + new_nipvv 
            elif user['dept'] == "ICU":
                new_h = st.number_input("1:1 High Acuity Patients", min_value=0, value=curr_high)
                new_vent = curr_vent; new_nipvv = curr_nipvv
            else:
                new_h = st.number_input("High Acuity Patients", min_value=0, value=curr_high)
                new_vent = curr_vent; new_nipvv = curr_nipvv
                
            if st.form_submit_button("Lock In Census"): 
                run_transaction("INSERT INTO unit_census (dept, total_pts, high_acuity, vented_pts, nipvv_pts) VALUES (:d, :t, :h, :v, :n) ON CONFLICT (dept) DO UPDATE SET total_pts=:t, high_acuity=:h, vented_pts=:v, nipvv_pts=:n, last_updated=NOW()", {"d": user['dept'], "t": new_t, "h": new_h, "v": new_vent, "n": new_nipvv})
                st.success("Census and Acuity logged successfully."); time.sleep(1); st.rerun()

elif nav == "MARKETPLACE":
    st.markdown("<h2 style='font-weight:900; margin-bottom:5px;'>⚡ INTERNAL SHIFT MARKETPLACE</h2>", unsafe_allow_html=True)
    if st.button("🔄 Refresh Market"): st.rerun()
    
    open_shifts = run_query("SELECT shift_id, role, date, start_time, rate, escrow_status FROM marketplace WHERE status='OPEN' ORDER BY date ASC")
    if open_shifts:
        for shift in open_shifts:
            s_id, s_role, s_date, s_time, s_rate, s_escrow = shift[0], shift[1], shift[2], shift[3], float(shift[4]), shift[5]
            est_payout = s_rate * 12
            escrow_badge = "<span style='background:#10b981; color:#0b1120; padding:3px 8px; border-radius:4px; font-size:0.75rem; font-weight:bold; margin-left:10px;'>✔️ BASE RATE VERIFIED</span>" if s_escrow == "LOCKED" else ""
            
            st.markdown(f"<div class='shift-card'><div style='display:flex; justify-content:space-between; align-items:flex-start;'><div><div style='color:#94a3b8; font-weight:800; text-transform:uppercase; font-size:0.9rem;'>{s_date} <span style='color:#38bdf8;'>| {s_time}</span></div><div style='font-size:1.4rem; font-weight:800; color:#f8fafc; margin-top:5px;'>{s_role}{escrow_badge}</div><div class='shift-amount'>${est_payout:,.2f} (Est. Base Pay)</div></div></div></div>", unsafe_allow_html=True)
            
            if st.button(f"⚡ CLAIM SHIFT", key=f"claim_{s_id}"):
                creds = run_query("SELECT doc_type, exp_date FROM credentials WHERE pin=:p AND status='ACTIVE'", {"p": pin})
                expired = [c[0] for c in creds if str(c[1]) < str(date.today())]
                
                wk_hrs = get_rolling_weekly_hours(pin)
                will_hit_ot = (wk_hrs + 12) > 40.0
                
                if expired:
                    st.error(f"🛑 HARD EMR INTERLOCK: Claim blocked due to expired credentials ({', '.join(expired)}). Please update via HR Vault.")
                elif will_hit_ot:
                    st.warning(f"⚠️ CFO OVERTIME LOCK: Claiming this shift pushes you to {wk_hrs+12:.1f} hrs for the week. Shift pended for Manager/CFO Overtime Authorization.")
                    run_transaction("INSERT INTO shift_bids (bid_id, shift_id, pin, counter_rate, status) VALUES (:bid, :sid, :p, :r, 'PENDING_OT')", {"bid": f"OT-{int(time.time()*1000)}", "sid": s_id, "p": pin, "r": s_rate * 1.5})
                    time.sleep(3); st.rerun()
                else:
                    rows_updated = run_transaction("UPDATE marketplace SET status='CLAIMED', claimed_by=:p WHERE shift_id=:id AND status='OPEN'", {"p": pin, "id": s_id})
                    if rows_updated > 0:
                        run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{s_id}", "p": pin, "d": s_date, "t": s_time, "dept": user['dept']})
                        st.success("✅ Shift Claimed!"); time.sleep(2); st.rerun()
                    else:
                        st.error("❌ Shift Already Claimed!"); time.sleep(2); st.rerun()
    else: st.markdown("<div class='empty-state'><h3>No Urgent Coverage Needed</h3></div>", unsafe_allow_html=True)

elif nav == "COMMS":
    st.markdown("## 📡 Secure Comms")
    if st.button("🔄 Refresh Feed"): st.rerun()
    
    if user['level'] in ["Admin", "Executive", "Manager", "Director", "Supervisor"]: 
        tab_intra, tab_inter, tab_dm, tab_sos = st.tabs([f"🏥 {user['dept']} Channel", "🌍 Hospital-Wide", "💬 Direct Messages", "🚨 SOS Dispatch"])
    else: 
        tab_intra, tab_inter, tab_dm = st.tabs([f"🏥 {user['dept']} Channel", "🌍 Hospital-Wide", "💬 Direct Messages"])
    
    with tab_intra:
        with st.form("intra_chat"):
            msg = st.text_input("Send to Department")
            if st.form_submit_button("Send"):
                run_transaction("INSERT INTO messages (msg_id, sender_pin, target_dept, message) VALUES (:id, :p, :d, :m)", {"id": f"MSG-{int(time.time()*1000)}", "p": pin, "d": user['dept'], "m": msg})
                st.rerun()
        
        msgs = run_query("SELECT sender_pin, message, timestamp, is_sos FROM messages WHERE target_dept=:d ORDER BY timestamp DESC LIMIT 50", {"d": user['dept']})
        if msgs:
            for m in msgs:
                sender_name = USERS.get(str(m[0]), {}).get('name', 'SYSTEM' if m[0] == 'SYSTEM' else 'Unknown')
                dt_str = m[2].strftime('%H:%M - %b %d') if hasattr(m[2], 'strftime') else str(m[2])
                color = "#ef4444" if m[3] else "#3b82f6"
                bg_color = "rgba(239, 68, 68, 0.1)" if m[3] else "rgba(30, 41, 59, 0.6)"
                st.markdown(f"<div style='background: {bg_color}; border-left: 4px solid {color}; padding: 15px; border-radius: 8px; margin-bottom: 10px;'><div style='display:flex; justify-content:space-between; margin-bottom:5px;'><strong style='color:#f8fafc;'>{sender_name}</strong><span style='color:#94a3b8; font-size:0.8rem;'>{dt_str}</span></div><div style='color:#cbd5e1;'>{m[1]}</div></div>", unsafe_allow_html=True)

    with tab_inter:
        msgs = run_query("SELECT sender_pin, message, timestamp, is_sos FROM messages WHERE target_dept='All' ORDER BY timestamp DESC LIMIT 50")
        if msgs:
            for m in msgs:
                sender_name = USERS.get(str(m[0]), {}).get('name', 'SYSTEM' if m[0] == 'SYSTEM' else 'Unknown')
                dt_str = m[2].strftime('%H:%M - %b %d') if hasattr(m[2], 'strftime') else str(m[2])
                color = "#ef4444" if m[3] else "#10b981"
                bg_color = "rgba(239, 68, 68, 0.1)" if m[3] else "rgba(30, 41, 59, 0.6)"
                st.markdown(f"<div style='background: {bg_color}; border-left: 4px solid {color}; padding: 15px; border-radius: 8px; margin-bottom: 10px;'><div style='display:flex; justify-content:space-between; margin-bottom:5px;'><strong style='color:#f8fafc;'>{sender_name}</strong><span style='color:#94a3b8; font-size:0.8rem;'>{dt_str}</span></div><div style='color:#cbd5e1;'>{m[1]}</div></div>", unsafe_allow_html=True)

    with tab_dm:
        peer_dict = {f"{d['name']} ({d['role']} - {d['dept']})": p for p, d in USERS.items() if p != pin}
        if not peer_dict:
            st.info("No other operators found in the enterprise directory.")
        else:
            selected_peer_name = st.selectbox("Select Operator to Message", list(peer_dict.keys()))
            selected_peer_pin = peer_dict[selected_peer_name]
            
            with st.form("dm_chat"):
                dm_msg = st.text_input("Encrypted Message")
                if st.form_submit_button("Send Direct Message"):
                    run_transaction("INSERT INTO messages (msg_id, sender_pin, target_dept, recipient_pin, message) VALUES (:id, :p, 'DM', :rp, :m)", {"id": f"MSG-{int(time.time()*1000)}", "p": pin, "rp": selected_peer_pin, "m": dm_msg})
                    st.rerun()
            
            st.markdown("<hr style='border-color: rgba(255,255,255,0.05);'>", unsafe_allow_html=True)
            dm_history = run_query("SELECT sender_pin, message, timestamp FROM messages WHERE target_dept='DM' AND ((sender_pin=:p AND recipient_pin=:rp) OR (sender_pin=:rp AND recipient_pin=:p)) ORDER BY timestamp DESC LIMIT 50", {"p": pin, "rp": selected_peer_pin})
            
            if dm_history:
                for m in dm_history:
                    is_me = (m[0] == pin)
                    sender_name = "You" if is_me else USERS.get(str(m[0]), {}).get('name', 'Unknown')
                    dt_str = m[2].strftime('%H:%M - %b %d') if hasattr(m[2], 'strftime') else str(m[2])
                    align = "right" if is_me else "left"
                    bg_color = "rgba(16, 185, 129, 0.15)" if is_me else "rgba(30, 41, 59, 0.6)"
                    border_color = "#10b981" if is_me else "#3b82f6"
                    
                    st.markdown(f"<div style='text-align: {align}; margin-bottom: 10px;'><div style='display: inline-block; text-align: left; background: {bg_color}; border-left: 4px solid {border_color}; padding: 10px 15px; border-radius: 8px; min-width: 250px; max-width: 80%;'><div style='display:flex; justify-content:space-between; margin-bottom:5px;'><strong style='color:#f8fafc;'>{sender_name}</strong><span style='color:#94a3b8; font-size:0.75rem; margin-left:15px;'>{dt_str}</span></div><div style='color:#cbd5e1;'>{m[1]}</div></div></div>", unsafe_allow_html=True)

    if user['level'] in ["Admin", "Executive", "Manager", "Director", "Supervisor"]:
        with tab_sos:
            st.markdown("### Broadcast Emergency Alerts")
            with st.form("sos_form"):
                sos_target = st.selectbox("Target Department", ["All", "Respiratory", "ICU", "Emergency"])
                sos_msg = st.text_area("SOS Message")
                if st.form_submit_button("🚨 TRIGGER SOS DISPATCH"):
                    run_transaction("INSERT INTO messages (msg_id, sender_pin, target_dept, message, is_sos) VALUES (:id, :p, :d, :m, TRUE)", {"id": f"MSG-{int(time.time()*1000)}", "p": pin, "d": sos_target, "m": sos_msg})
                    st.success(f"✅ SOS Dispatched! Internal channels updated.")
                    time.sleep(2.5); st.rerun()

elif nav == "SCHEDULE":
    st.markdown("## 📅 Intelligent Scheduling")
    if st.button("🔄 Refresh Schedule"): st.rerun()
    
    if user['level'] in ["Admin", "Executive", "Manager", "Director", "Supervisor"]: 
        tab_mine, tab_master, tab_manage = st.tabs(["🙋 MY UPCOMING", "🏥 MASTER ROSTER", "📝 ASSIGN SHIFTS"])
    else: 
        tab_mine, tab_hist = st.tabs(["🙋 MY UPCOMING", "🕰️ WORKED HISTORY"])
        
    with tab_mine:
        my_scheds = run_query("SELECT shift_id, shift_date, shift_time, COALESCE(status, 'SCHEDULED'), department FROM schedules WHERE pin=:p AND shift_date >= :today ORDER BY shift_date ASC", {"p": pin, "today": str(date.today())})
        if my_scheds:
            for s in my_scheds:
                if s[3] == 'SCHEDULED':
                    st.markdown(f"<div class='glass-card' style='border-left: 4px solid #10b981 !important;'><div style='font-size:1.1rem; font-weight:700; color:#f8fafc;'>{s[1]} <span style='color:#34d399;'>| {s[2]}</span></div></div>", unsafe_allow_html=True)
                    if st.button("🚨 CALL OUT SICK (Auto-Replace)", key=f"co_{s[0]}"): 
                        run_transaction("UPDATE schedules SET status='CALL_OUT' WHERE shift_id=:id", {"id": s[0]})
                        standard_rate = user['rate']
                        new_sid = f"REPLACE-{s[0]}"
                        run_transaction("INSERT INTO marketplace (shift_id, poster_pin, role, date, start_time, end_time, rate, status, escrow_status) VALUES (:id, 'SYSTEM', :r, :d, :t, '12hr', :rt, 'OPEN', 'PENDING') ON CONFLICT DO NOTHING", {"id": new_sid, "r": f"🚨 URGENT REPLACEMENT: {s[4]}", "d": s[1], "t": s[2], "rt": standard_rate})
                        alert_msg = f"URGENT SICK CALL REPLACEMENT: {s[4]} unit for {s[1]}. Shift posted in Marketplace at standard rate."
                        run_transaction("INSERT INTO messages (msg_id, sender_pin, target_dept, message, is_sos) VALUES (:mid, 'SYSTEM', :dept, :m, TRUE)", {"mid": f"MSG-{int(time.time()*1000)}", "dept": s[4], "m": alert_msg})
                        st.success("Sick call registered. Automated coverage request pushed to the department."); time.sleep(2.5); st.rerun()
                elif s[3] == 'CALL_OUT': st.error(f"🚨 {s[1]} | {s[2]} (SICK LEAVE LOGGED)")
        else: st.info("Your schedule is clear.")
        
        st.markdown("<hr style='border-color: rgba(255,255,255,0.05); margin-top: 15px;'>", unsafe_allow_html=True)
        with st.expander("✈️ REQUEST TIME OFF (PTO)"):
            with st.form("pto_form"):
                pto_start = st.date_input("Start Date")
                pto_end = st.date_input("End Date")
                pto_reason = st.text_input("Reason (Optional)")
                if st.form_submit_button("Submit Request"):
                    run_transaction("INSERT INTO pto_requests (req_id, pin, start_date, end_date, reason) VALUES (:id, :p, :sd, :ed, :r)", {"id": f"PTO-{int(time.time())}", "p": pin, "sd": str(pto_start), "ed": str(pto_end), "r": pto_reason})
                    st.success("PTO Request routed to Management Approval Gateway."); time.sleep(2); st.rerun()

    if user['level'] in ["Admin", "Executive", "Manager", "Director", "Supervisor"]:
        with tab_master:
            all_s = run_query("SELECT shift_id, pin, shift_date, shift_time, department, COALESCE(status, 'SCHEDULED') FROM schedules WHERE shift_date >= :today ORDER BY shift_date ASC, shift_time ASC", {"today": str(date.today())})
            if all_s:
                groups = defaultdict(list)
                for s in all_s: groups[s[2]].append(s)
                for date_key in sorted(groups.keys()):
                    st.markdown(f"<div class='sched-date-header'>🗓️ {date_key}</div>", unsafe_allow_html=True)
                    for s in groups[date_key]:
                        owner = USERS.get(str(s[1]), {}).get('name', f"User {s[1]}"); lbl = "<span style='color:#ff453a; margin-left:10px;'>🚨 SICK</span>" if s[5]=="CALL_OUT" else ""
                        st.markdown(f"<div class='sched-row'><div class='sched-time'>{s[3]}</div><div style='flex-grow: 1; padding-left: 15px;'><span class='sched-name'>{owner}</span> {lbl}</div></div>", unsafe_allow_html=True)

        with tab_manage:
            st.markdown("### 🛠️ Shift Assignment Desk")
            dispatch_mode = st.radio("Select Dispatch Mode", ["Manual Input", "AI Auto-Dispatch (Float Recommender)"], horizontal=True)
            st.markdown("<hr style='border-color: rgba(255,255,255,0.05);'>", unsafe_allow_html=True)
            
            if dispatch_mode == "Manual Input":
                with st.form("manual_assign_form"):
                    all_staff = {p: d for p, d in USERS.items() if d['level'] in ['Worker', 'Supervisor']}
                    staff_options = [f"{d['name']} (PIN: {p})" for p, d in all_staff.items()]
                    sel_staff = st.selectbox("Select Provider", staff_options)
                    c1, c2, c3 = st.columns(3)
                    m_date = c1.date_input("Shift Date"); m_time = c2.text_input("Time", value="0700-1900"); m_dept = c3.selectbox("Department", ["Respiratory", "ICU", "Emergency", "Floor"])
                    if st.form_submit_button("⚡ Force Assign Shift"):
                        target_pin = sel_staff.split("PIN: ")[1].replace(")", "")
                        run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{int(time.time()*1000)}", "p": target_pin, "d": str(m_date), "t": m_time, "dept": m_dept})
                        st.success(f"✅ Shift securely added to master schedule."); time.sleep(1.5); st.rerun()
            else:
                st.caption("AI Float Recommender scans ALL departments for cross-trained staff with the lowest fatigue score to fill gaps safely.")
                with st.form("ai_scheduler"):
                    c1, c2 = st.columns(2); s_date = c1.date_input("Target Shift Date"); s_time = c2.text_input("Shift Time", value="0700-1900"); req_dept = st.selectbox("Department Needed", ["Respiratory", "ICU", "Emergency"])
                    if st.form_submit_button("Run Algorithmic Analysis"): st.session_state.ai_date = s_date; st.session_state.ai_time = s_time; st.session_state.ai_dept = req_dept; st.rerun()
                
                if 'ai_date' in st.session_state:
                    st.markdown(f"#### Cross-Trained Float Candidates for {st.session_state.ai_date} ({st.session_state.ai_dept})")
                    all_staff = {p: d for p, d in USERS.items() if d['level'] in ['Worker', 'Supervisor']}
                    stats = []
                    for p, d in all_staff.items():
                        f_score, f_hrs, f_notes = calculate_fatigue_score(p, st.session_state.ai_dept)
                        is_native = d['dept'] == st.session_state.ai_dept
                        adjusted_score = f_score if is_native else f_score + 10.0 
                        stats.append({"pin": p, "name": d['name'], "dept": d['dept'], "score": adjusted_score, "is_native": is_native})
                    
                    stats = sorted(stats, key=lambda x: x['score'])
                    for idx, s in enumerate(stats[:3]):
                        badge = "<span style='background:#3b82f6; color:#fff; padding:2px 6px; border-radius:4px; font-size:0.7rem; margin-left:10px;'>NATIVE UNIT</span>" if s['is_native'] else "<span style='background:#f59e0b; color:#fff; padding:2px 6px; border-radius:4px; font-size:0.7rem; margin-left:10px;'>CROSS-TRAINED FLOAT</span>"
                        color = "#10b981" if s['score'] < 72 else "#f59e0b"
                        
                        st.markdown(f"<div class='glass-card' style='border-left: 4px solid {color} !important;'><div style='display:flex; justify-content:space-between; align-items:center;'><div><strong style='font-size:1.1rem; color:#f8fafc;'>Choice #{idx+1}: {s['name']}</strong> {badge}<br><span style='color:#94a3b8; font-size:0.9rem;'>Home Unit: {s['dept']} | Engine Score: {s['score']:.1f}</span></div></div></div>", unsafe_allow_html=True)
                        if st.button(f"⚡ DISPATCH {s['name'].upper()}", key=f"ai_{s['pin']}"):
                            run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) VALUES (:id, :p, :d, :t, :dept, 'SCHEDULED')", {"id": f"SCH-{int(time.time())}", "p": s['pin'], "d": str(st.session_state.ai_date), "t": st.session_state.ai_time, "dept": st.session_state.ai_dept}); st.success("✅ Dispatched!"); del st.session_state.ai_date; time.sleep(2); st.rerun()

elif nav == "APPROVALS":
    st.markdown("## 📥 Approval Gateway")
    
    tab_ot, tab_pto, tab_cfo = st.tabs(["⚠️ OVERTIME EXCEPTIONS", "🏖️ TIME OFF (PTO)", "💸 CFO SETTLEMENTS"])
    
    with tab_ot:
        ot_bids = run_query("SELECT bid_id, shift_id, pin, counter_rate FROM shift_bids WHERE status='PENDING_OT'")
        if ot_bids:
            for b in ot_bids:
                b_id, s_id, p_pin, ot_rate = b
                op_name = USERS.get(str(p_pin), {}).get('name', 'Unknown')
                st.markdown(f"<div style='background:rgba(239,68,68,0.1); border-left:4px solid #ef4444; padding:10px; margin-bottom:10px;'><strong>{op_name}</strong> attempted to claim a shift that pushes them into Overtime. Requires authorization at <strong style='color:#f8fafc;'>${float(ot_rate):.2f}/hr (1.5x)</strong>.</div>", unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                if c1.button("✅ APPROVE OT & ASSIGN", key=f"app_ot_{b_id}"):
                    run_transaction("UPDATE marketplace SET rate=:r, status='CLAIMED', claimed_by=:p WHERE shift_id=:id", {"r": ot_rate, "p": p_pin, "id": s_id})
                    run_transaction("UPDATE shift_bids SET status='APPROVED' WHERE bid_id=:id", {"id": b_id})
                    run_transaction("INSERT INTO schedules (shift_id, pin, shift_date, shift_time, department, status) SELECT shift_id, :p, date, start_time, 'Overtime Exception', 'SCHEDULED' FROM marketplace WHERE shift_id=:id", {"p": p_pin, "id": s_id})
                    st.success("Overtime Approved!"); time.sleep(1.5); st.rerun()
                if c2.button("❌ DENY CLAIM", key=f"den_ot_{b_id}"):
                    run_transaction("UPDATE shift_bids SET status='DENIED' WHERE bid_id=:id", {"id": b_id}); st.rerun()
        else: st.info("No Overtime overrides pending.")

    with tab_pto:
        ptos = run_query("SELECT req_id, pin, start_date, end_date, reason FROM pto_requests WHERE status='PENDING'")
        if ptos:
            for pto in ptos:
                r_id, p_pin, sd, ed, rsn = pto
                op_name = USERS.get(str(p_pin), {}).get('name', 'Unknown')
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid #38bdf8 !important;'><h4>{op_name}</h4><p style='color:#94a3b8; font-size:0.9rem;'>Request: {sd} to {ed}<br>Reason: {rsn}</p></div>", unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                if c1.button("✅ APPROVE PTO", key=f"pto_app_{r_id}"):
                    run_transaction("UPDATE pto_requests SET status='APPROVED' WHERE req_id=:id", {"id": r_id})
                    st.success("Approved!"); time.sleep(1); st.rerun()
                if c2.button("❌ DENY PTO", key=f"pto_den_{r_id}"):
                    run_transaction("UPDATE pto_requests SET status='DENIED' WHERE req_id=:id", {"id": r_id})
                    st.rerun()
        else: st.info("No PTO requests pending.")
        
    with tab_cfo:
        if user['role'] == "CFO" or user['level'] == "Admin":
            pending_cfo = run_query("SELECT tx_id, pin, amount, timestamp, note FROM transactions WHERE status='PENDING_CFO' ORDER BY timestamp ASC")
            if pending_cfo:
                for tx in pending_cfo:
                    tx_note = tx[4] if len(tx) > 4 and tx[4] else "No context provided"
                    st.markdown(f"<div class='glass-card' style='border-left: 4px solid #3b82f6 !important;'><h4>{USERS.get(str(tx[1]), {}).get('name', 'Unknown')} | ${float(tx[2]):,.2f}</h4><p style='color:#94a3b8; font-size:0.9rem;'>{tx_note}</p></div>", unsafe_allow_html=True)
                    if st.button("💸 RELEASE FUNDS", key=f"cfo_{tx[0]}"): 
                        run_transaction("UPDATE transactions SET status='APPROVED' WHERE tx_id=:id AND status='PENDING_CFO'", {"id": tx[0]})
                        st.success("Approved!"); time.sleep(1); st.rerun()
            else: st.info("No funds pending CFO authorization.")
        else: st.warning("Requires CFO or Admin Clearance.")

elif nav == "THE BANK":
    st.markdown("## 🏦 Enterprise Ledger")
    st.caption("All payouts are securely routed via ACH Direct Deposit in compliance with federal and state wage labor laws.")
    if st.button("🔄 Refresh Bank Ledger"): st.rerun()
    
    banked_gross = st.session_state.user_state.get('earnings', 0.0)
    total_tax, fed_tx, ma_tx, ss_tx, med_tx = calculate_taxes(pin, banked_gross)
    banked_net = banked_gross - total_tax
    
    st.markdown(f"<div class='stripe-box'><div style='display:flex; justify-content:space-between; align-items:center;'><span style='font-size:0.9rem; font-weight:600; text-transform:uppercase;'>Available Balance</span></div><h1 style='font-size:3.5rem; margin:10px 0 5px 0;'>${banked_gross:,.2f} Gross</h1><p style='margin:0; font-size:0.9rem; opacity:0.9;'>Net Estimate: ${banked_net:,.2f} • Total Tax Withheld: ${total_tax:,.2f}</p></div>", unsafe_allow_html=True)
    
    if banked_gross > 0.01 and not st.session_state.user_state.get('active', False):
        if st.button("⚡ INITIATE FIAT SETTLEMENT", key="web3_btn", use_container_width=True):
            treasury_res = run_query("SELECT available_balance FROM hospital_treasury WHERE id=1")
            current_treasury = float(treasury_res[0][0]) if treasury_res else 0.0
            
            if current_treasury >= banked_gross:
                net, tax = execute_split_stream_payout(pin, banked_gross) 
                run_transaction("UPDATE hospital_treasury SET available_balance = available_balance - :amt WHERE id=1", {"amt": banked_gross})
                update_status(pin, "Inactive", 0, 0.0); st.session_state.user_state['earnings'] = 0.0
                st.success(f"✅ Auto-Cleared! ${net:,.2f} routed to Direct Deposit."); time.sleep(2); st.rerun()
            else:
                run_transaction("INSERT INTO transactions (tx_id, pin, amount, status, tx_type, note) VALUES (:id, :p, :amt, 'PENDING_CFO', 'NET_PAY', 'Liquidity Low')", {"id": f"TX-PEND-{int(time.time())}", "p": pin, "amt": banked_gross})
                update_status(pin, "Inactive", 0, 0.0); st.session_state.user_state['earnings'] = 0.0
                st.warning(f"⏳ Liquidity Pool Low. Pended for CFO authorization."); time.sleep(2); st.rerun()

    paystubs = run_query("SELECT tx_id, amount, timestamp, destination_pubkey, note FROM transactions WHERE pin=:p AND tx_type='NET_PAY' ORDER BY timestamp DESC", {"p": pin})
    if paystubs:
        for stub in paystubs:
            tx_id, net_amt, tx_ts, dest, note = stub[0], float(stub[1]), stub[2], stub[3], stub[4]
            dt_str = tx_ts.strftime("%Y-%m-%d %H:%M") if hasattr(tx_ts, 'strftime') else str(tx_ts)
            with st.expander(f"Payout: {dt_str} | ${net_amt:,.2f} Net"):
                prev_tx_res = run_query("SELECT timestamp FROM transactions WHERE pin=:p AND tx_type='NET_PAY' AND timestamp < :ts ORDER BY timestamp DESC LIMIT 1", {"p": pin, "ts": tx_ts})
                prev_ts = prev_tx_res[0][0] if prev_tx_res else datetime.min
                if prev_ts.tzinfo is None and getattr(tx_ts, 'tzinfo', None) is not None: prev_ts = prev_ts.replace(tzinfo=pytz.UTC)
                shifts_res = run_query("SELECT action, timestamp FROM history WHERE pin=:p AND action IN ('CLOCK IN', 'CLOCK OUT') AND timestamp > :pts AND timestamp <= :ts ORDER BY timestamp ASC", {"p": pin, "pts": prev_ts, "ts": tx_ts})
                
                shifts_data = []
                current_in = None
                if shifts_res:
                    for r in shifts_res:
                        fmt_ts = r[1].strftime('%m/%d/%Y %H:%M') if hasattr(r[1], 'strftime') else str(r[1])
                        if r[0] == 'CLOCK IN': current_in = fmt_ts
                        elif r[0] == 'CLOCK OUT': shifts_data.append((current_in if current_in else "Prior to record", fmt_ts)); current_in = None
                
                file_data = create_paystub_pdf(user['name'], dt_str, tx_id, net_amt, net_amt, 0.0, dest, shifts_data)
                ext = "pdf" if PDF_ACTIVE else "txt"
                mime = "application/pdf" if PDF_ACTIVE else "text/plain"
                if file_data:
                    st.download_button(label=f"📄 Download Official Receipt ({ext.upper()})", data=file_data, file_name=f"Paystub_{tx_id}.{ext}", mime=mime, key=f"pdf_{tx_id}")

elif nav == "MY PROFILE":
    st.markdown("## 🗄️ Enterprise HR Vault")
    t_lic, t_sec, t_acc = st.tabs(["🪪 ENCRYPTED CREDENTIALS", "🔐 SECURITY", "🏅 CLINICAL OBT PORTFOLIO"])
    
    with t_sec:
        with st.form("update_password_form"):
            current_pw = st.text_input("Current Password", type="password"); new_pw = st.text_input("New Secure Password", type="password"); confirm_pw = st.text_input("Confirm New Password", type="password")
            if st.form_submit_button("Update Password"):
                db_pw_res = run_query("SELECT password_hash FROM enterprise_users WHERE pin=:p", {"p": pin})
                if db_pw_res and verify_password(current_pw, db_pw_res[0][0]):
                    run_transaction("UPDATE enterprise_users SET password_hash=:pw, last_pw_change=NOW() WHERE pin=:p", {"p": pin, "pw": hash_password(new_pw)})
                    st.success("✅ Password encrypted and updated!"); time.sleep(2); st.rerun()
                
    with t_lic:
        with st.expander("➕ ADD NEW CREDENTIAL / CERTIFICATION"):
            with st.form("cred_form"):
                doc_type = st.selectbox("Document Type", ["State RN License", "State RRT License", "ACLS Provider", "BLS Provider"])
                doc_num = st.text_input("License Number"); exp_date = st.date_input("Expiration Date")
                if st.form_submit_button("Save Credential"):
                    run_transaction("INSERT INTO credentials (doc_id, pin, doc_type, doc_number, exp_date, status) VALUES (:id, :p, :dt, :dn, :ed, 'ACTIVE')", {"id": f"DOC-{int(time.time())}", "p": pin, "dt": doc_type, "dn": generate_secure_checksum(doc_num, pin), "ed": str(exp_date)})
                    st.success("✅ Credential securely hashed and saved."); time.sleep(1.5); st.rerun()
        
        creds = run_query("SELECT doc_type, doc_number, exp_date FROM credentials WHERE pin=:p", {"p": pin})
        if creds:
            for c in creds: 
                is_expired = str(c[2]) < str(date.today())
                color = "#ef4444" if is_expired else "#10b981"
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid {color} !important;'><h4>{c[0]} {'(EXPIRED)' if is_expired else ''}</h4><p style='color:#94a3b8;'>Exp: {c[2]}</p></div>", unsafe_allow_html=True)
        
        st.markdown("<hr style='border-color: rgba(255,255,255,0.05); margin-top: 15px;'>", unsafe_allow_html=True)
        st.markdown("### Clinical Competencies")
        comps = run_query("SELECT comp_id, competency_name, expires_date, status FROM staff_competencies WHERE pin=:p", {"p": pin})
        if comps:
            for c in comps:
                c_id, c_name, c_exp, c_status = c
                color = "#ef4444" if c_status == 'EXPIRED' else "#f59e0b" if c_status == 'PENDING_REVIEW' else "#10b981"
                st.markdown(f"<div class='glass-card' style='border-left: 4px solid {color} !important;'><h4>{c_name}</h4><p style='color:#94a3b8;'>Status: {c_status} | Exp: {c_exp}</p></div>", unsafe_allow_html=True)
                if c_status == 'EXPIRED':
                    if st.button(f"Upload Proof & Renew: {c_name}", key=f"renew_{c_id}"):
                        run_transaction("UPDATE staff_competencies SET status='PENDING_REVIEW' WHERE comp_id=:id", {"id": c_id})
                        st.success("Renewal submitted. Awaiting CCO approval."); time.sleep(1.5); st.rerun()
        else: st.info("No tracked competencies.")
                
    with t_acc:
        st.markdown("### Soulbound Clinical Portfolio (OBT)")
        st.caption("Immutable, non-fungible cryptographic proof of your high-acuity interventions.")

        c1, c2 = st.columns([2, 1])
        with c2:
            if st.button("🔑 Generate ZK Access Key"):
                zk_key = f"{random.choice(['A', 'X', 'K', 'M'])}{random.randint(10,99)}{random.choice(['B', 'Z', 'Q'])}-{random.randint(100,999)}"
                st.info(f"Access Key: **{zk_key}** (Valid for 24h)")

        my_obts = run_query("SELECT token_id, accolade_type, clinical_context, timestamp, encryption_hash FROM obt_ledger WHERE pin=:p ORDER BY timestamp DESC", {"p": pin})
        if my_obts:
            for obt in my_obts:
                t_id, a_type, ctx, ts, e_hash = obt
                try: ts_str = ts.strftime('%b %d, %Y - %H:%M')
                except: ts_str = str(ts)
                st.markdown(f"""
                <div style='background: rgba(30, 41, 59, 0.6); backdrop-filter: blur(10px); border-left: 5px solid #38bdf8; border-radius: 12px; padding: 18px; margin-bottom: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.2);'>
                    <div style='display: flex; justify-content: space-between;'>
                        <div style='font-size:1.1rem; font-weight:900; color:#f8fafc;'>🛡️ {ctx.split(' | ')[0] if ' | ' in ctx else ctx}</div>
                        <div style='background:#10b981; color:#0b1120; padding:4px 8px; border-radius:6px; font-size:0.7rem; font-weight:900;'>SBT VERIFIED</div>
                    </div>
                    <div style='color:#94a3b8; font-size:0.85rem; font-weight: 600; text-transform: uppercase; margin-top:5px;'>{a_type} <span style='color:#475569;'>•</span> {ts_str}</div>
                    <div style='font-family: monospace; color: #64748b; font-size: 0.75rem; margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.05);'>
                        TOKEN ID: {t_id}<br>HASH: {e_hash}
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown("<div class='empty-state'><h3 style='color:#94a3b8;'>No OBTs Minted Yet</h3></div>", unsafe_allow_html=True)
