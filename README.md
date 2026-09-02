# Data Broker Opt-Out (macOS)

A DeleteMe-style privacy tool for **macOS 10.10 and up**. It prepares, guides the
submission of, and tracks **personal-data deletion / opt-out requests** to
data-broker sites (people-search sites, background-check sites, marketing data
brokers). Works with **up to 5 people**.

- Pure Python **standard library** — Tkinter GUI + a CLI. No pip installs.
- All data stays **on your Mac**, under
  `~/Library/Application Support/Data Broker Opt-Out/`.
- Ships with a catalogue of ~36 real broker sites and their opt-out routes, with
  **manual** and **automatic (monthly)** catalogue updates.

---

## What it does / doesn't do

| Does | Does not |
|---|---|
| Store up to 5 people's identity details locally | Send any email by itself |
| Keep a catalogue of broker opt-out URLs, emails, phones, mailing addresses, and step-by-step instructions | Submit web forms or solve CAPTCHAs |
| Generate a legally-grounded request (CCPA/CPRA, GDPR Art. 17/21, or a generic US-state request) per person per broker | Give legal advice |
| Open the broker's opt-out page and an **email draft** for you to review and send | Guarantee a broker complies |
| Track status of every request and flag follow-ups | Upload anything anywhere |
| Update the broker list on demand and once a month | |

The "prepare, you send" design is deliberate: unattended bulk submissions to
hundreds of third parties get flagged as abuse and rejected. This tool gives you
the statute, the wording, the contact, a paper trail, and the bookkeeping.

---

## Requirements

- macOS 10.10+
- **Python 3 with Tkinter.** The version at `/usr/bin/python3` works for the CLI.
  For the GUI, use a Python that bundles a current Tk — the
  [python.org macOS installer](https://www.python.org/downloads/macos/)
  (supports macOS 10.9+) or Homebrew's `python-tk`.

Check Tk:

```bash
python3 -m tkinter
```

---

## Run

```bash
cd data-broker-optout

# GUI
python3 -m dbopt
#   or
./run.py

# CLI
python3 -m dbopt.cli --help
```

Optional double-clickable app bundle (does not embed Python):

```bash
bash scripts/make-app.sh
open "dist/Data Broker Opt-Out.app"
```

---

## Using the app

1. **People tab** — add up to 5 people. For each: name (+ aliases/maiden names),
   emails (needed for the confirmation links brokers send), phones, and one or
   more addresses (`street | city | state | zip | from_year | to_year`, one per
   line). The tab tells you when a profile has enough to be "verifiable".

2. **Brokers tab** — browse the catalogue. Select a site to see its method,
   confirmation type, contacts, and instructions. Buttons open the opt-out page
   or a blank privacy email. You can **Add / Edit / Delete** entries; your edits
   are marked and preserved across monthly updates.

3. **Requests tab** — pick a person and a legal basis. For each broker row:
   - paste the **listing URL(s)** for that person on that site (optional but
     makes requests far more effective), then **Save listing URLs**;
   - click **Prepare request** — this writes a review-ready `.eml` draft to the
     `outbox/` folder, opens the broker's opt-out page, and (for email-based
     brokers) opens the draft in Mail. **You** review and press Send, or paste
     the text (**Copy email text**) into the broker's web form;
   - after submitting, mark the row **Submitted** → **Awaiting confirm** →
     **Removed** (or **Rejected**). Submitting auto-schedules a follow-up based
     on the broker's typical turnaround.
   A progress bar shows "N of M sites confirmed removed" for that person.

4. **Updates tab** — see below.

---

## Broker-list updates

### Manual

- **Updates tab → "Check for updates now (manual)"**, or
- `python3 -m dbopt.cli update --force`

### Automatic — once per month

A `launchd` agent runs `python3 -m dbopt.cli update` on the 1st of each month at
10:00 local time.

Install it:

```bash
bash scripts/install-monthly-update.sh          # day 1, 10:00
bash scripts/install-monthly-update.sh 1 9       # day 1, 09:00
#   or, from the GUI: Updates tab → "Install monthly auto-update (launchd)"
```

Remove it:

```bash
bash scripts/uninstall-monthly-update.sh
```

Verify / inspect:

```bash
launchctl list | grep databrokeroptout
python3 -m dbopt.cli log
```

The agent plist is written to
`~/Library/LaunchAgents/com.local.databrokeroptout.monthlyupdate.plist`
(reference template: `scripts/…​.plist.template`). Only Day/Hour/Minute are
pinned, so it repeats every month. Output goes to the app's `logs/` folder.

### Update source

Set **Update source URL** on the Updates tab to any HTTPS URL returning JSON in
the same shape as [`data/brokers.seed.json`](data/brokers.seed.json). Merge rules:

- new broker id → **added**
- existing entry you have **not** edited → factual fields refreshed from remote
- existing entry you **have** edited → left alone (only `last_verified` bumps)
- broker only in your local list → **kept**

Payloads that aren't a `{"brokers": [...]}` object, are empty, or have entries
missing `id` / `name` / `opt_out_url` / `method` are **rejected** and the current
catalogue is left untouched. Every run is logged. With **no** URL configured the
bundled seed list is used and nothing is fetched.

There is no public feed already in this schema, so you host your own. Two ways:

**a) Quick — a Gist you edit by hand**

```bash
gh gist create --desc "my data-broker list" data/brokers.seed.json
# open the gist, click "Raw", paste that URL into the app
```

**b) Auto-tracked — this repo's builder + GitHub Action**

`tools/build_broker_list.py` merges the curated seed list (authoritative) with
the community list [brianreumere/data-brokers](https://github.com/brianreumere/data-brokers)
— the seed wins on curated fields (privacy email/phone, mailing address,
hand-written instructions, verified opt-out URL); the community list only **adds**
brokers and annotates any whose opt-out it reports broken. Output is validated
against the app's own rules before it's written.

```bash
python3 -m pip install -r tools/requirements.txt
python3 tools/build_broker_list.py -o brokers.json      # ~75 brokers
python3 tools/build_broker_list.py --check              # dry run, just the summary
```

`.github/workflows/update-broker-list.yml` runs that on the 1st of each month
(and on demand) and commits `brokers.json`. Once the repo is on GitHub:

```bash
git init && git add -A && git commit -m "initial"
gh repo create data-broker-optout --private --source=. --push
```

then set the app's **Update source URL** to:

```
https://raw.githubusercontent.com/<your-user>/data-broker-optout/main/brokers.json
```

To add more sources later, extend `build_broker_list.py` (e.g. the
California/Vermont registries, or yaelwrites/Big-Ass-Data-Broker-Opt-Out-List).

---

## CLI reference

```
python3 -m dbopt.cli update [--force]         # fetch + merge (respects monthly cadence)
python3 -m dbopt.cli status                   # config + per-person progress
python3 -m dbopt.cli brokers                  # list catalogue
python3 -m dbopt.cli people                   # list configured people
python3 -m dbopt.cli generate --person NAME [--broker ID] [--law CCPA|GDPR|US-STATE-GENERIC]
python3 -m dbopt.cli install-monthly [--day 1] [--hour 10] [--run-now]
python3 -m dbopt.cli uninstall-monthly
python3 -m dbopt.cli log
python3 -m dbopt.cli gui
```

`generate` only writes drafts to `outbox/`. It never sends.

---

## Files

```
data-broker-optout/
├── dbopt/
│   ├── gui.py          Tkinter app (People / Brokers / Requests / Updates / About)
│   ├── cli.py          command line + launchd install/uninstall
│   ├── models.py       Profile (max 5), Address, Settings
│   ├── brokers.py      catalogue load / save / validate / merge
│   ├── templates.py    CCPA / GDPR / US-state request text builders
│   ├── engine.py       request lifecycle, .eml drafting, status tracking
│   ├── updater.py      manual + monthly update logic
│   └── storage.py      ~/Library/Application Support paths, atomic JSON
├── data/brokers.seed.json     bundled broker catalogue (authoritative source)
├── tools/
│   ├── build_broker_list.py   merge seed + community list -> brokers.json
│   └── requirements.txt        PyYAML (build-time only)
├── .github/workflows/update-broker-list.yml   monthly rebuild + commit of brokers.json
├── scripts/            make-app.sh, make-dmg.sh, install/uninstall-monthly-update.sh
├── setup.py            py2app standalone build
├── tests/test_core.py  stdlib self-test  (python3 tests/test_core.py)
├── run.py              GUI launcher
└── Makefile            run · cli · test · app · install-monthly · update · status
```

Data lives outside the source tree, so updating the code never touches your
people, requests, or catalogue edits.

---

## Packaging a `.dmg`

Two steps: build the `.app`, then wrap it.

### 1. Build the `.app`

**Thin bundle** — tiny, but the recipient needs a python.org/Homebrew Python 3 with Tk:

```bash
bash scripts/make-app.sh          # -> dist/Data Broker Opt-Out.app  (~200 KB)
```

**Standalone bundle** — embeds Python + Tk, runs on a clean Mac (~40–60 MB):

```bash
python3 -m pip install --user py2app
python3 setup.py py2app           # -> dist/Data Broker Opt-Out.app
```

Build py2app on the **oldest macOS you want to support** — the bundle's floor is
roughly the build machine's OS. Building on an Apple-Silicon Mac produces an
arm64 app; use an Intel Mac (or `arch -x86_64`) for a universal/Intel build.

### 2. Wrap it in a `.dmg`

```bash
bash scripts/make-dmg.sh          # -> "dist/Data Broker Opt-Out <version>.dmg"
```

This stages the app plus an `/Applications` symlink and runs `hdiutil create`
(compressed `UDZO`). No third-party tools. For a fancier window (background
image, icon positions) install `create-dmg` (`brew install create-dmg`) and swap
the `hdiutil` call — the layout is identical.

### 3. Signing & notarization (optional, for distribution)

Unsigned: recipients right-click the app → **Open** once to get past Gatekeeper.
To avoid that you need an Apple Developer ID ($99/yr):

```bash
# sign the app (hardened runtime)
codesign --deep --force --options runtime --timestamp \
  --sign "Developer ID Application: YOUR NAME (TEAMID)" \
  "dist/Data Broker Opt-Out.app"

bash scripts/make-dmg.sh          # rebuild the dmg from the signed app

# notarize the dmg, then staple
xcrun notarytool submit "dist/Data Broker Opt-Out 1.0.0.dmg" \
  --apple-id you@example.com --team-id TEAMID --password APP_SPECIFIC_PW --wait
xcrun stapler staple "dist/Data Broker Opt-Out 1.0.0.dmg"
```

Ship the `.dmg`. Recipients drag the app to Applications.

---

## Accuracy & legal notes

- Opt-out URLs, emails, and processes **change frequently**. Each broker entry
  has a `last_verified` date — always confirm the current process on the
  broker's own privacy page before submitting.
- Some brokers (LexisNexis, CoreLogic) are partly FCRA-regulated; full
  suppression may require a permissible-purpose claim and ID. The templates ask
  them to delete everything not covered by a stated exemption.
- This is templates and organisation, **not legal advice**. Only submit requests
  for people who have authorised you to act for them.
