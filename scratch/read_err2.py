import os
import sys

def print_err():
    with open('scratch/test_lead_output.txt', 'rb') as f:
        content = f.read().decode('utf-16le', errors='replace')
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if 'sqlalchemy.exc.' in line or 'psycopg2.errors.' in line:
                print("FOUND EXCEPTION LINE:")
                print(line)
                break

if __name__ == "__main__":
    print_err()
