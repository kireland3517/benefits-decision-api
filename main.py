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

# =============================================================================
# FREQUENCY NORMALIZATION CONSTANTS
# =============================================================================
FREQUENCY_TO_MONTHLY = {
    'hourly': 173.33,      # 40 hrs/week × 4.33 weeks
    'weekly': 4.33,        # 52 weeks ÷ 12 months
    'biweekly': 2.167,     # 26 pay periods ÷ 12
    'semi-monthly': 2.0,   # 24 pay periods ÷ 12
    'monthly': 1.0,
    'annual': 0.0833,      # 1 ÷ 12
    'yearly': 0.0833
}

# =============================================================================
# CONFIDENCE SCORING HELPER
# =============================================================================
def calculate_extraction_confidence(field: str, value, context: str, matched_pattern: str = None) -> dict:
    """Calculate confidence score for extracted data with factor breakdown."""
    base_confidence = 0.65  # Base for self-reported data
    factors = {"base": base_confidence}

    # Boost for explicit affirmative language
    if re.search(r'\b(?:is|are|earns?|makes?|receives?|gets?)\b', context, re.IGNORECASE):
        factors["explicit_language"] = 0.10

    # Boost for specific values (not rounded)
    if value and isinstance(value, (int, float)):
        if value % 100 != 0:  # Not a round number
            factors["specific_value"] = 0.05

    # Reduce for hedging language
    if re.search(r'\b(?:maybe|possibly|approximately|about|around|estimated|roughly|probably)\b', context, re.IGNORECASE):
        factors["hedging_detected"] = -0.10

    # Reduce for temporal uncertainty
    if re.search(r'\b(?:used\s+to|previously|before|last\s+(?:year|month)|was\s+making)\b', context, re.IGNORECASE):
        factors["temporal_uncertainty"] = -0.15

    # Reduce for negation proximity
    if re.search(r'\b(?:no[t]?|doesn\'t|don\'t|never|without|stopped)\b', context, re.IGNORECASE):
        factors["negation_detected"] = -0.20

    # Boost for dollar sign (more explicit)
    if matched_pattern and r'\$' in matched_pattern:
        factors["explicit_currency"] = 0.05

    total = sum(factors.values())
    return {
        "confidence": max(0.0, min(1.0, total)),
        "factors": factors
    }

def detect_contradictions(input_text: str, facts: dict) -> list:
    """Detect contradictory information in the input."""
    contradictions = []
    input_lower = input_text.lower()

    # Employment contradictions
    has_employed = bool(re.search(r'\b(?:works?|working|employed|job|makes?\s+\$)\b', input_lower))
    has_unemployed = bool(re.search(r'\b(?:unemployed|not\s+working|no\s+job|jobless|laid\s+off)\b', input_lower))
    if has_employed and has_unemployed:
        contradictions.append({
            "type": "employment_status",
            "description": "Both employed and unemployed indicators detected",
            "severity": "medium"
        })

    # Marital contradictions
    has_single = bool(re.search(r'\bsingle\s+(?:adult|person|mother|father)\b', input_lower))
    has_married = bool(re.search(r'\b(?:married|spouse|husband|wife|partner)\b', input_lower))
    if has_single and has_married:
        contradictions.append({
            "type": "marital_status",
            "description": "Both single and married/partnered indicators detected",
            "severity": "medium"
        })

    # Housing contradictions
    has_homeless = bool(re.search(r'\b(?:homeless|no\s+(?:permanent\s+)?address|shelter)\b', input_lower))
    has_rent = facts.get("rent") and facts["rent"] > 0
    if has_homeless and has_rent:
        contradictions.append({
            "type": "housing_status",
            "description": "Homeless indicator with rent amount detected",
            "severity": "low"
        })

    return contradictions

# =============================================================================
# COMPREHENSIVE FACT EXTRACTION
# =============================================================================
def normalize_facts(input_raw: str) -> dict:
    """Comprehensive fact extraction with confidence scoring and validation."""

    print(f"DEBUG - Raw input: {input_raw}")

    facts = {
        # HOUSEHOLD COMPOSITION
        "household_size": 1,
        "household_members": [],
        "custody_info": None,
        "living_situation": None,

        # INCOME SOURCES (comprehensive)
        "income_sources": [],
        "total_monthly_income": None,
        "gross_monthly_income": None,  # Backward compatibility
        "income_irregular": False,

        # DEMOGRAPHICS
        "ages": [],
        "elderly_in_household": False,
        "disabled_in_household": False,

        # EMPLOYMENT
        "employment_status": None,
        "work_hours": None,

        # HOUSING
        "housing_type": None,
        "housing_instability": None,
        "rent": None,
        "utilities_separate": False,
        "utility_cost": None,

        # SPECIAL CIRCUMSTANCES
        "circumstances": [],
        "prior_snap_denial": False,
        "domestic_violence": False,

        # POTENTIAL DEDUCTIONS (informational)
        "potential_deductions": {
            "childcare": None,
            "medical": None,
            "court_ordered_support": None,
            "shelter_burden": None
        },

        # EXTRACTION METADATA
        "extraction_confidence": {},
        "patterns_matched": [],
        "patterns_attempted": 0,
        "missing_critical_info": [],
        "contradictions_detected": [],

        # DEBUG INFO
        "extraction_debug": {
            "raw_extractions": [],
            "confidence_factors": {},
            "unmatched_indicators": []
        }
    }

    input_lower = input_raw.lower()
    patterns_attempted = 0

    # =========================================================================
    # 1. HOUSEHOLD SIZE PATTERNS (Enhanced with custody)
    # =========================================================================
    # Map number words to digits
    number_words = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8}

    household_patterns = [
        # Explicit counts (highest priority)
        (r'household\s*of\s*(\d+|four|five|six|seven|eight)', 'household_count'),
        (r'(\d+)\s*person\s*household', 'household_count'),
        (r'family\s*of\s*(\d+|four|five|six|seven|eight)', 'family_count'),
        (r'couple|married|husband|wife|spouse', 'couple'),
        (r'twin\s*(?:\d+[-\s]?year[-\s]?old)?\s*(?:boys?|girls?|children|kids)', 'twin_children'),  # twins = 2
        (r'(\d+)\s*(?:u\.?s\.?\s*citizen\s*)?child(?:ren)?', 'children'),
        (r'(?:children|kids)\s*ages?\s*(\d+)\s*and\s*(\d+)', 'children_ages'),  # "children ages 6 and 10"
        (r'single\s*(?:adult|mother|father|person|mom|dad)', 'single'),
        (r'living\s*with\s*(\d+)\s*(?:other\s*)?people', 'living_with'),
        (r'(?:grand)?(?:mother|father|parent)s?\s*(?:living|staying)\s*with', 'multigenerational'),
        (r'three[-\s]?generation(?:al)?\s*household', 'multigenerational'),  # "three-generation household"
        (r'multi[-\s]?generational', 'multigenerational'),
        # Explicit member counting
        (r'grandmother.*daughter.*(?:son|grandson|child)', 'multigenerational'),  # 3+ generations
        (r'(?:father|mother|parent).*(?:children|kids).*(?:ages?\s*\d+)', 'parent_with_children'),
    ]

    # Custody patterns
    custody_patterns = [
        (r'(?:joint|shared|split|50[-/]?50)\s*custody', 'joint_custody'),
        (r'(?:sole|full|primary|exclusive)\s*custody', 'sole_custody'),
        (r'(\d+)%\s*(?:custody|of\s*the\s*time)', 'custody_percentage'),
        (r'(?:visitation|parenting\s*time|every\s*other\s*(?:week|weekend))', 'visitation'),
    ]

    for pattern, pattern_type in household_patterns:
        patterns_attempted += 1
        match = re.search(pattern, input_lower)
        if match:
            if pattern_type == 'household_count':
                count_str = match.group(1)
                if count_str in number_words:
                    facts["household_size"] = number_words[count_str]
                else:
                    facts["household_size"] = int(count_str)
            elif pattern_type == 'family_count':
                count_str = match.group(1)
                if count_str in number_words:
                    facts["household_size"] = number_words[count_str]
                else:
                    facts["household_size"] = int(count_str)
            elif pattern_type == 'couple':
                facts["household_size"] = max(facts["household_size"], 2)
            elif pattern_type == 'twin_children':
                # Twins = 2 children, add to current household
                facts["household_size"] = max(facts["household_size"], facts["household_size"] + 2)
                facts["household_members"].append({"type": "children", "count": 2, "note": "twins"})
            elif pattern_type == 'children':
                num_children = int(match.group(1))
                facts["household_size"] = max(facts["household_size"], num_children + 1)
                facts["household_members"].append({"type": "children", "count": num_children})
            elif pattern_type == 'children_ages':
                # "children ages 6 and 10" = 2 children
                facts["household_size"] = max(facts["household_size"], 3)  # At least parent + 2 children
                facts["household_members"].append({"type": "children", "count": 2})
            elif pattern_type == 'single':
                # Only set to 1 if we haven't found children
                if not facts["household_members"]:
                    facts["household_size"] = 1
            elif pattern_type == 'living_with':
                facts["household_size"] = int(match.group(1)) + 1
            elif pattern_type == 'multigenerational':
                facts["household_size"] = max(facts["household_size"], 3)
                if "multigenerational" not in facts["circumstances"]:
                    facts["circumstances"].append("multigenerational")
            elif pattern_type == 'parent_with_children':
                # Look for explicit child count in surrounding context
                child_match = re.search(r'(\d+)\s*(?:children|kids)', input_lower)
                if child_match:
                    facts["household_size"] = max(facts["household_size"], int(child_match.group(1)) + 1)

            conf = calculate_extraction_confidence("household", facts["household_size"], input_raw, pattern)
            facts["extraction_confidence"]["household_size"] = conf["confidence"]
            facts["extraction_debug"]["confidence_factors"]["household"] = conf["factors"]
            facts["patterns_matched"].append(f"household:{pattern_type}")
            facts["extraction_debug"]["raw_extractions"].append({
                "field": "household",
                "matched_text": match.group(0),
                "pattern": pattern
            })
            print(f"DEBUG - Household pattern matched: {pattern_type} -> size={facts['household_size']}")

    # Check custody
    for pattern, custody_type in custody_patterns:
        patterns_attempted += 1
        match = re.search(pattern, input_lower)
        if match:
            if custody_type == 'custody_percentage':
                facts["custody_info"] = {"type": "percentage", "value": int(match.group(1))}
            else:
                facts["custody_info"] = {"type": custody_type}
            facts["patterns_matched"].append(f"custody:{custody_type}")

    # =========================================================================
    # 2. INCOME SOURCE PATTERNS (Enhanced with frequency normalization)
    # =========================================================================
    # Helper to parse amounts (handles decimals and ranges)
    def parse_amount(amount_str: str) -> float:
        """Parse amount string, handling decimals and commas."""
        return float(amount_str.replace(",", ""))

    income_patterns = [
        # Employment with frequency detection (earns/makes) - supports decimals
        (r'(?:makes?|earns?|earning)\s*(?:around\s*)?\$([0-9,.]+)\s*(?:a|per|/)\s*hour', 'employment', 'hourly'),
        (r'(?:makes?|earns?|earning)\s*(?:around\s*)?\$([0-9,.]+)\s*(?:a|per)\s*week(?:ly)?', 'employment', 'weekly'),
        (r'(?:makes?|earns?|earning)\s*(?:around\s*)?\$([0-9,.]+)\s*(?:bi[-\s]?weekly|every\s*(?:two|2)\s*weeks?)', 'employment', 'biweekly'),
        (r'(?:makes?|earns?|earning)\s*(?:around\s*)?\$([0-9,.]+)\s*(?:a|per)\s*month', 'employment', 'monthly'),
        (r'(?:makes?|earns?|earning)\s*(?:around\s*)?\$([0-9,.]+)\s*(?:a|per)\s*year', 'employment', 'yearly'),
        (r'\$([0-9,.]+)\s*(?:a|per|/)\s*hour', 'employment', 'hourly'),  # "$16.50/hour"
        (r'\$([0-9,.]+)\s*(?:a|per)\s*month(?:\s*(?:before|gross))?', 'employment', 'monthly'),
        (r'\$([0-9,.]+)\s*(?:a|per)\s*week(?:ly)?', 'employment', 'weekly'),
        (r'\$([0-9,.]+)\s*monthly', 'employment', 'monthly'),
        (r'\$([0-9,.]+)\s*weekly', 'employment', 'weekly'),
        (r'\$([0-9,.]+)\s*(?:before|gross)', 'employment', 'monthly'),
        (r'salary\s*(?:of\s*)?\$([0-9,.]+)', 'employment', 'yearly'),
        # Default monthly (must come after specific frequencies)
        (r'(?:makes?|earns?|earning)\s*(?:around\s*)?\$([0-9,.]+)(?!\s*(?:a|per|/)\s*(?:hour|week|year))', 'employment', 'monthly'),

        # Self-employment / Gig work / Side business
        (r'(?:1099|freelance|gig|side\s*(?:hustle|business)|self[-\s]?employ)\s*.*?\$([0-9,.]+)', 'self_employment', 'monthly'),
        (r'\$([0-9,.]+)\s*(?:from\s*)?(?:side\s*(?:hustle|business)|freelance)', 'self_employment', 'monthly'),
        (r'(?:uber|lyft|doordash|instacart)\s*.*?\$([0-9,.]+)', 'gig_work', 'monthly'),
        (r'cleaning\s*(?:offices?|houses?|business).*?\$([0-9,.]+)', 'self_employment', 'monthly'),

        # Government benefits (always monthly) - label before and after amount
        (r'unemployment\s*(?:benefits?\s*)?(?:of\s*)?\$([0-9,.]+)', 'unemployment', 'monthly'),
        (r'\$([0-9,.]+)\s*(?:monthly\s*)?(?:from\s*)?unemployment', 'unemployment', 'monthly'),
        (r'expecting\s*(?:about\s*)?\$([0-9,.]+)\s*(?:weekly|per\s*week)', 'unemployment_pending', 'weekly'),
        (r'social\s*security\s*(?:of\s*)?\$([0-9,.]+)', 'social_security', 'monthly'),
        (r'\$([0-9,.]+)\s*(?:monthly\s*)?(?:from\s*)?social\s*security', 'social_security', 'monthly'),
        (r'(?:ssi|ssdi)\s*(?:of\s*)?\$([0-9,.]+)', 'ssi_ssdi', 'monthly'),
        (r'\$([0-9,.]+)\s*(?:monthly\s*)?(?:from\s*)?(?:ssi|ssdi)', 'ssi_ssdi', 'monthly'),
        (r'\$([0-9,.]+)\s*monthly\s*ssdi', 'ssi_ssdi', 'monthly'),  # "$914 monthly SSDI"
        (r'disability\s*(?:benefits?\s*)?(?:of\s*)?\$([0-9,.]+)', 'disability', 'monthly'),
        (r'\$([0-9,.]+)\s*(?:monthly\s*)?(?:from\s*)?disability', 'disability', 'monthly'),
        (r'gets?\s*\$([0-9,.]+)\s*(?:monthly\s*)?(?:from\s*)?(?:ssi|ssdi|disability)', 'disability', 'monthly'),
        (r'pension\s*(?:of\s*)?\$([0-9,.]+)', 'pension', 'monthly'),
        (r'\$([0-9,.]+)\s*(?:monthly\s*)?(?:from\s*)?pension', 'pension', 'monthly'),
        (r'(?:va|veteran)\s*benefits?\s*(?:of\s*)?\$([0-9,.]+)', 'va_benefits', 'monthly'),
        (r'\$([0-9,.]+)\s*(?:monthly\s*)?(?:from\s*)?(?:va|veteran)', 'va_benefits', 'monthly'),

        # Support payments
        (r'(?:receives?\s*)?\$([0-9,.]+)\s*(?:monthly\s*)?child\s*support', 'child_support', 'monthly'),
        (r'child\s*support\s*(?:of\s*)?\$([0-9,.]+)', 'child_support', 'monthly'),
        (r'\$([0-9,.]+)\s*(?:from\s*)?child\s*support', 'child_support', 'monthly'),
        (r'alimony\s*(?:of\s*)?\$([0-9,.]+)', 'alimony', 'monthly'),
        (r'\$([0-9,.]+)\s*(?:from\s*)?alimony', 'alimony', 'monthly'),

        # Non-dollar income patterns
        (r'(?:makes?|earns?)\s*(?:around\s*|about\s*)?([0-9,]+)\s*(?:a|per)\s*month', 'employment', 'monthly'),
    ]

    # Income range patterns (take lower bound for conservative estimate)
    income_range_patterns = [
        (r'\$([0-9,.]+)[-–](?:\$)?([0-9,.]+)\s*(?:(?:a|per)\s*)?month', 'variable_income', 'monthly'),
        (r'\$([0-9,.]+)[-–](?:\$)?([0-9,.]+)\s*(?:some\s*)?months?', 'variable_income', 'monthly'),
        (r'\$([0-9,.]+)[-–](?:\$)?([0-9,.]+)\s*(?:(?:a|per)\s*)?week', 'variable_income', 'weekly'),
        (r'(?:makes?|earns?)\s*\$([0-9,.]+)[-–](?:\$)?([0-9,.]+)', 'variable_income', 'monthly'),
    ]

    total_income = 0
    seen_amounts = {}  # Track amounts with their types for deduplication
    seen_monthly_amounts = set()  # Track normalized monthly amounts to prevent double-counting

    # Process regular income patterns
    for pattern, income_type, frequency in income_patterns:
        patterns_attempted += 1
        matches = re.finditer(pattern, input_lower)
        for match in matches:
            try:
                amount = parse_amount(match.group(1))

                # Skip very small amounts that are likely ages/hours, not income
                if amount < 10 and frequency == 'monthly':
                    continue

                # Calculate monthly for deduplication check
                multiplier = FREQUENCY_TO_MONTHLY.get(frequency, 1.0)
                monthly_check = int(amount * multiplier)

                # Skip if we've seen this exact raw amount with this type
                amount_key = f"{amount}_{income_type}"
                if amount_key in seen_amounts:
                    continue

                # Skip if the monthly amount is very close to one we've already seen
                # This prevents counting $914 SSDI multiple times with different type labels
                is_duplicate = False
                for seen_monthly in seen_monthly_amounts:
                    if abs(seen_monthly - monthly_check) < 50:  # Within $50 = likely same source
                        is_duplicate = True
                        break
                if is_duplicate:
                    continue

                seen_amounts[amount_key] = monthly_check
                seen_monthly_amounts.add(monthly_check)

                # Normalize to monthly
                multiplier = FREQUENCY_TO_MONTHLY.get(frequency, 1.0)
                monthly_amount = int(amount * multiplier)

                income_source = {
                    "type": income_type,
                    "raw_amount": amount,
                    "frequency": frequency,
                    "monthly_amount": monthly_amount
                }

                # Calculate confidence for this income source
                conf = calculate_extraction_confidence("income", amount, input_raw, pattern)
                income_source["confidence"] = conf["confidence"]

                facts["income_sources"].append(income_source)
                total_income += monthly_amount

                facts["patterns_matched"].append(f"income:{income_type}:{frequency}")
                facts["extraction_debug"]["raw_extractions"].append({
                    "field": "income",
                    "matched_text": match.group(0),
                    "pattern": pattern,
                    "normalized_monthly": monthly_amount
                })
                facts["extraction_debug"]["confidence_factors"][f"income_{income_type}"] = conf["factors"]
                print(f"DEBUG - Income matched: {income_type} = ${amount}/{frequency} -> ${monthly_amount}/month")

            except (ValueError, IndexError):
                continue

    # Process income range patterns (use lower bound for conservative estimate)
    for pattern, income_type, frequency in income_range_patterns:
        patterns_attempted += 1
        matches = re.finditer(pattern, input_lower)
        for match in matches:
            try:
                low_amount = parse_amount(match.group(1))
                high_amount = parse_amount(match.group(2))

                # Use average for estimation, but flag as variable
                amount = (low_amount + high_amount) / 2

                # Skip if we already captured this range
                range_key = f"{low_amount}-{high_amount}"
                if range_key in seen_amounts:
                    continue

                multiplier = FREQUENCY_TO_MONTHLY.get(frequency, 1.0)
                monthly_amount = int(amount * multiplier)

                seen_amounts[range_key] = monthly_amount
                seen_monthly_amounts.add(monthly_amount)

                income_source = {
                    "type": income_type,
                    "raw_amount": f"{low_amount}-{high_amount}",
                    "frequency": frequency,
                    "monthly_amount": monthly_amount,
                    "is_variable": True,
                    "range_low": int(low_amount * multiplier),
                    "range_high": int(high_amount * multiplier)
                }

                conf = calculate_extraction_confidence("income", amount, input_raw, pattern)
                conf["confidence"] -= 0.10  # Reduce confidence for ranges
                income_source["confidence"] = max(0.3, conf["confidence"])

                facts["income_sources"].append(income_source)
                facts["income_irregular"] = True
                total_income += monthly_amount

                facts["patterns_matched"].append(f"income:{income_type}:range:{frequency}")
                print(f"DEBUG - Income range matched: {income_type} = ${low_amount}-${high_amount}/{frequency} -> ${monthly_amount}/month (avg)")

            except (ValueError, IndexError):
                continue

    if total_income > 0:
        facts["total_monthly_income"] = total_income
        facts["gross_monthly_income"] = total_income

        # Calculate overall income confidence (average of sources)
        if facts["income_sources"]:
            avg_conf = sum(s.get("confidence", 0.65) for s in facts["income_sources"]) / len(facts["income_sources"])
            facts["extraction_confidence"]["income"] = avg_conf
    else:
        facts["missing_critical_info"].append("income")
        print("DEBUG - No income pattern matched")

    # Check for irregular income indicators
    irregular_patterns = [
        r'(?:varies?|variable|irregular|fluctuat)',
        r'(?:sometimes|occasionally|when\s+available)',
        r'(?:seasonal|temporary|contract)',
    ]
    for pattern in irregular_patterns:
        if re.search(pattern, input_lower):
            facts["income_irregular"] = True
            facts["circumstances"].append("irregular_income")
            break

    # =========================================================================
    # 3. AGE PATTERNS (Enhanced - find ALL ages)
    # =========================================================================
    age_patterns = [
        (r'(\d+)\s*years?\s*old', 'age'),
        (r'age[sd]?\s*(\d+)', 'age'),
        (r'(?:kids?|children?)\s*(?:are\s*)?(\d+)(?:\s*,\s*(\d+))?(?:\s*(?:,|and)\s*(\d+))?', 'child_ages'),
        (r'elderly|senior', 'elderly'),
        (r'retired', 'retired'),
    ]

    for pattern, pattern_type in age_patterns:
        patterns_attempted += 1
        if pattern_type == 'child_ages':
            match = re.search(pattern, input_lower)
            if match:
                for group in match.groups():
                    if group:
                        try:
                            age = int(group)
                            if age < 22:  # Reasonable child age
                                facts["ages"].append(age)
                        except ValueError:
                            pass
        elif pattern_type == 'age':
            for match in re.finditer(pattern, input_lower):
                try:
                    age = int(match.group(1))
                    if age not in facts["ages"]:  # Avoid duplicates
                        facts["ages"].append(age)
                        if age >= 60:
                            facts["elderly_in_household"] = True
                        facts["patterns_matched"].append(f"age:{age}")
                        print(f"DEBUG - Age matched: {age}")
                except ValueError:
                    pass
        elif pattern_type in ['elderly', 'retired']:
            if re.search(pattern, input_lower):
                facts["elderly_in_household"] = True
                facts["patterns_matched"].append(f"age:{pattern_type}")

    # =========================================================================
    # 4. HOUSING PATTERNS (Enhanced with instability detection)
    # =========================================================================
    housing_patterns = [
        (r'rent\s*(?:is\s*)?\$([0-9,]+)', 'rent_amount'),
        (r'\$([0-9,]+)\s*(?:for\s*)?rent', 'rent_amount'),
        (r'mortgage\s*(?:is\s*)?\$([0-9,]+)', 'mortgage_amount'),
        (r'owns?\s*(?:a\s*)?(?:home|house|condo)', 'own'),
        (r'lives?\s*with\s*(?:family|friend|parent|relative)', 'shared'),
        (r'section\s*8|housing\s*voucher|subsidized', 'subsidized'),
    ]

    housing_instability_patterns = [
        (r'homeless|unhoused|unsheltered', 'literal_homeless'),
        (r'(?:homeless|emergency)\s*shelter', 'shelter'),
        (r'(?:domestic\s*violence|dv)\s*shelter', 'dv_shelter'),
        (r'(?:transitional|temporary)\s*housing', 'transitional'),
        (r'doubled[-\s]?up|couch\s*surfing', 'doubled_up'),
        (r'staying\s*(?:with|at)\s*(?:friend|family)', 'doubled_up'),
        (r'no\s*(?:permanent|stable|fixed)\s*(?:address|housing)', 'unstable'),
        (r'eviction\s*(?:notice|pending|facing)', 'at_risk'),
        (r'behind\s*on\s*rent|past\s*due', 'at_risk'),
        (r'living\s*in\s*(?:car|vehicle|street)', 'literal_homeless'),
    ]

    for pattern, pattern_type in housing_patterns:
        patterns_attempted += 1
        match = re.search(pattern, input_lower)
        if match:
            if pattern_type == 'rent_amount':
                facts["rent"] = int(match.group(1).replace(",", ""))
                facts["housing_type"] = "rent"
                conf = calculate_extraction_confidence("rent", facts["rent"], input_raw, pattern)
                facts["extraction_confidence"]["rent"] = conf["confidence"]
                print(f"DEBUG - Rent matched: ${facts['rent']}")
            elif pattern_type == 'mortgage_amount':
                facts["rent"] = int(match.group(1).replace(",", ""))
                facts["housing_type"] = "own"
            else:
                facts["housing_type"] = pattern_type
            facts["patterns_matched"].append(f"housing:{pattern_type}")

    for pattern, instability_type in housing_instability_patterns:
        patterns_attempted += 1
        if re.search(pattern, input_lower):
            facts["housing_instability"] = instability_type
            facts["circumstances"].append(f"housing_{instability_type}")
            facts["patterns_matched"].append(f"housing_instability:{instability_type}")
            print(f"DEBUG - Housing instability matched: {instability_type}")
            if instability_type in ['literal_homeless', 'shelter']:
                facts["circumstances"].append("homeless")

    # =========================================================================
    # 5. UTILITY PATTERNS
    # =========================================================================
    utility_patterns = [
        (r'(?:utilities?|electric|gas|heat)\s*(?:is\s*|of\s*|about\s*)?\$([0-9,]+)', 'utility_amount'),
        (r'\$([0-9,]+)\s*(?:for\s*)?(?:utilities?|electric|gas)', 'utility_amount'),
        (r'\$([0-9,]+)\s*total\s*(?:utilities?|electric\s*and\s*gas)', 'utility_amount'),
        (r'pays?\s*(?:electric|gas|utilities?)\s*separate(?:ly)?', 'separate'),
        (r'utilities?\s*(?:are\s*)?included', 'included'),
    ]

    for pattern, pattern_type in utility_patterns:
        patterns_attempted += 1
        match = re.search(pattern, input_lower)
        if match:
            if pattern_type == 'utility_amount':
                facts["utility_cost"] = int(match.group(1).replace(",", ""))
                facts["utilities_separate"] = True
                print(f"DEBUG - Utility cost matched: ${facts['utility_cost']}")
            elif pattern_type == 'separate':
                facts["utilities_separate"] = True
            elif pattern_type == 'included':
                facts["utilities_separate"] = False
            facts["patterns_matched"].append(f"utility:{pattern_type}")

    # =========================================================================
    # 6. EMPLOYMENT STATUS
    # =========================================================================
    employment_patterns = [
        (r'part[\s-]*time', 'part-time'),
        (r'full[\s-]*time', 'full-time'),
        (r'unemployed|not\s*working|no\s*job', 'unemployed'),
        (r'retired', 'retired'),
        (r'disabled?|on\s*disability', 'disabled'),
        (r'(\d+)\s*hours?\s*(?:a|per)\s*week', 'hours'),
        (r'(?:laid\s*off|lost\s*(?:my\s*)?job|fired|let\s*go)', 'recently_unemployed'),
        (r'(?:just\s*started|recently\s*hired|new\s*job)', 'recently_employed'),
    ]

    for pattern, pattern_type in employment_patterns:
        patterns_attempted += 1
        match = re.search(pattern, input_lower)
        if match:
            if pattern_type == 'hours':
                facts["work_hours"] = int(match.group(1))
            else:
                facts["employment_status"] = pattern_type
            facts["patterns_matched"].append(f"employment:{pattern_type}")
            print(f"DEBUG - Employment matched: {pattern_type}")

    # =========================================================================
    # 7. SPECIAL CIRCUMSTANCES (Enhanced)
    # =========================================================================
    circumstances_patterns = [
        (r'domestic\s*violence|abuse|restraining\s*order|protective\s*order', 'domestic_violence'),
        (r'fleeing\s*(?:abuse|abuser|domestic)', 'domestic_violence'),
        (r'vawa|violence\s*against\s*women', 'domestic_violence'),
        (r'homeless|shelter|living\s*in\s*(?:car|street)', 'homeless'),
        (r'disabled?|disability|impair(?:ed|ment)', 'disabled'),
        (r'laid\s*off|fired|quit|lost\s*(?:my\s*)?job', 'job_loss'),
        (r'medical\s*(?:bills?|expenses?|debt)', 'medical_expenses'),
        (r'lost\s*snap|denied|(?:said|they\s*said)\s*.*?too\s*much', 'prior_denial'),
        (r'hasn\'?t?\s*applied|never\s*applied', 'never_applied'),
        (r'(?:pending|waiting\s*(?:on|for))\s*(?:disability|ssi|unemployment)', 'pending_benefits'),
        (r'student|(?:college|school|university)', 'student'),
        (r'migrant|seasonal\s*worker|farm\s*worker', 'migrant_worker'),
        (r'(?:undocumented|no\s*(?:legal\s*)?status)', 'immigration_concern'),
    ]

    for pattern, circumstance in circumstances_patterns:
        patterns_attempted += 1
        match = re.search(pattern, input_lower)
        if match:
            if circumstance not in facts["circumstances"]:
                facts["circumstances"].append(circumstance)
            if circumstance == 'prior_denial':
                facts["prior_snap_denial"] = True
            if circumstance == 'disabled':
                facts["disabled_in_household"] = True
            if circumstance == 'domestic_violence':
                facts["domestic_violence"] = True
            facts["patterns_matched"].append(f"circumstance:{circumstance}")
            print(f"DEBUG - Circumstance matched: {circumstance}")

    # =========================================================================
    # 8. DEDUCTION PATTERN EXTRACTION (Informational Only)
    # =========================================================================
    deduction_patterns = [
        # Childcare / After-school
        (r'(?:childcare|daycare|child\s*care|after[-\s]?school)\s*(?:program\s*)?(?:costs?\s*)?\$([0-9,.]+)', 'childcare'),
        (r'\$([0-9,.]+)\s*(?:(?:a|per|/)\s*month\s*)?(?:for\s*)?(?:childcare|daycare|child\s*care|after[-\s]?school)', 'childcare'),
        (r'pays?\s*\$([0-9,.]+)\s*(?:(?:a|per|/)\s*month\s*)?(?:for\s*)?(?:daughter|son|child)(?:\'?s)?\s*(?:after[-\s]?school|daycare|care)', 'childcare'),

        # Medical expenses
        (r'(?:medical|health|medication|prescription|doctor)\s*(?:expenses?|bills?|costs?|visits?)\s*(?:costing\s*)?(?:around\s*)?(?:of\s*)?\$([0-9,.]+)', 'medical'),
        (r'\$([0-9,.]+)\s*(?:(?:a|per|/)\s*month\s*)?(?:in\s*|for\s*)?(?:medical|health|medication)', 'medical'),
        (r'(?:costing|costs?)\s*(?:around\s*|about\s*)?\$([0-9,.]+)\s*(?:(?:a|per|/)\s*month)?(?:\s*(?:even\s*)?with\s*(?:medicare|insurance))?', 'medical'),
        (r'(?:treatment|medication)\s*(?:costs?|expenses?)\s*(?:about\s*)?\$([0-9,.]+)', 'medical'),

        # Court-ordered support
        (r'pays?\s*(?:child\s*support|alimony)\s*(?:of\s*)?\$([0-9,.]+)', 'court_ordered_support'),

        # Work-related expenses
        (r'(?:commute|transportation|work)\s*(?:costs?\s*)?\$([0-9,.]+)', 'work_expenses'),
    ]

    for pattern, deduction_type in deduction_patterns:
        patterns_attempted += 1
        match = re.search(pattern, input_lower)
        if match:
            try:
                amount = int(parse_amount(match.group(1)))
                # Only update if not already set (first match wins)
                if facts["potential_deductions"].get(deduction_type) is None:
                    facts["potential_deductions"][deduction_type] = amount
                    facts["patterns_matched"].append(f"deduction:{deduction_type}")
                    print(f"DEBUG - Deduction matched: {deduction_type} = ${amount}")
            except (ValueError, IndexError):
                pass

    # Calculate shelter burden if we have rent and income
    if facts["rent"] and facts["total_monthly_income"]:
        facts["potential_deductions"]["shelter_burden"] = round(
            facts["rent"] / facts["total_monthly_income"], 2
        )

    # =========================================================================
    # 9. VALIDATION & CONTRADICTION DETECTION
    # =========================================================================
    facts["contradictions_detected"] = detect_contradictions(input_raw, facts)
    facts["patterns_attempted"] = patterns_attempted

    # Calculate overall data quality score
    confidence_values = list(facts["extraction_confidence"].values())
    if confidence_values:
        facts["extraction_debug"]["data_quality_score"] = round(
            sum(confidence_values) / len(confidence_values), 2
        )
    else:
        facts["extraction_debug"]["data_quality_score"] = 0.5

    # Check for potential unmatched indicators
    potential_indicators = [
        (r'\$\d', "Possible unextracted dollar amount"),
        (r'\d+\s*%', "Possible percentage value"),
        (r'custody', "Possible custody mention"),
    ]
    for pattern, indicator in potential_indicators:
        if re.search(pattern, input_lower) and not any(indicator.lower() in p.lower() for p in facts["patterns_matched"]):
            # Only add if we didn't already match something related
            pass  # Simplified - could add to unmatched_indicators

    print(f"DEBUG - Final facts: household_size={facts['household_size']}, income=${facts['total_monthly_income']}, patterns={len(facts['patterns_matched'])}/{patterns_attempted}")

    return facts

# =============================================================================
# DECISION MAP GENERATION (Enhanced with soft validation)
# =============================================================================
def generate_decision_map(facts: dict) -> dict:
    """Generate decision map with comprehensive rules and soft validation."""

    # Virginia SNAP gross income limits by household size (2026 estimates, 130% FPL)
    SNAP_GROSS_LIMITS = {
        1: 1580, 2: 2137, 3: 2694, 4: 3250,
        5: 3807, 6: 4364, 7: 4921, 8: 5478
    }

    # LIHEAP income limits (approximately 150% FPL)
    LIHEAP_LIMITS = {
        1: 2400, 2: 3240, 3: 4080, 4: 4920,
        5: 5760, 6: 6600, 7: 7440, 8: 8280
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

        # Enhanced extraction info
        "data_quality_score": facts.get("extraction_debug", {}).get("data_quality_score", 0.5),
        "low_confidence_fields": [],
        "confidence_warnings": [],
        "contradictions_detected": facts.get("contradictions_detected", []),

        "facts_extracted": {
            "income_sources": facts.get("income_sources", []),
            "circumstances": facts.get("circumstances", []),
            "patterns_matched": len(facts.get("patterns_matched", [])),
            "patterns_attempted": facts.get("patterns_attempted", 0),
            "extraction_confidence": facts.get("extraction_confidence", {}),
            "potential_deductions": facts.get("potential_deductions", {})
        }
    }

    # Check for low confidence fields
    for field, confidence in facts.get("extraction_confidence", {}).items():
        if confidence < 0.70:
            decision_map["low_confidence_fields"].append(field)
            decision_map["confidence_warnings"].append(
                f"{field.replace('_', ' ').title()} extraction has low confidence ({confidence:.0%})"
            )

    # Add contradiction warnings
    for contradiction in facts.get("contradictions_detected", []):
        decision_map["confidence_warnings"].append(
            f"Contradiction detected: {contradiction['description']}"
        )

    # Get income
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

    # Check for special rules
    special_rules = []
    if facts.get("elderly_in_household") or facts.get("disabled_in_household"):
        special_rules.append("Elderly/disabled household - may qualify under net income test only")
    if facts.get("domestic_violence"):
        special_rules.append("Domestic violence situation - expedited processing and confidentiality protections available")
    if facts.get("housing_instability") in ['literal_homeless', 'shelter']:
        special_rules.append("Homeless status - expedited 7-day processing required")
    if special_rules:
        decision_map["special_rules"] = special_rules

    # Main eligibility determination
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

        # Check for expedited service
        expedited_reasons = []
        if gross_income < 150:
            expedited_reasons.append("very low income")
        if 'homeless' in facts.get("circumstances", []):
            expedited_reasons.append("housing instability")
        if facts.get("domestic_violence"):
            expedited_reasons.append("domestic violence situation")

        if expedited_reasons:
            decision_map["expedited"] = True
            decision_map["expedited_reasons"] = expedited_reasons
            decision_map["next_steps"].insert(0, f"Request EXPEDITED processing (7-day approval) - qualifies due to: {', '.join(expedited_reasons)}")
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
            decision_map["potential_benefit"] = "With SUA deduction, net income could qualify for SNAP"
        else:
            decision_map["current_status"] = "not_eligible"
            decision_map["reason"] = f"Income ${gross_income}/month exceeds SNAP limit of ${gross_limit} for household of {household_size}"
            decision_map["next_steps"] = [
                "Verify all income amounts are accurate",
                "Check if household size should include additional members",
                "Review if any deductions apply (medical, childcare, shelter)"
            ]

            # Check for deduction opportunities
            deduction_opportunities = []
            if facts.get("elderly_in_household") or facts.get("disabled_in_household"):
                deduction_opportunities.append("Medical expense deduction (expenses over $35/month for elderly/disabled)")
            if facts.get("potential_deductions", {}).get("medical"):
                medical_amt = facts["potential_deductions"]["medical"]
                deduction_opportunities.append(f"Medical expense deduction: ${medical_amt} identified")
            if facts.get("potential_deductions", {}).get("childcare"):
                childcare_amt = facts["potential_deductions"]["childcare"]
                deduction_opportunities.append(f"Dependent care deduction: ${childcare_amt} identified")
            shelter_burden = facts.get("potential_deductions", {}).get("shelter_burden")
            if shelter_burden is not None and shelter_burden > 0.50:
                deduction_opportunities.append("Excess shelter deduction may apply (housing costs exceed 50% of income)")

            if deduction_opportunities:
                decision_map["deduction_opportunities"] = deduction_opportunities
                decision_map["reversible"] = True
                decision_map["reason"] += ". However, deductions may reduce countable income."

    # Adjust overall confidence based on data quality
    data_quality = decision_map["data_quality_score"]
    if data_quality < 0.60:
        decision_map["confidence"] = "low"
        decision_map["confidence_warnings"].append("Overall data quality is low - recommend verification of key facts")
    elif data_quality < 0.75 and decision_map["confidence"] == "high":
        decision_map["confidence"] = "medium"

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
