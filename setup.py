"""Standalone macOS build with py2app (embeds Python + Tk).

    python3 -m pip install --user py2app
    python3 setup.py py2app          # -> dist/Data Broker Opt-Out.app
    bash scripts/make-dmg.sh         # -> dist/Data Broker Opt-Out <ver>.dmg

For the thin bundle that does NOT embed Python, use scripts/make-app.sh instead.
"""
from setuptools import setup

import dbopt

APP = ["run.py"]
DATA_FILES = [("data", ["data/brokers.seed.json"])]
OPTIONS = {
    "argv_emulation": False,
    "packages": ["dbopt", "certifi"],
    "includes": ["tkinter", "tkinter.ttk", "tkinter.messagebox"],
    "plist": {
        "CFBundleName": "Data Broker Opt-Out",
        "CFBundleDisplayName": "Data Broker Opt-Out",
        "CFBundleIdentifier": "com.local.databrokeroptout",
        "CFBundleVersion": dbopt.__version__,
        "CFBundleShortVersionString": dbopt.__version__,
        # Honest, not aspirational: this standalone bundle embeds whatever
        # Python built it (see the framework path py2app printed), and that
        # Python sets the real floor. A 3.13 framework build's floor is
        # macOS 10.13 - Apple's own python.org 3.13 installers require it.
        # For a lower floor (down to ~10.9), use scripts/make-app.sh (the thin
        # bundle) with an older python.org Python instead of this py2app build.
        "LSMinimumSystemVersion": "10.13",
        "NSHighResolutionCapable": True,
        # No network entitlement needed; the monthly update uses plain HTTPS.
    },
    # "iconfile": "assets/app.icns",   # add a .icns here if you make one
}

setup(
    app=APP,
    name="Data Broker Opt-Out",
    version=dbopt.__version__,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
