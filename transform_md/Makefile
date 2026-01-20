
PYTHON=python3

.PHONY: transform-md-test transform-md-transform

transform-md-test:
	$(PYTHON) -m pytest -v

# Usage (from repo root): make md-transform INDIR=../data/chats OUTDIR=../data/chats
transform-md-transform:
	@if [ -z "$(INDIR)" ] || [ -z "$(OUTDIR)" ]; then \
		echo "Usage: make md-transform INDIR=./in_dir OUTDIR=./out_dir"; exit 2; \
	fi
	$(PYTHON) transform_md.py --indir $(INDIR) --outdir $(OUTDIR)
