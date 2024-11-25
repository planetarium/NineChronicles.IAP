import csv
import sys


def add_thor_path(input_path: str, output_path: str):
    header = None
    processed_data = []
    with open(input_path, "r") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0:
                header = row
                continue

            processed_data.append(row)
            if row[0].endswith("_PATH"):  # Add thor path
                data = []
                for d in row:
                    prefix, *suffix = d.split(".")
                    if suffix:
                        data.append(f"{prefix}_THOR.{'.'.join(suffix)}")
                    elif prefix:
                        data.append(f"{prefix}_THOR")
                    else:
                        data.append(prefix)
                processed_data.append(data)
    print(f"Processed with {input_path.split('/')[-1]}")

    with open(output_path, "w") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(processed_data)
    print(f"Write processed data to {output_path}")


if __name__ == "__main__":
    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else input_path
    add_thor_path(input_path, output_path)
