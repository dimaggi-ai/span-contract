# Reproduction entry points. See README.md for what each target produces.
PY := .venv/bin/python

.PHONY: help venv test validate schema examples smoke-test clean

help:
	@echo "make venv      create the pinned virtual environment"
	@echo "make test      run the test suite, including the mutation tests"
	@echo "make validate  the validation registry and the list of what it declines"
	@echo "make schema    regenerate schema/span_contract.schema.json from the code"
	@echo "make examples  run every example envelope through the validator"
	@echo "make smoke-test  tests, registry, schema check and examples (<1 min)"
	@echo "make clean     remove build artifacts"

venv:
	python3.12 -m venv .venv
	.venv/bin/pip install --quiet --upgrade pip
	.venv/bin/pip install --quiet -e ".[dev]"

test:
	PYTHONPATH=src:validation $(PY) -m pytest tests/ -q

validate:
	$(PY) validation/validate_contract.py

schema:
	PYTHONPATH=src $(PY) -c "import json;from spancontract.schema import envelope_schema;\
	open('schema/span_contract.schema.json','w').write(json.dumps(envelope_schema(), indent=2)+'\n')"
	@echo "wrote schema/span_contract.schema.json"

examples:
	$(PY) examples/run_examples.py

smoke-test: test validate examples
	@echo "smoke test complete"

clean:
	rm -rf build dist src/*.egg-info .pytest_cache
