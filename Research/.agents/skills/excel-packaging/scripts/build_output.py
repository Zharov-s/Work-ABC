from pathlib import Path

FINAL = Path("output/mitino_target_companies_lpr_direct_contacts.xlsx")

if FINAL.exists():
    print(f"{FINAL} is the single workbook used by the project")
else:
    raise SystemExit(f"Missing final workbook: {FINAL}")
