"""Test the multi-program benefits screener with 4 scenarios."""

from main import normalize_facts, generate_multi_program_eligibility

scenarios = {
    'Young Family': '''Couple with two children ages 3 and 6. Father works full-time making $2,400/month gross.
    Mother is 20 weeks pregnant with their third child, staying home with the kids.
    Rent is $1,100, utilities separate averaging $180/month.
    Currently have no health insurance for the family.''',

    'Senior Couple': '''Married couple, both age 68, both on Medicare.
    Combined Social Security income of $2,100/month.
    Own their home outright but pay $220/month for heating oil and electric.
    Husband has diabetes with $150/month medication costs even with Medicare Part D.''',

    'Working Adult': '''Single adult age 42, no children.
    Works two part-time jobs: $12/hour for 20 hours at a warehouse, plus $14/hour for 15 hours at a restaurant.
    Rents a room for $650/month, utilities included.
    No health insurance, no disabilities.''',

    'Pregnant Woman': '''Single mother age 26, currently 32 weeks pregnant.
    Has a 2-year-old daughter. On Medicaid for the pregnancy.
    Works part-time as cashier making $11/hour for 25 hours/week.
    Lives with her mother (not applying), paying $400/month contribution to rent.
    Currently breastfeeding her toddler.'''
}

for name, text in scenarios.items():
    print(f'\n{"="*70}')
    print(f'{name}')
    print('='*70)

    facts = normalize_facts(text)
    result = generate_multi_program_eligibility(facts)

    # Print key facts extracted
    print(f'\nExtracted Facts:')
    print(f'  Household Size: {facts["household_size"]}')
    print(f'  Total Monthly Income: ${facts.get("total_monthly_income") or "N/A"}')
    print(f'  Income Sources: {len(facts.get("income_sources", []))}')
    for src in facts.get('income_sources', []):
        amt = src['raw_amount']
        print(f'    - {src["type"]}: ${amt}/{src["frequency"]} -> ${src["monthly_amount"]}/mo')

    print(f'  Children under 5: {facts.get("children_under_5", 0)}')
    print(f'  Children school age: {facts.get("children_school_age", 0)}')
    print(f'  Pregnant: {facts.get("pregnant", False)}')
    print(f'  Breastfeeding: {facts.get("breastfeeding", False)}')
    print(f'  Medicare eligible: {facts.get("medicare_eligible", False)}')
    print(f'  On Medicare: {facts.get("on_medicare", False)}')
    print(f'  Has heating/cooling costs: {facts.get("has_heating_cooling_costs", False)}')
    print(f'  Utilities included: {facts.get("utilities_included", False)}')

    # Print summary
    print(f'\nEligibility Summary:')
    print(f'  Likely Eligible: {result["summary"]["likely_eligible"]}')
    print(f'  Potentially Eligible: {result["summary"]["potentially_eligible"]}')
    print(f'  Not Eligible: {result["summary"]["not_eligible"]}')
    print(f'  Not Applicable: {result["summary"]["not_applicable"]}')

    # Print priority action
    if result.get("priority_action"):
        pa = result["priority_action"]
        print(f'\nPriority Action: {pa["program"]}')
        print(f'  Reason: {pa["reason"]}')
        if pa.get("expedited"):
            print(f'  EXPEDITED: Yes')

    # Print total value
    print(f'\nTotal Estimated Monthly Value: {result["total_estimated_monthly_value"]}')

    # Print each program result
    print(f'\nProgram Details:')
    for prog in result["programs"]:
        status_emoji = {
            'likely_eligible': '[Y]',
            'potentially_eligible': '[?]',
            'not_eligible': '[N]',
            'not_applicable': '[-]',
            'insufficient_info': '[!]'
        }.get(prog["status"], '[ ]')

        print(f'  {status_emoji} {prog["program"]}: {prog["status"]}')
        print(f'      Reason: {prog["reason"][:80]}...' if len(prog.get("reason", "")) > 80 else f'      Reason: {prog.get("reason", "N/A")}')
        if prog.get("estimated_benefit"):
            print(f'      Benefit: {prog["estimated_benefit"]}')
        if prog.get("tier"):
            print(f'      Tier: {prog["tier"]}')

    print(f'\nData Quality Score: {result.get("data_quality_score", "N/A")}')
