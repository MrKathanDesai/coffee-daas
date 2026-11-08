"""
Step 1 of the DaaS project: build the database.

Reads the CQI Arabica coffee quality dataset (CSV), cleans it, and loads it
into a SQLite database file `coffee.db` with one table: `coffee`.

Run:  python load_data.py
"""
import os
import re
import sqlite3
import urllib.request

import pandas as pd

CSV_PATH = os.path.join("data", "arabica_data_cleaned.csv")
CSV_URL = ("https://raw.githubusercontent.com/jldbc/coffee-quality-database/"
           "master/data/arabica_data_cleaned.csv")
DB_PATH = os.environ.get("DB_PATH", "coffee.db")


def get_csv():
    """Use the local copy; download it once if it is missing."""
    if not os.path.exists(CSV_PATH):
        os.makedirs("data", exist_ok=True)
        print(f"Downloading dataset from {CSV_URL} ...")
        urllib.request.urlretrieve(CSV_URL, CSV_PATH)
    return pd.read_csv(CSV_PATH)


def first_year(value):
    """'2013/2014', 'March 2010', '2017 / 2018' -> 2013, 2010, 2017."""
    m = re.search(r"(19|20)\d{2}", str(value))
    return int(m.group(0)) if m else None


def clean(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "country":           df["Country.of.Origin"].str.strip(),
        "region":            df["Region"].str.strip().str.title(),
        "farm_name":         df["Farm.Name"].str.strip(),
        "variety":           df["Variety"].str.strip(),
        "processing_method": df["Processing.Method"].str.strip(),
        "altitude_m":        (df["altitude_low_meters"] + df["altitude_high_meters"]) / 2,
        "harvest_year":      df["Harvest.Year"].apply(first_year),
        "aroma":             df["Aroma"],
        "flavor":            df["Flavor"],
        "aftertaste":        df["Aftertaste"],
        "acidity":           df["Acidity"],
        "body":              df["Body"],
        "balance":           df["Balance"],
        "sweetness":         df["Sweetness"],
        "total_cup_points":  df["Total.Cup.Points"],
        "moisture":          df["Moisture"],
    })

    # Data-quality fixes
    out = out[out["total_cup_points"] > 0]                       # one row has a score of 0
    bad_alt = (out["altitude_m"] < 100) | (out["altitude_m"] > 3500)
    out.loc[bad_alt, "altitude_m"] = None                        # typos like 190164 m
    out["altitude_m"] = out["altitude_m"].round(0)
    out["harvest_year"] = out["harvest_year"].astype("Int64")
    out = out.where(pd.notnull(out), None)

    out = out.reset_index(drop=True)
    out.insert(0, "id", out.index + 1)
    return out


def build_db(df: pd.DataFrame):
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE coffee (
            id                INTEGER PRIMARY KEY,
            country           TEXT,
            region            TEXT,
            farm_name         TEXT,
            variety           TEXT,
            processing_method TEXT,
            altitude_m        REAL,
            harvest_year      INTEGER,
            aroma             REAL,
            flavor            REAL,
            aftertaste        REAL,
            acidity           REAL,
            body              REAL,
            balance           REAL,
            sweetness         REAL,
            total_cup_points  REAL,
            moisture          REAL
        )""")
    df.to_sql("coffee", con, if_exists="append", index=False)
    # Indexes on the columns clients filter and sort by
    con.execute("CREATE INDEX idx_country ON coffee(country)")
    con.execute("CREATE INDEX idx_process ON coffee(processing_method)")
    con.execute("CREATE INDEX idx_score   ON coffee(total_cup_points)")
    con.commit()

    n = con.execute("SELECT COUNT(*) FROM coffee").fetchone()[0]
    c = con.execute("SELECT COUNT(DISTINCT country) FROM coffee").fetchone()[0]
    con.close()
    print(f"Created {DB_PATH}: {n} rows, {len(df.columns)} columns, {c} countries")


if __name__ == "__main__":
    raw = get_csv()
    print(f"Raw dataset: {raw.shape[0]} rows x {raw.shape[1]} columns")
    build_db(clean(raw))
