import os
import shutil
import argparse

UNWANTED_DIRS = {
    "__pycache__",
    "venv",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

UNWANTED_FILES = {
    ".DS_Store",
}

UNWANTED_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
}

def clean_project(root_path: str, dry_run: bool = True):
    removed_dirs = []
    removed_files = []

    for root, dirs, files in os.walk(root_path, topdown=True):
        # Modify dirs in-place to prevent walking into deleted folders
        for d in list(dirs):
            if d in UNWANTED_DIRS:
                full_path = os.path.join(root, d)
                removed_dirs.append(full_path)

                if not dry_run:
                    shutil.rmtree(full_path, ignore_errors=True)

                dirs.remove(d)

        for f in files:
            if f in UNWANTED_FILES or os.path.splitext(f)[1] in UNWANTED_EXTENSIONS:
                full_path = os.path.join(root, f)
                removed_files.append(full_path)

                if not dry_run:
                    try:
                        os.remove(full_path)
                    except FileNotFoundError:
                        pass

    return removed_dirs, removed_files


def main():
    parser = argparse.ArgumentParser(
        description="Remove Python unwanted files/folders (__pycache__, venv, .venv, etc.)"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=os.getcwd(),
        help="Root directory (default: current directory)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Actually delete files (without this flag, it's a dry run)",
    )

    args = parser.parse_args()
    root_path = os.path.abspath(args.path)
    dry_run = not args.force

    print(f"{'Dry run' if dry_run else 'Deleting'} in: {root_path}\n")

    dirs, files = clean_project(root_path, dry_run=dry_run)

    if dirs:
        print("Directories:")
        for d in dirs:
            print(f"  {d}")

    if files:
        print("\nFiles:")
        for f in files:
            print(f"  {f}")

    if dry_run:
        print("\nNothing deleted. Run again with --force to remove these items.")
    else:
        print("\nCleanup complete.")


if __name__ == "__main__":
    main()
import os
import shutil
import argparse

UNWANTED_DIRS = {
    "__pycache__",
    "venv",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

UNWANTED_FILES = {
    ".DS_Store",
}

UNWANTED_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
}

def clean_project(root_path: str, dry_run: bool = True):
    removed_dirs = []
    removed_files = []

    for root, dirs, files in os.walk(root_path, topdown=True):
        # Modify dirs in-place to prevent walking into deleted folders
        for d in list(dirs):
            if d in UNWANTED_DIRS:
                full_path = os.path.join(root, d)
                removed_dirs.append(full_path)

                if not dry_run:
                    shutil.rmtree(full_path, ignore_errors=True)

                dirs.remove(d)

        for f in files:
            if f in UNWANTED_FILES or os.path.splitext(f)[1] in UNWANTED_EXTENSIONS:
                full_path = os.path.join(root, f)
                removed_files.append(full_path)

                if not dry_run:
                    try:
                        os.remove(full_path)
                    except FileNotFoundError:
                        pass

    return removed_dirs, removed_files


def main():
    parser = argparse.ArgumentParser(
        description="Remove Python unwanted files/folders (__pycache__, venv, .venv, etc.)"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=os.getcwd(),
        help="Root directory (default: current directory)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Actually delete files (without this flag, it's a dry run)",
    )

    args = parser.parse_args()
    root_path = os.path.abspath(args.path)
    dry_run = not args.force

    print(f"{'Dry run' if dry_run else 'Deleting'} in: {root_path}\n")

    dirs, files = clean_project(root_path, dry_run=dry_run)

    if dirs:
        print("Directories:")
        for d in dirs:
            print(f"  {d}")

    if files:
        print("\nFiles:")
        for f in files:
            print(f"  {f}")

    if dry_run:
        print("\nNothing deleted. Run again with --force to remove these items.")
    else:
        print("\nCleanup complete.")


if __name__ == "__main__":
    main()
