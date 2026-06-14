import sqlite3
import csv
import io
import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Query
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─── Auth config ─────────────────────────────────────────────────────────────

SESSION_DURATION_HOURS = 24

# User directory — email is the login name
USERS = {
    "ajaree.to@thailandpost.com":    {"name": "Ajaree Tochai",               "password": "PMC@S&M2026"},
    "chawachit.so@thailandpost.com": {"name": "Chawachit Soonthornsaratoon", "password": "PMC@S&M2026"},
    "teerapat.ro@thailandpost.com":  {"name": "Teerapat Roekcharoen",        "password": "PMC@S&M2026"},
    "tantrawan.a@beryl8.com":        {"name": "Tantrawan Ajchariyavanich",   "password": "PMC@S&M2026"},
    "kanin.p@beryl8.com":            {"name": "Kanin Pinsuvana",             "password": "PMC@S&M2026"},
    "pimparat.p@beryl8.com":         {"name": "Pimparat Panchatree",         "password": "PMC@S&M2026"},
}

# In-memory session store: {token: {"expires_at": datetime, "email": str, "name": str}}
_sessions: dict = {}

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "pipeline.db"
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "template"

app = FastAPI(title="PMC Sales Pipeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Auth middleware ──────────────────────────────────────────────────────────

def _valid_session(request: Request) -> dict | None:
    """Returns session dict {expires_at, email, name} if valid, else None."""
    token = request.cookies.get("pmc_session")
    if not token or token not in _sessions:
        return None
    session = _sessions[token]
    if session["expires_at"] < datetime.now():
        del _sessions[token]
        return None
    return session

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Always allow: login endpoint + static assets + main HTML (has embedded login screen)
    public = ["/api/login", "/api/me", "/static/", "/favicon"]
    if path == "/" or any(path.startswith(p) for p in public):
        return await call_next(request)
    # Block everything else without a valid session
    if not _valid_session(request):
        if path.startswith("/api/"):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        # For non-API routes (e.g. direct URL access), redirect to root
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/")
    return await call_next(request)

# ─── Database ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS deals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        short TEXT,
        sector TEXT,
        useCase TEXT,
        service TEXT,
        stage TEXT,
        stageNum INTEGER,
        revenue REAL,
        fee TEXT,
        volume INTEGER,
        owner TEXT,
        notes TEXT,
        priority TEXT,
        effort INTEGER,
        competitive_risk TEXT,
        close_date TEXT,
        created_at TEXT,
        updated_at TEXT,
        created_by TEXT
    );
    CREATE TABLE IF NOT EXISTS activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        deal_id INTEGER,
        action TEXT,
        field_changed TEXT,
        old_value TEXT,
        new_value TEXT,
        user_name TEXT,
        timestamp TEXT
    );
    """)
    conn.commit()
    conn.close()

init_db()

# ─── Stage mapping ───────────────────────────────────────────────────────────

STAGE_MAP = {
    "active/verbal": 1,
    "in discussion": 2,
    "on hold": 3,
    "discovery": 4,
    "new lead": 5,
}

def stage_to_num(stage: str) -> int:
    return STAGE_MAP.get(stage.strip().lower(), 5)

# ─── Seed data ────────────────────────────────────────────────────────────────

SEED_DATA = [
  {"name":"JMT Network Services PCL","short":"JMT","sector":"Asset Mgmt","useCase":"Property pin-drop & address validation survey","service":"Survey","stage":"Active/Verbal","stageNum":1,"revenue":62650,"fee":"THB 50/txn","volume":1253,"owner":"K.Biin","notes":"Contract signed THP side; JMT counter-signature pending. 1,253 txns confirmed.","priority":"P1","effort":2,"competitive_risk":"Low","close_date":"2026-07-31","created_by":"system"},
  {"name":"Bangkok Asset Management","short":"BAM","sector":"Asset Mgmt","useCase":"NPA asset survey + data enrichment nationwide","service":"Survey","stage":"In Discussion","stageNum":2,"revenue":400000,"fee":"THB 350-500/txn","volume":900,"owner":"K.Toey","notes":"Senior meeting pending. Key custody process needs resolution. Active competitive landscape.","priority":"P1","effort":4,"competitive_risk":"Medium","close_date":"2026-09-30","created_by":"system"},
  {"name":"Bank of Ayudhya (Krungsri)","short":"BAY","sector":"Banking","useCase":"SME loan doc collect — UC1 manual UC2 on-platform","service":"Survey","stage":"In Discussion","stageNum":2,"revenue":1625000,"fee":"THB 300-350/txn","volume":5000,"owner":"K.Toey","notes":"Demo done 24 Mar. BAY confirmed platform timeline OK. Follow up on BAY discussions. Lock in UC2 scope.","priority":"P1","effort":3,"competitive_risk":"Low","close_date":"2026-09-30","created_by":"system"},
  {"name":"Innozus Healthcare","short":"Innozus","sector":"Healthcare","useCase":"Kitnee kidney test kit distribution + lead gen","service":"Express","stage":"In Discussion","stageNum":2,"revenue":400000,"fee":"GP% >THB100/unit","volume":0,"owner":"K.Toey","notes":"Scope and fee agreed. Pending go-to-market details. Finalise EMS rate by end of June 2026.","priority":"P2","effort":3,"competitive_risk":"Low","close_date":"2026-08-31","created_by":"system"},
  {"name":"Dhipaya Insurance","short":"DHIP","sector":"Insurance","useCase":"Lead generation + household survey","service":"Matching","stage":"On Hold","stageNum":3,"revenue":350000,"fee":"GP% model","volume":0,"owner":"K.Biin","notes":"DHIP wants success-fee model. Blocked until Matching platform is live. Revisit Q4 2026.","priority":"P2","effort":4,"competitive_risk":"Low","close_date":"2026-12-31","created_by":"system"},
  {"name":"Krungthai Card","short":"KTC","sector":"Banking","useCase":"Credit card application collection","service":"Survey","stage":"On Hold","stageNum":3,"revenue":475000,"fee":"THB 190/txn","volume":2500,"owner":"K.Biin","notes":"CRITICAL: 50% volume lost to Pivot.co.th. API integration needed. Propose interim manual ops within 30 days.","priority":"P1","effort":5,"competitive_risk":"High","close_date":"2026-08-31","created_by":"system"},
  {"name":"Muang Thai Insurance","short":"MTI","sector":"Insurance","useCase":"Car inspection with AI-assisted image processing","service":"Survey","stage":"Discovery","stageNum":4,"revenue":300000,"fee":"TBD","volume":0,"owner":"THP Speed","notes":"Platform dependency for car inspection AI. Propose metro pilot phase first.","priority":"P2","effort":4,"competitive_risk":"Medium","close_date":"2026-12-31","created_by":"system"},
  {"name":"National Statistical Office","short":"NSO","sector":"Government","useCase":"Nationwide household census survey","service":"Survey","stage":"Discovery","stageNum":4,"revenue":5000000,"fee":"THB 2-5/txn","volume":2900000,"owner":"K.Toey","notes":"STRATEGIC: THB 5M+ single contract. Govt budget cycle Q3. Exec THP sponsorship needed NOW.","priority":"P1","effort":5,"competitive_risk":"Low","close_date":"2027-03-31","created_by":"system"},
  {"name":"Globlex Securities","short":"Globlex","sector":"Finance","useCase":"KYC document collection + gold reverse logistics","service":"Survey","stage":"Discovery","stageNum":4,"revenue":400000,"fee":"THB 400/txn","volume":1000,"owner":"THP Speed","notes":"Discovery call done. Gold logistics needs insurance partner coordination.","priority":"P2","effort":3,"competitive_risk":"Low","close_date":"2026-11-30","created_by":"system"},
  {"name":"GCAP Pet","short":"GCAP Pet","sector":"Retail","useCase":"Pet shop field survey + product sampling","service":"Survey","stage":"Discovery","stageNum":4,"revenue":350000,"fee":"THB 350/txn","volume":1000,"owner":"K.Biin","notes":"SME retail segment. Initial contact made. Proposal not yet sent.","priority":"P3","effort":3,"competitive_risk":"Low","close_date":"2026-12-31","created_by":"system"},
  {"name":"Ministry of Public Health","short":"MOPH","sector":"Government","useCase":"Health Rider Programme — elderly care logistics","service":"Express","stage":"Discovery","stageNum":4,"revenue":500000,"fee":"TBD","volume":0,"owner":"K.Toey","notes":"Health Rider project deck prepared. Strategic govt relationship. Engage via THP channel.","priority":"P1","effort":5,"competitive_risk":"Low","close_date":"2027-06-30","created_by":"system"},
  {"name":"Betagro PCL","short":"Betagro","sector":"Agri/Retail","useCase":"Animal feed outlet survey + database update","service":"Survey","stage":"Discovery","stageNum":4,"revenue":450000,"fee":"THB 450/txn","volume":1000,"owner":"THP Speed","notes":"Uses proven BAM/JMT survey model. Issue formal proposal using standard template.","priority":"P2","effort":3,"competitive_risk":"Low","close_date":"2026-10-31","created_by":"system"},
  {"name":"CJ Express Group","short":"CJ Express","sector":"Retail","useCase":"Last-mile home delivery expansion","service":"Express","stage":"Discovery","stageNum":4,"revenue":350000,"fee":"TBD per drop","volume":0,"owner":"Internal","notes":"Retail delivery. Leverage THP network density. Proposal needed.","priority":"P2","effort":3,"competitive_risk":"Medium","close_date":"2026-12-31","created_by":"system"},
  {"name":"Central Watson","short":"Watson","sector":"Retail","useCase":"Health & beauty product home delivery","service":"Express","stage":"Discovery","stageNum":4,"revenue":320000,"fee":"TBD per drop","volume":0,"owner":"Internal","notes":"Central Group subsidiary. Premium delivery positioning. No contact yet.","priority":"P2","effort":3,"competitive_risk":"Medium","close_date":"2026-12-31","created_by":"system"},
  {"name":"Buzzebees","short":"Buzzebees","sector":"Commerce","useCase":"Loyalty programme distribution field ops","service":"Matching","stage":"Discovery","stageNum":4,"revenue":300000,"fee":"TBD","volume":0,"owner":"Internal","notes":"B2B commerce. Needs matching platform to activate. Low urgency.","priority":"P3","effort":3,"competitive_risk":"Low","close_date":"2027-03-31","created_by":"system"},
  {"name":"Monomax","short":"Monomax","sector":"Media","useCase":"Content/media field activation campaigns","service":"Matching","stage":"Discovery","stageNum":4,"revenue":350000,"fee":"TBD","volume":0,"owner":"Internal","notes":"Streaming media player distribution. Niche segment. Explore post-platform.","priority":"P3","effort":3,"competitive_risk":"Low","close_date":"2027-03-31","created_by":"system"},
  {"name":"Thai Rung Union Car","short":"Thairung","sector":"Auto","useCase":"Field data collection + asset survey","service":"Survey","stage":"Discovery","stageNum":4,"revenue":300000,"fee":"TBD","volume":0,"owner":"THP Speed","notes":"Auto sector — link to Krungsri Auto pipeline. Proposal pending.","priority":"P3","effort":3,"competitive_risk":"Low","close_date":"2026-12-31","created_by":"system"},
  {"name":"Mega Wiz (Sleep Test)","short":"Mega Wiz","sector":"Healthcare","useCase":"Sleep device logistics + lead generation","service":"Express","stage":"New Lead","stageNum":5,"revenue":400000,"fee":"TBD","volume":0,"owner":"K.Biin","notes":"Healthcare device logistics. First contact not made. Assign owner.","priority":"P2","effort":2,"competitive_risk":"Low","close_date":"2027-03-31","created_by":"system"},
  {"name":"Central Department Store","short":"Central","sector":"Retail","useCase":"Premium home delivery — high-value goods","service":"Express","stage":"New Lead","stageNum":5,"revenue":450000,"fee":"TBD per drop","volume":0,"owner":"THP refer","notes":"Top-tier retail. High brand alignment. Initial outreach needed.","priority":"P2","effort":3,"competitive_risk":"Medium","close_date":"2027-06-30","created_by":"system"},
  {"name":"SAM (Sukhumvit Asset Mgmt)","short":"SAM","sector":"Asset Mgmt","useCase":"NPA asset survey — BAM model replication","service":"Survey","stage":"New Lead","stageNum":5,"revenue":480000,"fee":"THB 350-500/txn","volume":1000,"owner":"THP refer","notes":"Direct BAM case study replication. Fast-track using same proposal template.","priority":"P1","effort":2,"competitive_risk":"Low","close_date":"2026-10-31","created_by":"system"},
  {"name":"Thai Beverage PCL","short":"Thai Bev","sector":"FMCG","useCase":"Nationwide outlet survey — 300K transactions potential","service":"Survey","stage":"New Lead","stageNum":5,"revenue":25000000,"fee":"THB 70-100/txn","volume":300000,"owner":"Internal","notes":"MEGA DEAL: 300K txns x THB 70-100 = THB 21-30M. Dedicated account manager needed. Highest-upside single account.","priority":"P1","effort":4,"competitive_risk":"Medium","close_date":"2027-06-30","created_by":"system"},
  {"name":"Srisawad Corporation","short":"Srisawad","sector":"Finance","useCase":"Asset survey re-engagement (65K txns done previously)","service":"Survey","stage":"New Lead","stageNum":5,"revenue":300000,"fee":"THB 50/txn","volume":6000,"owner":"THP Speed","notes":"Previous operations completed successfully. Re-engage with new volume.","priority":"P2","effort":2,"competitive_risk":"Low","close_date":"2026-10-31","created_by":"system"},
  {"name":"CJ MORE Convenience","short":"CJ MORE","sector":"Retail","useCase":"Convenience store field activation","service":"Matching","stage":"New Lead","stageNum":5,"revenue":320000,"fee":"TBD","volume":0,"owner":"Internal","notes":"CJ Group convenience chain. Matching service required. Post-platform.","priority":"P3","effort":3,"competitive_risk":"Low","close_date":"2027-06-30","created_by":"system"},
  {"name":"TOPS Market","short":"TOPS","sector":"Food Retail","useCase":"Same-day grocery home delivery","service":"Express","stage":"New Lead","stageNum":5,"revenue":350000,"fee":"TBD per drop","volume":0,"owner":"THP refer","notes":"Central Group food retail. Grocery delivery. Pitch THP network density advantage.","priority":"P2","effort":3,"competitive_risk":"Medium","close_date":"2027-06-30","created_by":"system"},
  {"name":"Krungsri Auto","short":"Krungsri Auto","sector":"Auto Finance","useCase":"Vehicle asset survey + inspection","service":"Survey","stage":"New Lead","stageNum":5,"revenue":350000,"fee":"THB 300-400/txn","volume":1000,"owner":"THP refer","notes":"Link to BAY relationship. Leverage Krungsri group connection.","priority":"P2","effort":2,"competitive_risk":"Low","close_date":"2026-12-31","created_by":"system"},
  {"name":"OyaKouKou","short":"OyaKouKou","sector":"Commerce","useCase":"GP% partnership model","service":"Matching","stage":"New Lead","stageNum":5,"revenue":300000,"fee":"GP%","volume":0,"owner":"Internal","notes":"E-commerce partnership. Matching service. Explore post-platform.","priority":"P3","effort":3,"competitive_risk":"Low","close_date":"2027-06-30","created_by":"system"},
  {"name":"PWA / กปภ. Water Authority","short":"PWA","sector":"Gov Utility","useCase":"Water meter reading via OCR + rider network","service":"Survey","stage":"New Lead","stageNum":5,"revenue":33000000,"fee":"THB 15/meter","volume":2200000,"owner":"THP Speed","notes":"STRATEGIC GOVT: 2.2M meters x THB 15 = THB 33M/mo potential. Long procurement cycle. THP govt team to lead.","priority":"P1","effort":5,"competitive_risk":"Low","close_date":"2027-12-31","created_by":"system"},
]

# ─── Models ───────────────────────────────────────────────────────────────────

class DealCreate(BaseModel):
    name: str
    short: Optional[str] = None
    sector: Optional[str] = None
    useCase: Optional[str] = None
    service: Optional[str] = None
    stage: Optional[str] = None
    stageNum: Optional[int] = None
    revenue: Optional[float] = None
    fee: Optional[str] = None
    volume: Optional[int] = None
    owner: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[str] = None
    effort: Optional[int] = None
    competitive_risk: Optional[str] = None
    close_date: Optional[str] = None
    created_by: Optional[str] = None

class DealUpdate(BaseModel):
    name: Optional[str] = None
    short: Optional[str] = None
    sector: Optional[str] = None
    useCase: Optional[str] = None
    service: Optional[str] = None
    stage: Optional[str] = None
    stageNum: Optional[int] = None
    revenue: Optional[float] = None
    fee: Optional[str] = None
    volume: Optional[int] = None
    owner: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[str] = None
    effort: Optional[int] = None
    competitive_risk: Optional[str] = None
    close_date: Optional[str] = None
    created_by: Optional[str] = None

# ─── Helpers ──────────────────────────────────────────────────────────────────

def row_to_dict(row):
    return dict(row) if row else None

def now_iso():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def log_activity(conn, deal_id, action, field_changed, old_value, new_value, user_name):
    conn.execute(
        "INSERT INTO activities (deal_id, action, field_changed, old_value, new_value, user_name, timestamp) VALUES (?,?,?,?,?,?,?)",
        (deal_id, action, field_changed, str(old_value) if old_value is not None else None,
         str(new_value) if new_value is not None else None, user_name, now_iso())
    )

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
def serve_index():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/api/deals")
def list_deals():
    conn = get_db()
    rows = conn.execute("SELECT * FROM deals ORDER BY stageNum, revenue DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/deals/{deal_id}")
def get_deal(deal_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Deal not found")
    return dict(row)

@app.post("/api/deals")
def create_deal(deal: DealCreate, request: Request):
    conn = get_db()
    now = now_iso()
    stage = deal.stage or "New Lead"
    stage_num = deal.stageNum if deal.stageNum else stage_to_num(stage)
    conn.execute(
        """INSERT INTO deals (name,short,sector,useCase,service,stage,stageNum,revenue,fee,volume,
           owner,notes,priority,effort,competitive_risk,close_date,created_at,updated_at,created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (deal.name, deal.short, deal.sector, deal.useCase, deal.service, stage, stage_num,
         deal.revenue, deal.fee, deal.volume, deal.owner, deal.notes, deal.priority,
         deal.effort, deal.competitive_risk, deal.close_date, now, now, deal.created_by)
    )
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    log_activity(conn, new_id, "created", None, None, deal.name, deal.created_by or "unknown")
    conn.commit()
    row = conn.execute("SELECT * FROM deals WHERE id=?", (new_id,)).fetchone()
    conn.close()
    return dict(row)

@app.put("/api/deals/{deal_id}")
def update_deal(deal_id: int, deal: DealUpdate, user: str = Query(default="unknown")):
    conn = get_db()
    existing = conn.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "Deal not found")
    old = dict(existing)
    updates = {k: v for k, v in deal.model_dump().items() if v is not None}
    if "stage" in updates and "stageNum" not in updates:
        updates["stageNum"] = stage_to_num(updates["stage"])
    updates["updated_at"] = now_iso()
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [deal_id]
    conn.execute(f"UPDATE deals SET {set_clause} WHERE id=?", values)
    for field, new_val in updates.items():
        if field == "updated_at":
            continue
        if str(old.get(field)) != str(new_val):
            log_activity(conn, deal_id, "updated", field, old.get(field), new_val, user)
    conn.commit()
    row = conn.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    conn.close()
    return dict(row)

@app.delete("/api/deals/{deal_id}")
def delete_deal(deal_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Deal not found")
    conn.execute("DELETE FROM deals WHERE id=?", (deal_id,))
    conn.execute("DELETE FROM activities WHERE deal_id=?", (deal_id,))
    conn.commit()
    conn.close()
    return {"deleted": deal_id}

@app.post("/api/seed")
def seed_deals(force: bool = Query(default=False)):
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
    if count > 0 and not force:
        conn.close()
        return {"message": "Already seeded", "count": count}
    if force:
        conn.execute("DELETE FROM deals")
        conn.execute("DELETE FROM activities")
    now = now_iso()
    inserted = 0
    for d in SEED_DATA:
        conn.execute(
            """INSERT INTO deals (name,short,sector,useCase,service,stage,stageNum,revenue,fee,volume,
               owner,notes,priority,effort,competitive_risk,close_date,created_at,updated_at,created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d["name"], d.get("short"), d.get("sector"), d.get("useCase"), d.get("service"),
             d.get("stage"), d.get("stageNum"), d.get("revenue"), d.get("fee"), d.get("volume"),
             d.get("owner"), d.get("notes"), d.get("priority"), d.get("effort"),
             d.get("competitive_risk"), d.get("close_date"), now, now, d.get("created_by","system"))
        )
        inserted += 1
    conn.commit()
    conn.close()
    return {"message": "Seeded", "inserted": inserted}

@app.post("/api/import/csv")
async def import_csv(file: UploadFile = File(...)):
    content = await file.read()
    filename = file.filename or ""
    errors = []
    imported = 0

    FIELDS = ["name","short","sector","useCase","service","stage","revenue","fee","volume",
              "owner","notes","priority","effort","competitive_risk","close_date","created_by"]

    rows_data = []

    if filename.lower().endswith(".xlsx"):
        try:
            import openpyxl
            from io import BytesIO
            wb = openpyxl.load_workbook(BytesIO(content))
            ws = wb.active
            headers = None
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i == 0:
                    headers = [str(h).strip().lower() if h else "" for h in row]
                    continue
                if all(v is None for v in row):
                    continue
                row_dict = {}
                for j, h in enumerate(headers):
                    val = row[j] if j < len(row) else None
                    row_dict[h] = str(val).strip() if val is not None else ""
                rows_data.append(row_dict)
        except Exception as e:
            return JSONResponse({"error": f"Excel parse error: {e}"}, status_code=400)
    else:
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            if row.get("name","").startswith("#"):
                continue
            rows_data.append({k.strip().lower(): v.strip() for k, v in row.items()})

    conn = get_db()
    now = now_iso()
    for i, row in enumerate(rows_data):
        name = row.get("name","").strip()
        if not name or name.startswith("#"):
            continue
        try:
            revenue_raw = row.get("revenue","0") or "0"
            revenue_raw = revenue_raw.replace(",","").replace("THB","").strip()
            revenue = float(revenue_raw) if revenue_raw else 0.0
        except:
            revenue = 0.0
        try:
            volume_raw = row.get("volume","0") or "0"
            volume = int(str(volume_raw).replace(",","").strip()) if volume_raw else 0
        except:
            volume = 0
        try:
            effort = max(1, min(5, int(row.get("effort","3") or "3")))
        except:
            effort = 3
        stage = row.get("stage","New Lead") or "New Lead"
        stage_num = stage_to_num(stage)

        existing = conn.execute("SELECT id FROM deals WHERE name=?", (name,)).fetchone()
        try:
            if existing:
                deal_id = existing[0]
                conn.execute(
                    """UPDATE deals SET short=?,sector=?,useCase=?,service=?,stage=?,stageNum=?,
                       revenue=?,fee=?,volume=?,owner=?,notes=?,priority=?,effort=?,
                       competitive_risk=?,close_date=?,updated_at=?,created_by=? WHERE id=?""",
                    (row.get("short"), row.get("sector"), row.get("useCase"),
                     row.get("service"), stage, stage_num, revenue, row.get("fee"),
                     volume, row.get("owner"), row.get("notes"), row.get("priority"),
                     effort, row.get("competitive_risk"), row.get("close_date"), now,
                     row.get("created_by"), deal_id)
                )
                log_activity(conn, deal_id, "updated", "csv_import", None, name, row.get("created_by","import"))
            else:
                conn.execute(
                    """INSERT INTO deals (name,short,sector,useCase,service,stage,stageNum,revenue,fee,
                       volume,owner,notes,priority,effort,competitive_risk,close_date,created_at,updated_at,created_by)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (name, row.get("short"), row.get("sector"), row.get("useCase"),
                     row.get("service"), stage, stage_num, revenue, row.get("fee"),
                     volume, row.get("owner"), row.get("notes"), row.get("priority"),
                     effort, row.get("competitive_risk"), row.get("close_date"), now, now,
                     row.get("created_by","import"))
                )
                new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                log_activity(conn, new_id, "created", "csv_import", None, name, row.get("created_by","import"))
            imported += 1
        except Exception as e:
            errors.append(f"Row {i+2} ({name}): {e}")

    conn.commit()
    conn.close()
    return {"imported": imported, "errors": errors}

@app.get("/api/export/csv")
def export_csv():
    conn = get_db()
    rows = conn.execute("SELECT * FROM deals ORDER BY stageNum, revenue DESC").fetchall()
    conn.close()
    output = io.StringIO()
    if rows:
        fieldnames = list(dict(rows[0]).keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=PMC_Pipeline_Export.csv"}
    )

@app.get("/api/export/json")
def export_json():
    conn = get_db()
    rows = conn.execute("SELECT * FROM deals ORDER BY stageNum, revenue DESC").fetchall()
    conn.close()
    data = [dict(r) for r in rows]
    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=PMC_Pipeline_Export.json"}
    )

@app.get("/api/template/csv")
def download_template():
    template_path = TEMPLATE_DIR / "PMC_Pipeline_Template.csv"
    return FileResponse(template_path, filename="PMC_Pipeline_Template.csv", media_type="text/csv")

@app.get("/api/activities/{deal_id}")
def get_activities(deal_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM activities WHERE deal_id=? ORDER BY timestamp DESC", (deal_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/stats")
def get_stats():
    conn = get_db()
    rows = conn.execute("SELECT * FROM deals").fetchall()
    conn.close()
    deals = [dict(r) for r in rows]
    total_pipeline = sum(d.get("revenue") or 0 for d in deals)
    active_deals = sum(1 for d in deals if d.get("stageNum") in (1, 2))
    p1_count = sum(1 for d in deals if d.get("priority") == "P1")
    top_deal = max(deals, key=lambda d: d.get("revenue") or 0, default=None)
    services = len(set(d.get("service") for d in deals if d.get("service")))
    survey_pipeline = sum(d.get("revenue") or 0 for d in deals if d.get("service") == "Survey")
    survey_target_2026 = 12_000_000
    stage_breakdown = {}
    for d in deals:
        s = d.get("stage","Unknown")
        if s not in stage_breakdown:
            stage_breakdown[s] = {"count": 0, "revenue": 0}
        stage_breakdown[s]["count"] += 1
        stage_breakdown[s]["revenue"] += d.get("revenue") or 0
    return {
        "total_pipeline": total_pipeline,
        "active_deals": active_deals,
        "p1_count": p1_count,
        "top_deal": {"name": top_deal["name"], "revenue": top_deal["revenue"]} if top_deal else None,
        "services_count": services,
        "survey_gap": survey_target_2026 - survey_pipeline,
        "survey_pipeline": survey_pipeline,
        "deal_count": len(deals),
        "stage_breakdown": stage_breakdown,
    }

# ─── Auth endpoints ───────────────────────────────────────────────────────────

@app.post("/api/login")
async def login(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"success": False, "message": "Invalid request"}, status_code=400)
    email = data.get("username", "").strip().lower()
    password = data.get("password", "")
    user = USERS.get(email)
    if user and password == user["password"]:
        token = secrets.token_urlsafe(32)
        _sessions[token] = {
            "expires_at": datetime.now() + timedelta(hours=SESSION_DURATION_HOURS),
            "email": email,
            "name": user["name"],
        }
        resp = JSONResponse({"success": True, "name": user["name"]})
        resp.set_cookie(
            key="pmc_session",
            value=token,
            httponly=True,
            max_age=SESSION_DURATION_HOURS * 3600,
            samesite="lax",
        )
        return resp
    return JSONResponse({"success": False, "message": "Invalid username or password"}, status_code=401)

@app.post("/api/logout")
async def logout(request: Request):
    token = request.cookies.get("pmc_session")
    if token and token in _sessions:
        del _sessions[token]
    resp = JSONResponse({"success": True})
    resp.delete_cookie("pmc_session")
    return resp

@app.get("/api/me")
async def me(request: Request):
    session = _valid_session(request)
    if session:
        return {"authenticated": True, "email": session["email"], "name": session["name"]}
    return JSONResponse({"authenticated": False}, status_code=401)

# ─── Static files (must be after all routes) ──────────────────────────────────
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
