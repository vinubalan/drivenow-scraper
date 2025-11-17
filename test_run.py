#!/usr/bin/env python3
"""Test script to run scraper and capture errors."""
import sys
import traceback
from main import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nERROR: {str(e)}")
        traceback.print_exc()
        sys.exit(1)

