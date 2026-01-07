"""Test the 4 bug fixes with provided scenarios."""

from main import normalize_facts

test_scenarios = {
    'Bug 1 - Utility as expense': {
        'input': 'Receives $350/month child support, pays $120 electric',
        'expected_income': 350,
        'description': '$350 income, $120 NOT income'
    },
    'Bug 2 - Child support': {
        'input': 'Receives $350/month child support',
        'expected_income': 350,
        'description': 'Child support should be captured'
    },
    'Bug 3 - Multiple Social Security': {
        'input': 'Husband gets $1,100 Social Security, wife gets $950 Social Security',
        'expected_income': 2050,
        'description': '$2,050 total income from both'
    },
    'Bug 4 - Multiple hourly jobs': {
        'input': '$12/hour for 20 hours, plus $14/hour for 15 hours',
        'expected_income': 1948,  # (12*20 + 14*15) * 4.33 ≈ 1039 + 909 = 1948
        'description': '~$1,948/month total'
    },
    'Bug 4 - Full sentence': {
        'input': 'Works two part-time jobs: $12/hour for 20 hours at a warehouse, plus $14/hour for 15 hours at a restaurant',
        'expected_income': 1948,
        'description': '~$1,948/month total'
    }
}

print("=" * 70)
print("BUG FIX VERIFICATION TESTS")
print("=" * 70)

all_passed = True

for name, scenario in test_scenarios.items():
    print(f'\n{"-"*70}')
    print(f'TEST: {name}')
    print(f'Input: {scenario["input"][:80]}...' if len(scenario["input"]) > 80 else f'Input: {scenario["input"]}')
    print(f'Expected: {scenario["description"]}')
    print(f'{"-"*70}')

    facts = normalize_facts(scenario['input'])

    actual_income = facts.get('total_monthly_income') or 0
    expected_income = scenario['expected_income']

    # Allow 10% tolerance for rounding
    tolerance = expected_income * 0.10
    passed = abs(actual_income - expected_income) <= tolerance

    print(f'\nResult:')
    print(f'  Total Monthly Income: ${actual_income}')
    print(f'  Expected: ~${expected_income}')
    print(f'  Income Sources: {len(facts.get("income_sources", []))}')
    for src in facts.get('income_sources', []):
        hours = src.get('hours_per_week', '')
        hours_str = f' ({hours}hrs/wk)' if hours else ''
        print(f'    - {src["type"]}: ${src["raw_amount"]}/{src["frequency"]}{hours_str} -> ${src["monthly_amount"]}/mo')

    if passed:
        print(f'  STATUS: [PASS]')
    else:
        print(f'  STATUS: [FAIL] (off by ${abs(actual_income - expected_income)})')
        all_passed = False

print(f'\n{"="*70}')
print(f'SUMMARY: {"ALL TESTS PASSED" if all_passed else "SOME TESTS FAILED"}')
print(f'{"="*70}')
