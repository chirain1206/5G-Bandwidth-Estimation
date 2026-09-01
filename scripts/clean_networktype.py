import pandas as pd
import argparse
import os

def clean_network_type_unified(input_file: str, output_file: str, column_name: str = 'Network Type'):
    """
    Loads a CSV file and performs unified cleanup on the Network Type column,
    replacing both '5G (NSA)' and '5G+ (mmWave)' entries.
    """
    print("="*50)
    print(f"Starting unified cleanup on column: '{column_name}'")
    
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' not found.")
        return

    try:
        df = pd.read_csv(input_file)
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        return

    if column_name not in df.columns:
        print(f"Error: Column '{column_name}' not found. Available columns: {list(df.columns)}")
        return

    # Convert column to string type to safely handle replacements
    df[column_name] = df[column_name].astype(str)
    
    # --- Replacement 1: 5G (NSA) -> 5G ---
    search_1 = '5G (NSA)'
    replace_1 = '5G'
    count_1 = (df[column_name] == search_1).sum()
    df[column_name] = df[column_name].str.replace(search_1, replace_1, regex=False)
    
    # --- Replacement 2: 5G+ (mmWave) -> 5G+ ---
    search_2 = '5G+ (mmWave)'
    replace_2 = '5G+'
    count_2 = (df[column_name] == search_2).sum()
    df[column_name] = df[column_name].str.replace(search_2, replace_2, regex=False)

    print(f"✅ Cleanup Report:")
    print(f"  - Replaced '{count_1}' instances of '{search_1}'.")
    print(f"  - Replaced '{count_2}' instances of '{search_2}'.")
    
    # Save the modified DataFrame
    df.to_csv(output_file, index=False)
    print(f"Cleaned data successfully saved to: {output_file}")
    print("="*50)


def main():
    parser = argparse.ArgumentParser(description="Clean up Network Type column in CSV data.")
    parser.add_argument("input_file", type=str, help="Path to the original CSV file.")
    parser.add_argument("output_file", type=str, help="Path to save the cleaned CSV file.")
    parser.add_argument("--column", type=str, default="Network Type", 
                        help="Name of the column to perform the cleanup on (Default: 'Network Type').")
    
    args = parser.parse_args()
    clean_network_type_unified(args.input_file, args.output_file, args.column)


if __name__ == "__main__":
    main()