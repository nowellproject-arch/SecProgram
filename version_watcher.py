import json
import time
from pathlib import Path


# ============================================================
# SETTINGS
# ============================================================

PROJECT_DIR = Path(__file__).resolve().parent
VERSION_FILE = PROJECT_DIR / "version.json"

WATCH_EXTENSIONS = {
    ".py",
    ".html",
    ".js",
    ".css",
    ".json"
}

IGNORE_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules"
}


# ============================================================
# VERSION FUNCTIONS
# ============================================================

def read_version():

    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        return float(data.get("version", "18.3"))

    except Exception:
        return 18.3


def write_version(version):

    data = {
        "version": f"{version:.1f}"
    }

    with open(
        VERSION_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=4
        )


def increase_version():

    current = read_version()

    new_version = round(
        current + 0.1,
        1
    )

    write_version(new_version)

    print(
        f"🔼 VERSION UPDATED: "
        f"{current:.1f} → {new_version:.1f}"
    )

    return new_version


# ============================================================
# GET FILES WE WANT TO WATCH
# ============================================================

def get_project_files():

    files = []

    for path in PROJECT_DIR.rglob("*"):

        if not path.is_file():
            continue

        # Ignore directories
        if any(
            ignored in path.parts
            for ignored in IGNORE_DIRS
        ):
            continue

        # Never watch version.json
        if path.resolve() == VERSION_FILE.resolve():
            continue

        if path.suffix.lower() in WATCH_EXTENSIONS:
            files.append(path)

    return files


# ============================================================
# CREATE INITIAL SNAPSHOT
# ============================================================

def create_snapshot():

    snapshot = {}

    for path in get_project_files():

        try:
            snapshot[str(path)] = (
                path.stat().st_mtime_ns
            )
        except FileNotFoundError:
            pass

    return snapshot


# ============================================================
# WATCH PROJECT
# ============================================================

def watch_project():

    print("")
    print("==========================================")
    print("   SecProgram Version Watcher")
    print("==========================================")
    print("")
    print(f"📁 Project: {PROJECT_DIR}")
    print(f"📄 Version : {VERSION_FILE}")
    print("")
    print("Watching:")
    print("  .py")
    print("  .html")
    print("  .js")
    print("  .css")
    print("  .json")
    print("")
    print("Ignored:")
    print("  .git")
    print("  .venv")
    print("  __pycache__")
    print("  node_modules")
    print("  version.json")
    print("")
    print("💾 Save a project file to increase the version.")
    print("Press CTRL+C to stop.")
    print("")


    snapshot = create_snapshot()


    while True:

        time.sleep(1)


        new_snapshot = create_snapshot()


        changed_files = []

        # Detect changed / new files
        for path, mtime in new_snapshot.items():

            old_mtime = snapshot.get(path)

            if old_mtime is None:
                changed_files.append(path)

            elif old_mtime != mtime:
                changed_files.append(path)


        # Detect deleted files
        deleted_files = set(snapshot) - set(new_snapshot)

        if deleted_files:

            for path in deleted_files:
                print(
                    f"🗑️ FILE DELETED: {path}"
                )


        # Process changes
        if changed_files:

            for path in changed_files:

                print(
                    f"💾 FILE SAVED: {path}"
                )

            increase_version()


        snapshot = new_snapshot


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:
        watch_project()

    except KeyboardInterrupt:

        print("")
        print("🛑 Version watcher stopped.")