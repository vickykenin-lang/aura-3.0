"""Read-only Runway access/credit readiness. Never creates an image task."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def main():
    secret = os.getenv("RUNWAYML_API_SECRET", "").strip()
    report = {"credential_present": bool(secret), "organization_access_verified": False,
              "credits_sufficient_for_two_2k_images": False, "generation_verified": False,
              "image_tasks_created": 0, "model": "seedream5_pro",
              "maximum_pilot_credits": 18, "secret_values_recorded": False}
    if secret:
        request = Request("https://api.dev.runwayml.com/v1/organization",
                          headers={"Authorization": "Bearer " + secret,
                                   "X-Runway-Version": "2024-11-06"})
        try:
            with urlopen(request, timeout=30) as response:
                data = json.loads(response.read())
            credit = data.get("creditBalance")
            numeric = isinstance(credit, (int, float))
            report["credit_balance_state"] = (
                "UNKNOWN" if not numeric else "EMPTY" if credit <= 0 else
                "BELOW_PILOT_BUDGET" if credit < 18 else "SUFFICIENT")
            report["organization_access_verified"] = True
            report["credits_sufficient_for_two_2k_images"] = (
                isinstance(credit, (int, float)) and credit >= 18)
            report["status"] = ("ACCOUNT_READY_FOR_BOUNDED_PILOT" if
                                report["credits_sufficient_for_two_2k_images"] else
                                "INSUFFICIENT_OR_UNVERIFIED_CREDITS")
        except HTTPError as exc:
            report["status"] = "HTTP_" + str(exc.code)
        except Exception:
            report["status"] = "NETWORK_OR_RESPONSE_ERROR"
    else:
        report["status"] = "MISSING_RUNWAY_CREDENTIAL"
    path = Path("evaluation/results/runway-spatial-preflight.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "ACCOUNT_READY_FOR_BOUNDED_PILOT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
