"""
Test script for comprehensive fact extraction scenarios.
Run with: python test_scenarios.py
"""

import sys
import json

# Import the functions from main.py
from main import normalize_facts, generate_decision_map

def test_scenario(name: str, scenario: str):
    """Test a single scenario and print results."""
    print(f"\n{'='*70}")
    print(f"TEST: {name}")
    print(f"{'='*70}")
    print(f"Input: {scenario[:100]}..." if len(scenario) > 100 else f"Input: {scenario}")
    print("-" * 70)

    facts = normalize_facts(scenario)
    decision = generate_decision_map(facts)

    print(f"\nKey Extractions:")
    print(f"  Household Size: {facts['household_size']}")
    print(f"  Total Monthly Income: ${facts.get('total_monthly_income') or 'None'}")
    print(f"  Income Sources: {len(facts.get('income_sources', []))}")
    for source in facts.get('income_sources', []):
        print(f"    - {source['type']}: ${source['raw_amount']}/{source['frequency']} -> ${source['monthly_amount']}/month")

    if facts.get('custody_info'):
        print(f"  Custody Info: {facts['custody_info']}")

    if facts.get('housing_instability'):
        print(f"  Housing Instability: {facts['housing_instability']}")

    if facts.get('potential_deductions'):
        deductions = {k: v for k, v in facts['potential_deductions'].items() if v is not None}
        if deductions:
            print(f"  Potential Deductions: {deductions}")

    if facts.get('contradictions_detected'):
        print(f"  Contradictions: {facts['contradictions_detected']}")

    print(f"  Patterns Matched: {len(facts.get('patterns_matched', []))}/{facts.get('patterns_attempted', 0)}")
    print(f"  Data Quality Score: {facts.get('extraction_debug', {}).get('data_quality_score', 'N/A')}")

    print(f"\nDecision:")
    print(f"  Status: {decision['current_status']}")
    print(f"  Confidence: {decision['confidence']}")
    print(f"  Reason: {decision.get('reason', 'N/A')}")

    if decision.get('confidence_warnings'):
        print(f"  Warnings: {decision['confidence_warnings']}")

    return facts, decision


def run_all_tests():
    """Run all test scenarios."""

    scenarios = [
        (
            "1. Multiple income sources",
            "Makes $1,500 from job plus $800 Social Security"
        ),
        (
            "2. Frequency conversion (hourly)",
            "Earns $15/hour, works 30 hours/week"
        ),
        (
            "3. Custody situation",
            "Has 50/50 custody of 2 children"
        ),
        (
            "4. Housing instability",
            "Staying with friend, no lease"
        ),
        (
            "5. Deductions",
            "Pays $400/month childcare, $200 medical expenses"
        ),
        (
            "6. Contradictions",
            "Unemployed but makes $2,000/month"
        ),
        # Original test scenario
        (
            "7. Original test case",
            "Single adult, 58 years old. Works part-time at a grocery store, about 25 hours a week. Makes around $1,700 a month before taxes. Pays electric and gas separately, about $180 total. Rent is $950. No kids. No disability. Hasn't applied for LIHEAP yet. Lost SNAP last year because they said they made too much."
        ),
    ]

    results = []
    for name, scenario in scenarios:
        facts, decision = test_scenario(name, scenario)
        results.append({
            "name": name,
            "facts": facts,
            "decision": decision
        })

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    for r in results:
        income = r['facts'].get('total_monthly_income') or 'N/A'
        status = r['decision']['current_status']
        quality = r['facts'].get('extraction_debug', {}).get('data_quality_score', 'N/A')
        print(f"  {r['name']}: income=${income}, status={status}, quality={quality}")


if __name__ == "__main__":
    run_all_tests()
