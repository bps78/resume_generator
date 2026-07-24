# Resume/Cover-Letter Generator

## Structure
```
data/experience.json       <- source of truth: full bank of your experience
templates/resume.tex.jinja       <- LaTeX resume template (Jinja2 delimiters: \VAR{}, \BLOCK{})
templates/cover_letter.tex.jinja <- LaTeX cover letter template
scripts/build.py                 <- renders a tailored.json into .tex, compiles to PDF
jobs/<slug>/tailored.json        <- per-job selection file (Claude generates this)
jobs/<slug>/resume.pdf           <- output
```

## Requirements
- Python 3 with `jinja2` (`pip install jinja2`)
- A LaTeX distribution with `latexmk` + `pdflatex` on PATH (e.g. TeX Live / MacTeX)

## Usage
```bash
python3 scripts/build.py resume jobs/acme-corp-swe/tailored.json
python3 scripts/build.py cover  jobs/acme-corp-swe/cover_tailored.json
```

## Workflow with Claude
1. Give Claude the repo (or paste `data/experience.json` + the job description).
2. Claude reads your experience bank + the JD, and writes a new
   `jobs/<company-slug>/tailored.json` (and `cover_tailored.json`) selecting/
   ordering/rewriting only what belongs in `tailored.json` — see the schema
   documented at the top of `scripts/build.py`.
3. Run `build.py` to render + compile the PDF.
4. `data/experience.json` itself should rarely change — treat it as your
   permanent bullet bank. Add to it over time as you gain new experience.

See the schema docstring at the top of `scripts/build.py` for exact field
definitions.
