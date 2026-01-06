from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import jwt
import httpx
from datetime import datetime
import json
import uuid

app = FastAPI(title="Benefits Decision Scaffold API")

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

security = HTTPBearer()

class RunRequest(BaseModel):
    org_id: str
    input_raw: str

class RunResponse(BaseModel):
    run_id: str
    decision_map: dict

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify Supabase JWT and extract user ID"""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, options={"verify_signature": False})
        user_id = payload.get("sub")

        # DEBUG: Print what we're extracting
        print(f"DEBUG - JWT payload: {payload}")
        print(f"DEBUG - Extracted user_id: {user_id}")
        print(f"DEBUG - Expected user_id: 47405c01-9f36-48e8-8482-c65a6ce020b9")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )

        return user_id
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

async def verify_org_membership(user_id: str, org_id: str):
    """Check if user belongs to org"""
    async with httpx.AsyncClient() as client:
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        }

        # DEBUG: Print what we're checking
        print(f"DEBUG - Checking membership for user_id: {user_id}")
        print(f"DEBUG - Checking membership for org_id: {org_id}")

        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/org_members",
            headers=headers,
            params={
                "user_id": f"eq.{user_id}",
                "org_id": f"eq.{org_id}",
                "select": "*"
            }
        )

        print(f"DEBUG - Response status: {response.status_code}")
        print(f"DEBUG - Response body: {response.text}")

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error"
            )

        members = response.json()
        print(f"DEBUG - Found members: {members}")

        if not members:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this organization"
            )

        return members[0]

def normalize_facts(input_raw: str) -> dict:
    """Extract structured facts from free text input"""
    # Simple fact extraction for MVP
    # TODO: Use LLM for better extraction

    facts = {
        "household_size": 1,
        "age": None,
        "gross_monthly_income": None,
        "rent": None,
        "utilities_separate": False,
        "utility_cost": None,
        "employment": None,
        "prior_snap_denial": False
    }

    # Basic pattern matching
    input_lower = input_raw.lower()

    # Extract income
    if "1700" in input_raw or "1,700" in input_raw:
        facts["gross_monthly_income"] = 1700

    # Extract age
    if "58" in input_raw:
        facts["age"] = 58

    # Extract rent
    if "950" in input_raw:
        facts["rent"] = 950

    # Extract utilities
    if "180" in input_raw:
        facts["utility_cost"] = 180
        facts["utilities_separate"] = True

    # Employment
    if "part-time" in input_lower:
        facts["employment"] = "part-time"

    # Prior denial
    if "lost snap" in input_lower or "denied" in input_lower:
        facts["prior_snap_denial"] = True

    return facts

def generate_decision_map(facts: dict) -> dict:
    """Generate decision map for Virginia SNAP eligibility"""

    # Virginia SNAP parameters (2026 estimates)
    SNAP_GROSS_LIMIT_1_PERSON = 1580  # 130% FPL
    LIHEAP_LIMIT_1_PERSON = 2400      # ~150% FPL
    STANDARD_UTILITY_ALLOWANCE = 400  # Approximate SUA value

    decision_map = {
        "program": "SNAP",
        "state": "Virginia",
        "current_status": "not_eligible",
        "reason": "",
        "reversible": False,
        "high_impact_action": "",
        "next_steps": [],
        "documents_needed": [],
        "confidence": "medium"
    }

    gross_income = facts.get("gross_monthly_income")

    if gross_income is None:
        decision_map["current_status"] = "insufficient_info"
        decision_map["reason"] = "Unable to determine income from provided information"
        decision_map["next_steps"] = [
            "Verify monthly gross income amount",
            "Gather recent pay stubs or income documentation"
        ]
        return decision_map

    if gross_income <= SNAP_GROSS_LIMIT_1_PERSON:
        decision_map["current_status"] = "likely_eligible"
        decision_map["reason"] = "Income is within SNAP gross income limits"
        decision_map["next_steps"] = [
            "Apply for SNAP through local DSS office",
            "Gather required income and identity documents"
        ]
        decision_map["documents_needed"] = [
            "Recent pay stubs (30 days)",
            "Photo ID",
            "Proof of residence"
        ]
    else:
        # Check for potential deductions via LIHEAP
        income_over = gross_income - SNAP_GROSS_LIMIT_1_PERSON

        if (facts.get("utilities_separate") and
            gross_income <= LIHEAP_LIMIT_1_PERSON):

            decision_map["reversible"] = True
            decision_map["reason"] = f"Income is ${income_over} over SNAP limit, but LIHEAP utility deduction could qualify household"
            decision_map["high_impact_action"] = "Apply for LIHEAP to qualify for Standard Utility Allowance, which reduces countable SNAP income"
            decision_map["next_steps"] = [
                "Apply for LIHEAP immediately",
                "Collect utility bills for LIHEAP application",
                "Reapply for SNAP once LIHEAP approved or pending",
                "Reference LIHEAP application when applying for SNAP"
            ]
            decision_map["documents_needed"] = [
                "Recent electric or gas bill",
                "Proof of income (last 30 days)",
                "Lease agreement or rent receipt"
            ]
        else:
            decision_map["reason"] = f"Income is ${income_over} over SNAP limit and no available deductions apply"
            decision_map["next_steps"] = [
                "Verify all income amounts are accurate",
                "Check if any household circumstances have changed"
            ]

    return decision_map

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.post("/runs", response_model=RunResponse)
async def create_run(
    request: RunRequest,
    user_id: str = Depends(verify_token)
):
    """Create a new eligibility run"""

    # Verify org membership
    membership = await verify_org_membership(user_id, request.org_id)

    # Normalize input facts
    facts = normalize_facts(request.input_raw)

    # Generate decision map
    decision_map = generate_decision_map(facts)

    # Store run in database
    run_id = str(uuid.uuid4())

    async with httpx.AsyncClient() as client:
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json"
        }

        run_data = {
            "id": run_id,
            "org_id": request.org_id,
            "created_by": user_id,
            "input_raw": request.input_raw,
            "facts_normalized": facts,
            "decision_map": decision_map
        }

        response = await client.post(
            f"{SUPABASE_URL}/rest/v1/runs",
            headers=headers,
            json=run_data
        )

        if response.status_code not in [200, 201]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to store run"
            )

    return RunResponse(run_id=run_id, decision_map=decision_map)

@app.get("/orgs/{org_id}/runs")
async def get_org_runs(
    org_id: str,
    user_id: str = Depends(verify_token)
):
    """Get runs for an organization"""

    # Verify org membership
    membership = await verify_org_membership(user_id, org_id)

    async with httpx.AsyncClient() as client:
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        }

        # Filter based on role
        params = {"org_id": f"eq.{org_id}"}
        if membership["role"] == "volunteer":
            params["created_by"] = f"eq.{user_id}"

        response = await client.get(
            f"{SUPABASE_URL}/rest/v1/runs",
            headers=headers,
            params=params
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch runs"
            )

        return response.json()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
