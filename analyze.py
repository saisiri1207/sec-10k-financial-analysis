"""Turn SEC XBRL annual facts into a ratio dashboard, charts and an Excel workbook."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

FIRST_FY = 2016
raw = pd.read_csv("data/annual_facts.csv", dtype={"period_end": str, "filed": str})
raw["fy"] = raw.period_end.str[:4].astype(int)
# Fiscal year label = calendar year of the period end (P&G and Clorox close in June).


def as_first_reported(df):
    """Value from the first 10-K that reported each period (the filing for that year)."""
    first = df.sort_values("filed").groupby(["company", "metric", "period_end"], as_index=False).first()
    # if a company has two period ends in one calendar year (fiscal year change), keep the later one
    first = first.sort_values("period_end").groupby(["company", "metric", "fy"], as_index=False).last()
    return first.pivot_table(index=["company", "fy"], columns="metric", values="value", aggfunc="last")


def like_for_like_growth(df):
    """Revenue growth using current and prior year figures from the same 10-K, so
    divestitures and restatements are on one basis."""
    rev = df[df.metric == "revenue"].copy()
    out = []
    for (co, accn), g in rev.groupby(["company", "accession"]):
        g = g.sort_values("period_end")
        if len(g) < 2:
            continue
        cur, prev = g.iloc[-1], g.iloc[-2]
        # only use the filing that is the original 10-K for its latest period
        out.append({"company": co, "fy": cur.fy, "filed": cur.filed,
                    "revenue_growth_lfl": (cur.value / prev.value - 1) * 100})
    o = pd.DataFrame(out).sort_values("filed").groupby(["company", "fy"]).first()
    return o["revenue_growth_lfl"]


p = as_first_reported(raw)
ebit_proxy = p["pretax_income"] + p["interest_expense"]
p["operating_income_used"] = p["operating_income"].fillna(ebit_proxy)
p["ebit_is_proxy"] = p["operating_income"].isna() & ebit_proxy.notna()
p = p.join(like_for_like_growth(raw))
p = p[p.index.get_level_values("fy") >= FIRST_FY]

r = pd.DataFrame(index=p.index)
r["revenue_musd"] = p.revenue / 1e6
r["revenue_growth_pct"] = p.revenue_growth_lfl
r["gross_margin_pct"] = (1 - p.cogs / p.revenue) * 100
r["operating_margin_pct"] = p.operating_income_used / p.revenue * 100
r["net_margin_pct"] = p.net_income / p.revenue * 100
r["cash_conversion_x"] = p.operating_cash_flow / p.net_income
r["fcf_margin_pct"] = (p.operating_cash_flow - p.capex) / p.revenue * 100
r["dso_days"] = p.receivables / p.revenue * 365
r["dio_days"] = p.inventory / p.cogs * 365
r["dpo_days"] = p.payables / p.cogs * 365
r["cash_cycle_days"] = r.dso_days + r.dio_days - r.dpo_days
r["ebit_is_proxy"] = p.ebit_is_proxy
r = r.round(2)
r.to_csv("outputs/ratio_history.csv")

latest = r.reset_index().sort_values("fy").groupby("company").last()
five = r.reset_index()
summary = []
for co, g in five.groupby("company"):
    g = g.set_index("fy").sort_index()
    ly = g.index.max()
    base = g.loc[ly - 5] if ly - 5 in g.index else None
    summary.append({
        "company": co, "latest_fy": ly,
        "revenue_musd": g.loc[ly, "revenue_musd"],
        "avg_growth_5y_pct": g.loc[ly - 4:ly, "revenue_growth_pct"].mean(),
        "gross_margin_pct": g.loc[ly, "gross_margin_pct"],
        "gross_margin_change_5y_pts": g.loc[ly, "gross_margin_pct"] - base.gross_margin_pct,
        "operating_margin_pct": g.loc[ly, "operating_margin_pct"],
        "fcf_margin_pct": g.loc[ly, "fcf_margin_pct"],
        "avg_cash_conversion_5y_x": g.loc[ly - 4:ly, "cash_conversion_x"].mean(),
        "cash_cycle_days": g.loc[ly, "cash_cycle_days"],
        "cash_cycle_change_5y_days": g.loc[ly, "cash_cycle_days"] - base.cash_cycle_days,
    })
summary = pd.DataFrame(summary).sort_values("operating_margin_pct", ascending=False).round(2)
summary.to_csv("outputs/peer_dashboard.csv", index=False)

# Charts
rr = r.reset_index()
fig, ax = plt.subplots(figsize=(10, 5))
for co, g in rr.groupby("company"):
    ax.plot(g.fy, g.gross_margin_pct, marker="o", label=co)
ax.set_title("Gross margin by fiscal year (SEC 10-K XBRL)"); ax.set_ylabel("%"); ax.legend(fontsize=8)
plt.tight_layout(); plt.savefig("outputs/charts/gross_margin_trend.png", dpi=130); plt.close()

fig, ax = plt.subplots(figsize=(10, 5))
for co, g in rr[rr.fy >= 2019].groupby("company"):
    ax.plot(g.fy, g.revenue_growth_pct, marker="o", label=co)
ax.axhline(0, color="grey", lw=0.8)
ax.set_title("Revenue growth year over year, same 10-K basis"); ax.set_ylabel("%"); ax.legend(fontsize=8)
plt.tight_layout(); plt.savefig("outputs/charts/revenue_growth.png", dpi=130); plt.close()

fig, ax = plt.subplots(figsize=(10, 5))
s = summary.set_index("company")
x = range(len(s))
ax.bar([i - 0.2 for i in x], s.operating_margin_pct, width=0.4, label="Operating margin %")
ax.bar([i + 0.2 for i in x], s.fcf_margin_pct, width=0.4, label="Free cash flow margin %")
ax.set_xticks(list(x)); ax.set_xticklabels(s.index, rotation=15)
ax.set_title("Latest fiscal year: operating margin vs free cash flow margin"); ax.legend()
plt.tight_layout(); plt.savefig("outputs/charts/margin_vs_fcf.png", dpi=130); plt.close()

fig, ax = plt.subplots(figsize=(10, 5))
lt = latest[["dso_days", "dio_days", "dpo_days"]].copy()
lt["dpo_days"] = -lt["dpo_days"]
lt.columns = ["Receivable days (DSO)", "Inventory days (DIO)", "Payable days (DPO, shown negative)"]
lt.plot(kind="bar", stacked=True, ax=ax, color=["#4e79a7", "#59a14f", "#e15759"])
for i, v in enumerate(latest.cash_cycle_days):
    ax.text(i, latest.dso_days.iloc[i] + latest.dio_days.iloc[i] + 4, f"cycle {v:.0f} days", ha="center", fontsize=9)
ax.axhline(0, color="black", lw=0.8)
ax.set_title("Working capital days, latest fiscal year (DSO + DIO minus DPO)")
ax.set_ylabel("days"); ax.set_xlabel(""); plt.xticks(rotation=15)
plt.tight_layout(); plt.savefig("outputs/charts/working_capital_days.png", dpi=130); plt.close()

# Excel export
xlsx = "outputs/consumer_products_10k_analysis.xlsx"
with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
    summary.to_excel(w, sheet_name="Peer dashboard", index=False)
    r.reset_index().to_excel(w, sheet_name="Ratio history", index=False)
    (p.reset_index()[["company", "fy", "revenue", "cogs", "operating_income_used", "net_income",
                      "operating_cash_flow", "capex", "receivables", "inventory", "payables", "total_assets"]]
     ).to_excel(w, sheet_name="Source values USD", index=False)
wb = load_workbook(xlsx)
for ws in wb.worksheets:
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1F4E79")
        c.alignment = Alignment(wrap_text=True)
    for i, col in enumerate(ws.columns, 1):
        ws.column_dimensions[get_column_letter(i)].width = 18
    ws.freeze_panes = "B2"
wb.save(xlsx)

pd.set_option("display.width", 250)
print(summary.to_string(index=False))
print(r[r.ebit_is_proxy].index.tolist()[:3], "proxy rows:", int(r.ebit_is_proxy.sum()))
print(r.loc[(slice(None), slice(2021, 2026)), ["revenue_growth_pct", "gross_margin_pct", "operating_margin_pct"]].to_string())
