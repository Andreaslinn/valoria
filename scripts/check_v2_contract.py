"""Usage: python -m scripts.check_v2_contract --base-url https://actual-api

GET only. No login, freshness updates, valuation writes or synthetic production data.
"""
import argparse
import json
import httpx
from services.v2_contract import check_v2_contract, schema_fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-code-fingerprint")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        response = client.get(base + "/openapi.json")
        response.raise_for_status()
        schema = response.json()
        response = client.get(base + "/api/v1/health/capabilities")
        capabilities = response.json() if response.status_code == 200 else {}
    failures = check_v2_contract(schema, capabilities)
    if args.expected_code_fingerprint and capabilities.get("code_fingerprint") != args.expected_code_fingerprint:
        failures.append("Served deployment differs from intended code fingerprint")
    print(json.dumps({"schema_sha256": schema_fingerprint(schema), "capabilities": capabilities,
                      "failures": failures, "status": "FAILED" if failures else "PASSED"}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
