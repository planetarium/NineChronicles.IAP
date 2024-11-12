import csv
import sys


def add_thor_path(input_path: str, output_path: str):
    header = None
    processed_data = []
    with open(input_path, "r") as f:
        reader = csv.reader(f)
        prev = None
        for i, r in enumerate(reader):
            if i == 0:
                header = r
                continue

            if i > 1 and i % 2 == 1:  # Add thor path
                data = []
                for p in prev:
                    prefix, *suffix = p.split(".")
                    if suffix:
                        data.append(f"{prefix}_THOR.{'.'.join(suffix)}")
                    elif prefix:
                        data.append(f"{prefix}_THOR")
                    else:
                        data.append(prefix)
                processed_data.append(data)
                processed_data.append(r)
            else:
                processed_data.append(r)
                prev = r
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
