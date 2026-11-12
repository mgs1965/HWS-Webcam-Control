#!/usr/bin/env python3
"""Harpenden Weather Camera 2026-11-11 V46-RC1"""
from loader import load_runtime
def main():
    runtime=load_runtime()
    return runtime["main"]()
if __name__ == "__main__":
    main()
