#!/usr/bin/env python3
"""Harpenden Weather Camera 2026-11-12 V46-RC2"""
from loader import load_runtime
def main():
    runtime=load_runtime()
    return runtime["main"]()
if __name__ == "__main__":
    main()
