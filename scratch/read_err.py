import os
import sys

def print_err():
    with open('scratch/test_lead_output.txt', 'rb') as f:
        content = f.read().decode('utf-16le', errors='replace')
        # find the traceback part
        if 'Traceback' in content:
            print(content[content.index('Traceback'):])
        else:
            print(content)

if __name__ == "__main__":
    print_err()
