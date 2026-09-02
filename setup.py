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
    "packages": ["dbopt"],
    "includes": ["tkinter", "tkinter.ttk", "tkinter.messagebox"],
    "plist": {
        "CFBundleName": "Data Broker Opt-Out",
        "CFBundleDisplayName": "Data Broker Opt-Out",
        "CFBundleIdentifier": "com.local.databrokeroptout",
        "CFBundleVersion": dbopt.__version__,
        "CFBundleShortVersionString": dbopt.__version__,
        "LSMinimumSystemVersion": "10.10",
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
