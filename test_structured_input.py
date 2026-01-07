"""Test the structured input schema and normalize_facts_from_structured function."""

from main import (
    StructuredRunRequest, HouseholdInput, PersonInput, IncomeItem, ExpenseItem,
    normalize_facts_from_structured, generate_multi_program_eligibility
)

# Test Scenario 1: Young Family (structured equivalent)
young_family = StructuredRunRequest(
    org_id="test",
    household=HouseholdInput(
        housing_type="renting",
        rent_amount=1100,
        utilities_separate=True,
        has_heating_costs=True,
        has_cooling_costs=True
    ),
    persons=[
        PersonInput(
            role="head_of_household",
            age=30,
            income=[IncomeItem(type="employment", amount=2400, frequency="monthly")]
        ),
        PersonInput(
            role="spouse",
            age=28,
            pregnant=True
        ),
        PersonInput(role="child", age=3),
        PersonInput(role="child", age=6)
    ]
)

# Test Scenario 2: Senior Couple
senior_couple = StructuredRunRequest(
    org_id="test",
    household=HouseholdInput(
        housing_type="own_outright",
        has_heating_costs=True,
        has_cooling_costs=True
    ),
    persons=[
        PersonInput(
            role="head_of_household",
            age=68,
            on_medicare=True,
            income=[IncomeItem(type="social_security", amount=1050, frequency="monthly")],
            expenses=[ExpenseItem(type="medical", amount=150, frequency="monthly")]
        ),
        PersonInput(
            role="spouse",
            age=68,
            on_medicare=True,
            income=[IncomeItem(type="social_security", amount=1050, frequency="monthly")]
        )
    ]
)

# Test Scenario 3: Working Adult with Multiple Jobs (hourly)
working_adult = StructuredRunRequest(
    org_id="test",
    household=HouseholdInput(
        housing_type="renting",
        rent_amount=650,
        utilities_included=True
    ),
    persons=[
        PersonInput(
            role="head_of_household",
            age=42,
            income=[
                IncomeItem(type="employment", amount=12, frequency="hourly", hours_per_week=20),
                IncomeItem(type="employment", amount=14, frequency="hourly", hours_per_week=15)
            ]
        )
    ]
)

# Test Scenario 4: Pregnant Single Mother
pregnant_mother = StructuredRunRequest(
    org_id="test",
    household=HouseholdInput(
        housing_type="living_with_others",
        rent_amount=400
    ),
    persons=[
        PersonInput(
            role="head_of_household",
            age=26,
            pregnant=True,
            breastfeeding=True,
            income=[IncomeItem(type="employment", amount=11, frequency="hourly", hours_per_week=25)]
        ),
        PersonInput(role="child", age=2)
    ]
)

scenarios = {
    "Young Family": young_family,
    "Senior Couple": senior_couple,
    "Working Adult (Hourly Jobs)": working_adult,
    "Pregnant Single Mother": pregnant_mother
}

print("=" * 70)
print("STRUCTURED INPUT TESTS")
print("=" * 70)

for name, request in scenarios.items():
    print(f'\n{"-"*70}')
    print(f'{name}')
    print(f'{"-"*70}')

    # Normalize structured input
    facts = normalize_facts_from_structured(request)

    # Generate eligibility
    result = generate_multi_program_eligibility(facts)

    # Print key facts
    print(f'\nExtracted Facts:')
    print(f'  Household Size: {facts["household_size"]}')
    print(f'  Total Monthly Income: ${facts.get("total_monthly_income") or 0}')
    print(f'  Income Sources: {len(facts.get("income_sources", []))}')
    for src in facts.get('income_sources', []):
        hours = src.get('hours_per_week', '')
        hours_str = f' ({hours}hrs/wk)' if hours else ''
        print(f'    - {src["type"]}: ${src["raw_amount"]}/{src["frequency"]}{hours_str} -> ${src["monthly_amount"]}/mo')

    print(f'  Children under 5: {facts.get("children_under_5", 0)}')
    print(f'  Children school age: {facts.get("children_school_age", 0)}')
    print(f'  Pregnant: {facts.get("pregnant", False)}')
    print(f'  Breastfeeding: {facts.get("breastfeeding", False)}')
    print(f'  On Medicare: {facts.get("on_medicare", False)}')
    print(f'  Has heating/cooling costs: {facts.get("has_heating_cooling_costs", False)}')
    print(f'  Utilities included: {facts.get("utilities_included", False)}')
    print(f'  Data Quality Score: {facts.get("data_quality_score", "N/A")}')

    # Print summary
    print(f'\nEligibility Summary:')
    print(f'  Likely Eligible: {result["summary"]["likely_eligible"]}')
    print(f'  Potentially Eligible: {result["summary"]["potentially_eligible"]}')
    print(f'  Total Est. Monthly Value: {result["total_estimated_monthly_value"]}')

    # Print each program
    print(f'\nProgram Results:')
    for prog in result["programs"]:
        status_emoji = {
            'likely_eligible': '[Y]',
            'potentially_eligible': '[?]',
            'not_eligible': '[N]',
            'not_applicable': '[-]'
        }.get(prog["status"], '[ ]')
        print(f'  {status_emoji} {prog["program"]}: {prog["status"]}')

print(f'\n{"="*70}')
print("STRUCTURED INPUT TESTS COMPLETE")
print("=" * 70)
