from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cmaq_utils import find_cmaq_files, inspect_file, json_print


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect CMAQ NetCDF/IOAPI files.")
    parser.add_argument("--data-dir", type=Path, help="Folder containing CMAQ .ncf files.")
    parser.add_argument("--main", type=Path, help="Main CMAQ .ncf file.")
    parser.add_argument("--extra", type=Path, help="Optional CMAQ EXTRA file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    main_path = args.main
    extra_path = args.extra
    if args.data_dir:
        found_main, found_extra = find_cmaq_files(args.data_dir)
        main_path = main_path or found_main
        extra_path = extra_path or found_extra
    if not main_path:
        raise SystemExit("No main CMAQ file found. Provide --main or --data-dir.")

    files = {"main": inspect_file(main_path)}
    if extra_path:
        files["extra"] = inspect_file(extra_path)
    json_print(files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
