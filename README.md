# Benefits Decision Scaffold API

FastAPI service for multi-tenant benefits eligibility decision mapping.

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in Supabase credentials
3. Run: `uvicorn main:app --reload`

## Endpoints

- `POST /runs` - Create eligibility run
- `GET /orgs/{org_id}/runs` - Get org runs
- `GET /health` - Health check
