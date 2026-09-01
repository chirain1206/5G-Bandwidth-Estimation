import pandas as pd
import os
import argparse
import sys

def clean_id(val):
    """
    Cleans the Cell ID string.
    Removes decimal points if read as float (e.g. '123.0' -> '123').
    Returns stripped string.
    """
    s = str(val).strip()
    if s.endswith('.0'):
        return s[:-2]
    return s

def generate_cell_file_template(input_csv, output_csv):
    """
    Scans multiple columns in the input trace file for unique Cell IDs
    (combining App and NSG data) and generates a clean Cell File CSV template.
    """
    print(f"Reading trace file: {input_csv}")

    if not os.path.exists(input_csv):
        print(f"Error: File {input_csv} not found.")
        return

    try:
        # Read CSV. forcing all data to be object (string) to avoid float conversion issues
        df = pd.read_csv(input_csv, dtype=str)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    # Define invalid IDs that should be ignored
    invalid_ids = {'nan', 'N/A', '0', '2147483647', 'None', '', 'null'}

    # ---------------------------------------------------------
    # 1. Process LTE Cell IDs
    # ---------------------------------------------------------
    # List of possible column names for LTE
    lte_cols = ['LTE Cell ID', 'LTE_Cell_ID_NSG']
    unique_lte_ids = set()

    print("Scanning for LTE IDs...")
    for col in lte_cols:
        if col in df.columns:
            # Extract column, drop NA
            raw_ids = df[col].dropna()
            for val in raw_ids:
                cleaned = clean_id(val)
                if cleaned not in invalid_ids:
                    unique_lte_ids.add(cleaned)
            print(f"  - Scanned column '{col}'")
        else:
            print(f"  - Column '{col}' not found (skipping)")

    print(f"  > Total Unique LTE IDs found: {len(unique_lte_ids)}")

    # ---------------------------------------------------------
    # 2. Process 5G NR Cell IDs
    # ---------------------------------------------------------
    # List of possible column names for NR
    nr_cols = ['NR Cell ID', 'NR_Cell_ID_NSG']
    unique_nr_ids = set()

    print("Scanning for 5G NR IDs...")
    for col in nr_cols:
        if col in df.columns:
            raw_ids = df[col].dropna()
            for val in raw_ids:
                cleaned = clean_id(val)
                if cleaned not in invalid_ids:
                    unique_nr_ids.add(cleaned)
            print(f"  - Scanned column '{col}'")
        else:
            print(f"  - Column '{col}' not found (skipping)")

    print(f"  > Total Unique NR IDs found: {len(unique_nr_ids)}")

    # ---------------------------------------------------------
    # 3. Build Output Data
    # ---------------------------------------------------------
    output_data = []

    # Add LTE rows
    for cid in sorted(list(unique_lte_ids)):
        output_data.append({
            'ECI(LTE)/PCI(NR)': cid,
            'technology': 'LTE',
            'latitude': '',
            'longitude': '',
            'band': '',
            'bandwidth_mhz': ''
        })

    # Add NR rows
    for cid in sorted(list(unique_nr_ids)):
        output_data.append({
            'ECI(LTE)/PCI(NR)': cid,
            'technology': '5G_NR',
            'latitude': '',
            'longitude': '',
            'band': '',
            'bandwidth_mhz': ''
        })

    if not output_data:
        print("No valid Cell IDs found in any column.")
        return

    # Convert to DataFrame
    output_df = pd.DataFrame(output_data)

    # Save to CSV
    output_df.to_csv(output_csv, index=False)
    print("=" * 50)
    print(f"Success! Cell File Template generated: {output_csv}")
    print(f"Total entries: {len(output_df)}")
    print("Please manually fill in Lat/Lon/Band using CellMapper.")
    print("=" * 50)

def main():
    parser = argparse.ArgumentParser(description="Generate Cell File Template from Traces (App + NSG)")
    parser.add_argument("--input", type=str, default="bandwidth_traces.csv", 
                        help="Path to collected trace CSV")
    parser.add_argument("--output", type=str, default="cell_file_static.csv", 
                        help="Path to save the cell file template")
    
    args = parser.parse_args()
    generate_cell_file_template(args.input, args.output)

if __name__ == "__main__":
    main()