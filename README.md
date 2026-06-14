# Postman Cloud — Sales Pipeline Tool

A multi-user sales pipeline management tool for the Postman Cloud sales team.
Built with FastAPI + SQLite + Chart.js. No external database required.

---

## Quick Start

```bash
cd PMC-SalesTool
pip install -r requirements.txt
python app.py
```

Then open: **http://localhost:8000**

The app auto-seeds 27 deals on first launch. No setup needed.

---

## Sharing with Your Team (Same Network)

Find your machine's local IP:
- **Mac:** `ifconfig | grep "inet "` → look for 192.168.x.x
- **Windows:** `ipconfig` → look for IPv4 Address

Share the URL: `http://192.168.x.x:8000`

Team members open this in their browser. Each person sets their name in the top bar — saved locally. No login system required.

---

## Cloud Deployment (Render.com Free Tier)

1. Push this folder to a GitHub repo
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect your GitHub repo
4. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python app.py`
   - **Environment:** Python 3.11
5. Click Deploy
6. Your team URL will be: `https://your-app.onrender.com`

Note: Render free tier spins down after 15 min of inactivity. First load may take 30 seconds.

---

## Data Backup & Restore

**Backup:** Reports tab → "Export Full JSON" — saves all deals to a JSON file.

**Restore on new server:**
1. Go to Reports tab → Import JSON section
2. Paste your JSON backup and click Import
   — OR —
3. Copy `pipeline.db` file directly to new server

---

## Importing Deals (CSV / Excel)

1. Pipeline tab → click **⬆ Import** button
2. Click **⬇ Download Template CSV**
3. Fill in your deals in Excel (save as .xlsx or .csv)
4. Upload the file in the Import dialog
5. Click **Import N Rows**

Existing deals with the same Client Name will be updated (upsert). New names are added.

**Valid field values:**
- `service`: Survey | Express | Matching | Value-Added | Commerce
- `stage`: Active/Verbal | In Discussion | On Hold | Discovery | New Lead
- `priority`: P1 | P2 | P3
- `effort`: 1–5 (1=Easy, 5=Hard)
- `competitive_risk`: Low | Medium | High

---

## Adding Team Members

No admin setup needed:
1. Each person opens the app URL in their browser
2. Type their name in the "Your name" field (top right of every page)
3. Their name is saved in localStorage — appears on all records they create/edit

---

## Features

| Tab | Description |
|-----|-------------|
| Dashboard | KPI cards, funnel chart, revenue by service/sector, top 5 accounts |
| Pipeline | Full deal table, sort/filter, create/edit/delete deals, import CSV/Excel |
| Clients | 10 pivot analysis views + client card grid |
| Services | Service summary, 5-year target tracking, accordion deal lists |
| Reports | Auto-generated ExCom summary, export CSV/JSON, data reset |

---

## File Structure

```
PMC-SalesTool/
├── app.py              # FastAPI backend (SQLite database)
├── requirements.txt    # Python dependencies
├── pipeline.db         # Auto-created SQLite database (gitignore this)
├── static/
│   └── index.html      # Full SPA frontend (all JS inline)
├── template/
│   └── PMC_Pipeline_Template.csv
└── README.md
```

---

## Tech Stack

- **Backend:** Python FastAPI + SQLite (no PostgreSQL needed)
- **Frontend:** Vanilla JS SPA, Chart.js 4.4.1
- **No framework:** Zero npm, zero webpack — just open the URL
- **Offline capable:** Runs on any laptop, no internet required after install

---

Built for Capital8 Consortium · Postman Cloud · 2026
