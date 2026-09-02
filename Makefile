PY ?= python3
export PYTHONPATH := $(CURDIR)

.PHONY: run cli test app install-monthly uninstall-monthly update status clean

run:            ## open the GUI
	$(PY) -m dbopt

cli:            ## show CLI help
	$(PY) -m dbopt.cli --help

test:           ## run the self-test
	$(PY) -m pytest -q tests || $(PY) tests/test_core.py

app:            ## build dist/Data Broker Opt-Out.app
	bash scripts/make-app.sh

install-monthly:   ## install launchd monthly auto-update
	bash scripts/install-monthly-update.sh

uninstall-monthly:
	bash scripts/uninstall-monthly-update.sh

update:         ## force a broker-list update now
	$(PY) -m dbopt.cli update --force

status:
	$(PY) -m dbopt.cli status

clean:
	find . -name __pycache__ -type d -exec rm -rf {} + ; rm -rf dist
