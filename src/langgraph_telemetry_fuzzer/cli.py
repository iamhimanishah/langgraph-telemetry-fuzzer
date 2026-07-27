"""CLI entry point.

The `ltf run` command (agent x scenario x corruption -> report) lands in
Milestone 6, once injectors, the adapter, and the grader exist. For now this
just confirms the package installs and the entry point resolves.
"""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="ltf")
    parser.parse_args()
    print("ltf: not implemented yet (see the roadmap in README.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
