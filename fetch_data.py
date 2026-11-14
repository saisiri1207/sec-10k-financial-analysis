"""Download XBRL company facts from SEC EDGAR for a consumer products peer group and
flatten the annual 10-K values we need into data/annual_facts.csv.
SEC asks automated users to identify themselves with a User-Agent and stay under 10 requests per second."""
import datetime as dt
import json
import os
import time
import pandas as pd
import requests

HEADERS = {"User-Agent": "Sai Siri Bandaru bandarusaisiri1207@gmail.com"}
URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
COMPANIES = {
    "Procter & Gamble": 80424,
    "Colgate Palmolive": 21665,
    "Kimberly Clark": 55785,
    "Clorox": 21076,
    "Church & Dwight": 313927,
}
# Each metric lists XBRL tags in priority order; the first tag with a value for a year wins.
TAGS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "cogs": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "inventory": ["InventoryNet"],
    "payables": ["AccountsPayableCurrent", "AccountsPayableTradeCurrent"],
    "total_assets": ["Assets"],
    # used to rebuild operating income (EBIT) for filers that do not tag OperatingIncomeLoss
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating"],
}
DURATION = {"revenue", "cogs", "operating_income", "net_income", "operating_cash_flow", "capex",
            "pretax_income", "interest_expense"}


def annual_values(facts, tag, is_duration):
    node = facts["facts"].get("us-gaap", {}).get(tag)
    if not node:
        return {}
    out = {}
    for unit, items in node["units"].items():
        if unit != "USD":
            continue
        for it in items:
            if it.get("form") not in ("10-K", "10-K/A"):
                continue
            end = it["end"]
            if is_duration:
                days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(it["start"])).days
                if not 350 <= days <= 380:
                    continue
            out.setdefault(end, []).append({"val": it["val"], "filed": it["filed"], "accn": it["accn"]})
    return out


def main():
    os.makedirs("data/raw", exist_ok=True)  # raw JSON is large, so it is git ignored
    rows = []
    for name, cik in COMPANIES.items():
        r = requests.get(URL.format(cik=cik), headers=HEADERS, timeout=60)
        r.raise_for_status()
        facts = r.json()
        json.dump(facts, open(f"data/raw/CIK{cik:010d}.json", "w"))
        for metric, tags in TAGS.items():
            chosen = {}
            for tag in tags:
                for end, obs in annual_values(facts, tag, metric in DURATION).items():
                    chosen.setdefault(end, [{**o, "tag": tag} for o in obs])
            for end, obs in chosen.items():
                for v in obs:
                    rows.append({"company": name, "cik": cik, "metric": metric, "period_end": end,
                                 "value": v["val"], "tag": v["tag"], "accession": v["accn"], "filed": v["filed"]})
        print(name, "done")
        time.sleep(0.5)
    df = pd.DataFrame(rows).drop_duplicates().sort_values(["company", "metric", "period_end", "filed"])
    df.to_csv("data/annual_facts.csv", index=False)
    with open("data/PULL_DATE.txt", "w") as f:
        f.write(f"Pulled {dt.date.today().isoformat()} from https://data.sec.gov/api/xbrl/companyfacts/\n")
    print(len(df), "rows")


if __name__ == "__main__":
    main()
