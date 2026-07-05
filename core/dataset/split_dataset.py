import csv
import os
import time
import argparse
import sys

# --- FIX FOR LARGE FIELDS ---
# Increase the maximum field size to handle massive text blocks (like code snippets).
# We use a loop to safely find the maximum allowed integer for your specific operating system.
maxInt = sys.maxsize
while True:
    try:
        csv.field_size_limit(maxInt)
        break
    except OverflowError:
        maxInt = int(maxInt / 10)


# ----------------------------

def split_csv(input_filepath, rows_per_file=1000):
    # Check if the file actually exists before starting
    if not os.path.exists(input_filepath):
        print(f"Error: The file '{input_filepath}' was not found.")
        return

    # 1. Extract the base file name
    base_name = os.path.splitext(os.path.basename(input_filepath))[0]

    # Set the output directory to the base file name
    output_directory = base_name
    os.makedirs(output_directory, exist_ok=True)

    print(f"Splitting '{input_filepath}' into chunks of {rows_per_file} rows...")

    # 2. Open the large source CSV
    with open(input_filepath, 'r', encoding='utf-8') as source_file:
        reader = csv.reader(source_file)

        # Extract the header so we can add it to every new file
        try:
            header = next(reader)
        except StopIteration:
            print("The input file is empty.")
            return

        file_number = 1
        current_row_count = 0
        output_file = None
        writer = None

        # 3. Iterate through the rows and split them
        for row in reader:
            # If we are at the start of a new file, open it and write the header
            if current_row_count == 0:
                time.sleep(0.001)  # Guarantee strictly unique timestamps
                timestamp_ms = int(time.time() * 1000)

                output_filename = os.path.join(output_directory, f"{base_name}_{timestamp_ms}.csv")
                output_file = open(output_filename, 'w', encoding='utf-8', newline='')
                writer = csv.writer(output_file)
                writer.writerow(header)

            # Write the data row
            writer.writerow(row)
            current_row_count += 1

            # If we hit the row limit, close the file and reset the counter
            if current_row_count == rows_per_file:
                output_file.close()
                print(f"Saved: {output_filename}")
                current_row_count = 0
                file_number += 1

        # 4. Close the final file if it has leftover rows
        if output_file and not output_file.closed:
            output_file.close()
            print(f"Saved: {output_filename}")

    print(f"\nSuccess! All files have been saved in the '{output_directory}' folder.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Split a large CSV file into smaller files with timestamps.")

    parser.add_argument(
        '--filename',
        type=str,
        required=True,
        help="The exact path or name of the CSV file you want to split."
    )

    parser.add_argument(
        '--rows',
        type=int,
        default=1000,
        help="Number of rows per file (default is 1000)."
    )

    args = parser.parse_args()

    split_csv(input_filepath=args.filename, rows_per_file=args.rows)