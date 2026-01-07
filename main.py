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
import re

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
    """Comprehensive fact extraction based on actual intake form patterns"""

    print(f"DEBUG - Raw input: {input_raw}")

    facts = {
        # HOUSEHOLD COMPOSITION
        "household_size": 1,
        "household_members": [],
        "living_situation": None,

        # INCOME SOURCES
        "income_sources": [],
        "total_monthly_income": None,
        "gross_monthly_income": None,  # Keep for backward compatibility

        # DEMOGRAPHICS
        "ages": [],
        "elderly_in_household": False,
        "disabled_in_household": False,

        # EMPLOYMENT
        "employment_status": None,
        "work_hours": None,

        # HOUSING
        "housing_type": None,
        "rent": None,
        "utilities_separate": False,
        "utility_cost": None,

        # SPECIAL CIRCUMSTANCES
        "circumstances": [],
        "prior_snap_denial": False,

        # EXTRACTION INFO
        "patterns_matched": [],
        "missing_critical_info": []
    }

    input_lower = input_raw.lower()

    # 1. HOUSEHOLD SIZE PATTERNS
    household_patterns = [
        (r'(\d+)\s*person\s*household', 'household_count'),
        (r'family\s*of\s*(\d+)', 'family_count'),
        (r'couple|married|husband|wife|spouse', 'couple'),
        (r'(\d+)\s*child(?:ren)?', 'children'),
        (r'single\s*(?:adult|mother|father|person)', 'single'),
        (r'living\s*with\s*(\d+)\s*(?:other\s*)?people', 'living_with')
    ]

    for pattern, pattern_type in household_patterns:
        match = re.search(pattern, input_lower)
        if match:
            if pattern_type == 'household_count':
                facts["household_size"] = int(match.group(1))
            elif pattern_type == 'family_count':
                facts["household_size"] = int(match.group(1))
            elif pattern_type == 'couple':
                facts["household_size"] = max(facts["household_size"], 2)
            elif pattern_type == 'children':
                num_children = int(match.group(1))
                facts["household_size"] = max(facts["household_size"], num_children + 1)
            elif pattern_type == 'single':
                facts["household_size"] = 1
            elif pattern_type == 'living_with':
                facts["household_size"] = int(match.group(1)) + 1
            facts["patterns_matched"].append(f"household: {pattern}")
            print(f"DEBUG - Household pattern matched: {pattern} -> size={facts['household_size']}")

    # 2. INCOME SOURCE PATTERNS (comprehensive)
    income_patterns = [
        # Employment income with dollar sign
        (r'makes?\s*(?:around\s*)?\$([0-9,]+)', 'employment'),
        (r'earning\s*\$([0-9,]+)', 'employment'),
        (r'\$([0-9,]+)\s*(?:a|per)\s*month', 'employment'),
        (r'\$([0-9,]+)\s*monthly', 'employment'),
        (r'\$([0-9,]+)\s*(?:before|gross)', 'employment'),

        # Government benefits
        (r'unemployment\s*(?:of\s*)?\$([0-9,]+)', 'unemployment'),
        (r'social\s*security\s*(?:of\s*)?\$([0-9,]+)', 'social_security'),
        (r'(?:ssi|ssdi|disability)\s*(?:of\s*)?\$([0-9,]+)', 'disability'),
        (r'pension\s*(?:of\s*)?\$([0-9,]+)', 'pension'),

        # Other income
        (r'child\s*support\s*(?:of\s*)?\$([0-9,]+)', 'child_support'),
        (r'alimony\s*(?:of\s*)?\$([0-9,]+)', 'alimony'),
    ]

    total_income = 0
    for pattern, income_type in income_patterns:
        match = re.search(pattern, input_lower)
        if match:
            try:
                amount = int(match.group(1).replace(",", ""))
                facts["income_sources"].append({
                    "type": income_type,
                    "amount": amount,
                    "frequency": "monthly"
                })
                total_income += amount
                facts["patterns_matched"].append(f"income: {pattern} -> ${amount}")
                print(f"DEBUG - Income pattern matched: {income_type} = ${amount}")
            except (ValueError, IndexError):
                continue

    if total_income > 0:
        facts["total_monthly_income"] = total_income
        facts["gross_monthly_income"] = total_income  # Backward compatibility
    else:
        facts["missing_critical_info"].append("income")
        print("DEBUG - No income pattern matched")

    # 3. AGE PATTERNS
    age_patterns = [
        (r'(\d+)\s*years?\s*old', 'age'),
        (r'age[sd]?\s*(\d+)', 'age'),
        (r'elderly|senior', 'elderly'),
        (r'retired', 'retired'),
    ]

    for pattern, pattern_type in age_patterns:
        match = re.search(pattern, input_lower)
        if match:
            if pattern_type == 'age':
                age = int(match.group(1))
                facts["ages"].append(age)
                if age >= 60:
                    facts["elderly_in_household"] = True
                facts["patterns_matched"].append(f"age: {age}")
                print(f"DEBUG - Age pattern matched: {age}")
            elif pattern_type in ['elderly', 'retired']:
                facts["elderly_in_household"] = True
                facts["patterns_matched"].append(f"age: {pattern_type}")

    # 4. HOUSING PATTERNS
    housing_patterns = [
        (r'rent\s*(?:is\s*)?\$([0-9,]+)', 'rent_amount'),
        (r'\$([0-9,]+)\s*(?:for\s*)?rent', 'rent_amount'),
        (r'mortgage\s*(?:is\s*)?\$([0-9,]+)', 'mortgage_amount'),
        (r'owns?\s*(?:a\s*)?(?:home|house|condo)', 'own'),
        (r'lives?\s*with\s*(?:family|friend|parent)', 'shared'),
        (r'homeless|no\s*permanent\s*address', 'homeless'),
        (r'section\s*8|housing\s*voucher|subsidized', 'subsidized'),
    ]

    for pattern, pattern_type in housing_patterns:
        match = re.search(pattern, input_lower)
        if match:
            if pattern_type == 'rent_amount':
                facts["rent"] = int(match.group(1).replace(",", ""))
                facts["housing_type"] = "rent"
                print(f"DEBUG - Rent matched: ${facts['rent']}")
            elif pattern_type == 'mortgage_amount':
                facts["rent"] = int(match.group(1).replace(",", ""))
                facts["housing_type"] = "own"
            else:
                facts["housing_type"] = pattern_type
            facts["patterns_matched"].append(f"housing: {pattern}")

    # 5. UTILITY PATTERNS
    utility_patterns = [
        (r'(?:utilities?|electric|gas|heat)\s*(?:is\s*|of\s*|about\s*)?\$([0-9,]+)', 'utility'),
        (r'\$([0-9,]+)\s*(?:for\s*)?(?:utilities?|electric|gas)', 'utility'),
        (r'pays?\s*(?:electric|gas|utilities?)\s*separate', 'separate'),
    ]

    for pattern, pattern_type in utility_patterns:
        match = re.search(pattern, input_lower)
        if match:
            if pattern_type == 'utility':
                facts["utility_cost"] = int(match.group(1).replace(",", ""))
                facts["utilities_separate"] = True
                print(f"DEBUG - Utility cost matched: ${facts['utility_cost']}")
            elif pattern_type == 'separate':
                facts["utilities_separate"] = True
            facts["patterns_matched"].append(f"utility: {pattern}")

    # 6. EMPLOYMENT STATUS
    employment_patterns = [
        (r'part[\s-]*time', 'part-time'),
        (r'full[\s-]*time', 'full-time'),
        (r'unemployed|not\s*working|lost\s*(?:my\s*)?job', 'unemployed'),
        (r'retired', 'retired'),
        (r'disabled|disability', 'disabled'),
        (r'(\d+)\s*hours?\s*(?:a|per)\s*week', 'hours'),
    ]

    for pattern, pattern_type in employment_patterns:
        match = re.search(pattern, input_lower)
        if match:
            if pattern_type == 'hours':
                facts["work_hours"] = int(match.group(1))
            else:
                facts["employment_status"] = pattern_type
            facts["patterns_matched"].append(f"employment: {pattern}")
            print(f"DEBUG - Employment pattern matched: {pattern_type}")

    # 7. SPECIAL CIRCUMSTANCES
    circumstances_patterns = [
        (r'domestic\s*violence|abuse|restraining\s*order', 'domestic_violence'),
        (r'homeless|shelter|living\s*in\s*(?:car|street)', 'homeless'),
        (r'disabled?|disability|impair', 'disabled'),
        (r'laid\s*off|fired|quit|lost\s*(?:my\s*)?job', 'job_loss'),
        (r'medical\s*(?:bills?|expenses?)', 'medical_expenses'),
        (r'lost\s*snap|denied|too\s*much', 'prior_denial'),
        (r'hasn\'?t?\s*applied|never\s*applied', 'never_applied'),
    ]

    for pattern, circumstance in circumstances_patterns:
        match = re.search(pattern, input_lower)
        if match:
            facts["circumstances"].append(circumstance)
            if circumstance == 'prior_denial':
                facts["prior_snap_denial"] = True
            if circumstance == 'disabled':
                facts["disabled_in_household"] = True
            facts["patterns_matched"].append(f"circumstance: {circumstance}")
            print(f"DEBUG - Circumstance matched: {circumstance}")

    print(f"DEBUG - Final facts: household_size={facts['household_size']}, income=${facts['total_monthly_income']}, patterns={len(facts['patterns_matched'])}")

    return facts

def generate_decision_map(facts: dict) -> dict:
    """Generate decision map for Virginia SNAP eligibility with comprehensive rules"""

    # Virginia SNAP gross income limits by household size (2026 estimates, 130% FPL)
    SNAP_GROSS_LIMITS = {
        1: 1580,
        2: 2137,
        3: 2694,
        4: 3250,
        5: 3807,
        6: 4364,
        7: 4921,
        8: 5478
    }

    # LIHEAP income limits (approximately 150% FPL)
    LIHEAP_LIMITS = {
        1: 2400,
        2: 3240,
        3: 4080,
        4: 4920,
        5: 5760,
        6: 6600,
        7: 7440,
        8: 8280
    }

    household_size = facts.get("household_size", 1)
    gross_limit = SNAP_GROSS_LIMITS.get(household_size, SNAP_GROSS_LIMITS[8])
    liheap_limit = LIHEAP_LIMITS.get(household_size, LIHEAP_LIMITS[8])

    decision_map = {
        "program": "SNAP",
        "state": "Virginia",
        "current_status": "not_eligible",
        "reason": "",
        "reversible": False,
        "high_impact_action": "",
        "next_steps": [],
        "documents_needed": [],
        "confidence": "medium",
        "household_size": household_size,
        "income_limit": gross_limit,
        "facts_extracted": {
            "income_sources": facts.get("income_sources", []),
            "circumstances": facts.get("circumstances", []),
            "patterns_matched": len(facts.get("patterns_matched", []))
        }
    }

    # Get income (support both old and new format)
    gross_income = facts.get("total_monthly_income") or facts.get("gross_monthly_income")

    if gross_income is None:
        decision_map["current_status"] = "insufficient_info"
        decision_map["reason"] = "Unable to determine income from provided information"
        decision_map["confidence"] = "low"
        decision_map["next_steps"] = [
            "Verify monthly gross income amount",
            "Gather recent pay stubs or income documentation",
            "List all income sources (employment, benefits, support payments)"
        ]
        decision_map["missing_info"] = facts.get("missing_critical_info", ["income"])
        return decision_map

    # Elderly/disabled households have no gross income test in some cases
    if facts.get("elderly_in_household") or facts.get("disabled_in_household"):
        decision_map["confidence"] = "medium"
        decision_map["special_rules"] = "Elderly/disabled household - may qualify under net income test only"

    if gross_income <= gross_limit:
        decision_map["current_status"] = "likely_eligible"
        decision_map["reason"] = f"Income ${gross_income}/month is within SNAP gross limit of ${gross_limit} for household of {household_size}"
        decision_map["confidence"] = "high"
        decision_map["next_steps"] = [
            "Apply for SNAP through local DSS office or CommonHelp.virginia.gov",
            "Gather required income and identity documents",
            "Complete interview within 30 days of application"
        ]
        decision_map["documents_needed"] = [
            "Recent pay stubs (last 30 days)",
            "Photo ID for all adult household members",
            "Proof of residence (lease, utility bill)",
            "Social Security cards for all household members"
        ]

        # Add expedited service info if applicable
        if gross_income < 150 or 'homeless' in facts.get("circumstances", []):
            decision_map["expedited"] = True
            decision_map["next_steps"].insert(0, "Request EXPEDITED processing (7-day approval)")
    else:
        income_over = gross_income - gross_limit

        # Check for LIHEAP pathway
        if facts.get("utilities_separate") and gross_income <= liheap_limit:
            decision_map["current_status"] = "potentially_eligible"
            decision_map["reversible"] = True
            decision_map["reason"] = f"Income ${gross_income}/month is ${income_over} over SNAP limit, but LIHEAP utility deduction could qualify household"
            decision_map["high_impact_action"] = "Apply for LIHEAP to qualify for Standard Utility Allowance (SUA), which reduces countable SNAP income"
            decision_map["next_steps"] = [
                "Apply for LIHEAP immediately at local DSS or action agency",
                "Collect utility bills showing account in your name",
                "Apply for SNAP and mention pending LIHEAP application",
                "Request SUA deduction on SNAP application"
            ]
            decision_map["documents_needed"] = [
                "Recent electric or gas bill in your name",
                "Proof of income (last 30 days)",
                "Lease agreement showing utilities are separate",
                "Photo ID and Social Security card"
            ]
            decision_map["potential_benefit"] = f"With SUA deduction, net income could qualify for SNAP"
        else:
            decision_map["current_status"] = "not_eligible"
            decision_map["reason"] = f"Income ${gross_income}/month exceeds SNAP limit of ${gross_limit} for household of {household_size}"
            decision_map["next_steps"] = [
                "Verify all income amounts are accurate",
                "Check if household size should include additional members",
                "Review if any deductions apply (medical, childcare, shelter)"
            ]

            # Check for other deduction opportunities
            deduction_opportunities = []
            if facts.get("elderly_in_household") or facts.get("disabled_in_household"):
                deduction_opportunities.append("Medical expense deduction (expenses over $35/month)")
            if 'medical_expenses' in facts.get("circumstances", []):
                deduction_opportunities.append("Medical expense deduction available")

            if deduction_opportunities:
                decision_map["deduction_opportunities"] = deduction_opportunities
                decision_map["reversible"] = True

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
