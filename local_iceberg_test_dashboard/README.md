# Iceberg Test Dashboard

A Dash-based test dashboard for the Iceberg Trading Platform API.

---

## Purpose

This dashboard provides a testing interface for:
- API endpoint testing and validation
- Real-time data visualization (WebSocket/SSE)
- Admin operations testing
- Bootstrap data inspection

---

## Documentation

**All documentation for this project stays within this folder:**
- `FRONTEND_INTEGRATION_GUIDE.md` - **Complete API reference for Next.js frontend engineers**
- `fix_plan/` - Fix planning and implementation tracking
- `QA_VALIDATION_REPORT.md` - QA validation results

**Do NOT use these directories for test dashboard documentation:**
- `iceberg_ai_context/` - Reserved for `lean_iceberg/` only
- `iceberg_ai_exploration/` - Reserved for `lean_iceberg/` only
- `iceberg_fix_plan/` - Reserved for `lean_iceberg/` only

---

## Running the Dashboard

```bash
cd local_iceberg_test_dashboard
python -m src.app
```

Then open http://localhost:8050 in your browser.

---

## Configuration

Copy `.env.example` to `.env` and configure:
- `ICEBERG_API_URL` - API base URL (default: https://api.botbro.trade)
- `GOOGLE_CLIENT_ID` - Google OAuth client ID

---

## Project Structure

```
local_iceberg_test_dashboard/
├── src/
│   ├── app.py              # Main Dash application
│   ├── api_client.py       # REST API client
│   ├── sse_client.py       # SSE streaming client
│   ├── ws_client.py        # WebSocket client
│   ├── state_manager.py    # Thread-safe state container
│   ├── layouts.py          # UI layout components
│   ├── charts.py           # Plotly chart components
│   ├── models.py           # Data models
│   ├── admin_page.py       # Admin page
│   ├── advanced_page.py    # Advanced page (ADR treemap)
│   └── debugging_page.py   # Debugging page
├── assets/
│   └── custom.css          # Custom styles
├── fix_plan/               # Fix documentation (stays here!)
├── tests/                  # Test files
└── .env.example            # Environment template
```
