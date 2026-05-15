.PHONY: help setup test test-verbose smoke clean lint examples

PYTHON ?= python

help:  ## List the available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

setup:  ## Create runtime directories and install deps
	mkdir -p inbox/costar/rent_comps inbox/costar/sales_comps inbox/costar/pipeline
	mkdir -p outputs
	$(PYTHON) -m pip install -r requirements.txt
	git submodule update --init --recursive

test:  ## Run the unittest suite
	$(PYTHON) -m unittest discover -s tests

test-verbose:  ## Run tests with verbose output
	$(PYTHON) -m unittest discover -s tests -v

smoke:  ## Run all five engines against their bundled example YAMLs
	$(PYTHON) -m scripts.underwriting examples/marina-apartments.yaml -o outputs/marina.xlsx
	$(PYTHON) -m scripts.underwriting.commercial    examples/example-office.yaml
	$(PYTHON) -m scripts.underwriting.commercial    examples/example-industrial.yaml
	$(PYTHON) -m scripts.underwriting.commercial    examples/example-retail.yaml
	$(PYTHON) -m scripts.underwriting.hospitality   examples/example-hotel.yaml
	$(PYTHON) -m scripts.underwriting.datacenter    examples/example-dc-wholesale.yaml
	$(PYTHON) -m scripts.underwriting.datacenter    examples/example-dc-colo.yaml
	$(PYTHON) -m scripts.underwriting.infrastructure examples/example-solar-ppa.yaml
	$(PYTHON) -m scripts.underwriting.infrastructure examples/example-wind.yaml
	$(PYTHON) -m scripts.underwriting.infrastructure examples/example-bess.yaml

lint:  ## Run ruff if installed (no-op when absent)
	@command -v ruff >/dev/null 2>&1 && ruff check scripts tests || echo "ruff not installed; skipping"

examples:  ## Quick: run only the Marina multifamily example
	$(PYTHON) -m scripts.underwriting examples/marina-apartments.yaml -o outputs/marina.xlsx

clean:  ## Remove generated outputs (does not touch inbox)
	rm -rf outputs/*.xlsx outputs/*.docx outputs/*.html
