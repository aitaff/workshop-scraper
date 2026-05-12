# scrape.py

import os
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from supabase import create_client
import time

# Supabase credentials
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Scraper
start_url = "https://www.rent.nl/en/room/"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}
rows = []
scrape_time = datetime.now().isoformat()
page_number = 1

while page_number <= 20:
    url = f"https://www.rent.nl/en/room/?page={page_number}"
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    items = soup.select("div.relative.mb-12")

    if not items:
        break

    for item in items:
        address_node = item.select_one("p.font-bold.overflow-hidden")
        address = address_node.get_text(" ", strip=True) if address_node else None

        rent_node = item.select_one("p.font-bold.flex-none")
        rent = rent_node.get_text(strip=True) if rent_node else None

        surface_node = item.select_one("p.font-bold.leading-\\[22px\\]")
        surface = surface_node.get_text(strip=True) if surface_node else None

        rooms_node = item.find("p", class_="font-bold", string=lambda t: t and "room" in t.lower())
        rooms = rooms_node.get_text(strip=True) if rooms_node else None

        rows.append({
            "address":    address,
            "surface":    surface,
            "room_count": rooms,
            "rent_pm":    rent,
            "scraped_at": scrape_time,
        })

    page_number += 1
    time.sleep(1)

# Build dataframe
df = pd.DataFrame(rows)

# Clean rent
df["rent_eur"] = (
    df["rent_pm"]
      .str.replace(r"[^0-9.]", "", regex=True)
      .astype(float)
)
df = df.drop(columns=["rent_pm"])

# Clean room count
df["room_count"] = (
    df["room_count"]
      .str.replace(r"[^0-9]", "", regex=True)
      .replace("", pd.NA)
      .fillna(pd.NA)
      .astype("Int64")
)

# Rename columns
df = df.rename(columns={"surface": "surface_sqm"})

# Enrich
df["surface_tier"] = pd.cut(
    df["surface_sqm"].str.replace("m²", "").astype(float),
    bins=[0, 25, 50, 75, 100, float("inf")],
    labels=["Tiny (<25m²)", "Small (25-50m²)", "Medium (50-75m²)", "Large (75-100m²)", "XL (100m²+)"]
)

df["room_tier"] = df["room_count"].apply(
    lambda x: "Studio" if pd.isna(x) else
              "1 room" if x == 1 else
              "2 rooms" if x == 2 else
              "3 rooms" if x == 3 else
              "4+ rooms"
)

df["rent_tier"] = pd.cut(
    df["rent_eur"],
    bins=[0, 700, 1000, 1500, float("inf")],
    labels=["Budget (<€700)", "Mid (€700-1000)", "High (€1000-1500)", "Premium (€1500+)"]
)

df["rent_per_sqm"] = (
    df["rent_eur"] / df["surface_sqm"].str.replace("m²", "").astype(float)
).round(2)

# Alerts
#avg_rent = df["rent_eur"].mean()
#if avg_rent > 1500:
   # print(f"⚠️ ALERT: Average rent (€{avg_rent:.2f}) exceeded €1500!")
#else:
    #print(f"✅ Average rent is €{avg_rent:.2f} — within normal range")

# Append to CSV
filename = "rent_nl.csv"
if os.path.exists(filename):
    df.to_csv(filename, mode="a", header=False, index=False)
else:
    df.to_csv(filename, index=False)
print(f"Appended {len(df)} rows — total file now has historical data")

# Push to Supabase
insert_rows = []
for _, row in df.iterrows():
    insert_rows.append({
        "address":      str(row.get("address", "")),
        "surface_sqm":  str(row.get("surface_sqm", "")),
        "room_count":   None if pd.isna(row.get("room_count")) else int(row.get("room_count")),
        "rent_eur":     float(row.get("rent_eur", 0)),
        "surface_tier": str(row.get("surface_tier")),
        "room_tier":    str(row.get("room_tier")),
        "rent_tier":    str(row.get("rent_tier")),
        "rent_per_sqm": float(row.get("rent_per_sqm", 0)),
        "scraped_at":   scrape_time,
    })

result = supabase.table("rent_nl").insert(insert_rows).execute()
print(f"✅ Inserted {len(insert_rows)} rows into Supabase")
