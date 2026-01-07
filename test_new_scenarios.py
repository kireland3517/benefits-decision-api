"""Test the 4 new comprehensive scenarios."""

from main import normalize_facts, generate_decision_map

scenarios = {
    'Scenario 9': '''Single mother, 31, with joint custody of 8-year-old daughter (50/50 split). Works part-time as dental hygienist earning $28 per hour, about 25 hours per week. Also receives $485 monthly child support when ex pays it, but he's been inconsistent lately. Started a small side business cleaning offices, makes approximately $300-400 cash per month depending on clients. Recently applied for unemployment benefits from previous full-time job layoff 6 months ago, expecting about $380 weekly if approved. Rent is $1,175, pays electric and gas separately averaging $145/month. Pays $275/month for daughter's after-school program.''',

    'Scenario 10': '''Three-generation household: grandmother age 78 receiving Social Security of $1,456/month plus small pension of $287/month, adult daughter age 52 who's disabled and gets $914 monthly SSDI, and daughter's 16-year-old son who works part-time at grocery store making $12/hour for about 15 hours weekly during school year. They share a 3-bedroom rental house at $1,650/month split three ways. Grandmother has diabetes medication and doctor visits costing around $380/month even with Medicare. Teenager qualifies for free school meals. Utilities are about $280/month total shared among all three.''',

    'Scenario 11': '''Married couple, both around 45. Husband says he's unemployed but mentions getting "some cash work" helping neighbors with handyman jobs, maybe $600-800 some months but not every month. Wife works full-time at fast food restaurant making $16.50/hour for 35-40 hours weekly. They're currently homeless, staying at different friends' houses because they got evicted 3 weeks ago for non-payment of rent. Have been sleeping in their car some nights. Wife thinks they might qualify for emergency housing assistance. They have twin 12-year-old boys who are staying with wife's sister temporarily so they can keep attending the same school. No current utility bills since they don't have permanent housing.''',

    'Scenario 12': '''Household of four: father is permanent resident, mother is undocumented (not applying for benefits), and two U.S. citizen children ages 6 and 10. Father works construction seasonally - makes good money during busy season ($3,200-3,800 monthly from March to October) but very little in winter months ($800-1,200 monthly from odd jobs November to February). Mother provides informal childcare for neighbors, earns about $400-500 cash monthly but doesn't want to report this income due to immigration concerns. Currently winter season so income is low. Family pays $1,425 rent for 2-bedroom apartment, utilities included. Father wants to apply for food benefits for the children only. Medical expenses for son's asthma treatment cost about $150/month with insurance.'''
}

for name, text in scenarios.items():
    print(f'\n{"="*70}')
    print(f'{name}')
    print('='*70)

    facts = normalize_facts(text)
    decision = generate_decision_map(facts)

    print(f'Household Size: {facts["household_size"]}')
    print(f'Total Monthly Income: ${facts.get("total_monthly_income") or "N/A"}')
    print(f'Income Sources: {len(facts.get("income_sources", []))}')
    for src in facts.get('income_sources', []):
        amt = src['raw_amount']
        print(f'  - {src["type"]}: ${amt}/{src["frequency"]} -> ${src["monthly_amount"]}/mo')

    if facts.get('custody_info'):
        print(f'Custody: {facts["custody_info"]}')

    if facts.get('housing_instability'):
        print(f'Housing Instability: {facts["housing_instability"]}')

    deductions = {k:v for k,v in facts.get('potential_deductions', {}).items() if v is not None}
    if deductions:
        print(f'Deductions: {deductions}')

    if facts.get('contradictions_detected'):
        print(f'Contradictions: {[c["description"] for c in facts["contradictions_detected"]]}')

    print(f'\nDecision: {decision["current_status"]} (conf: {decision["confidence"]})')
    print(f'Limit: ${decision["income_limit"]} for HH of {decision["household_size"]}')
