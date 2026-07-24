#!/usr/bin/env python3
"""
build.py — Render a tailored resume (or cover letter) from the experience
data bank + a per-job selection file, then compile it to PDF with LaTeX.

USAGE
-----
    python3 scripts/build.py resume   jobs/acme-corp-swe/tailored.json
    python3 scripts/build.py cover    jobs/acme-corp-swe/tailored.json

This writes:
    jobs/acme-corp-swe/resume.tex   (or cover_letter.tex)
    jobs/acme-corp-swe/resume.pdf   (or cover_letter.pdf)

DATA MODEL
----------
data/experience.json   — the full bank of experience (source of truth,
                          never edited per-job). See that file's schema:
                          each section is a list of entries, each entry
                          has an "id" and a "bullets" list.

jobs/<slug>/tailored.json — one file per job application. Selects and
                          orders which entries/bullets to use, and
                          supplies the final summary text and (for cover
                          letters) the letter body. Claude generates this
                          file per job description; nothing here is
                          auto-tailored by the script itself — the script
                          only renders + compiles whatever selection it's
                          given.

TAILORED FILE SCHEMA (resume)
------------------------------
{
  "summary": "Final summary paragraph text to use as-is.",
  "personal_info_overrides": { "linkedin_url": "https://...", ... },
  "sections": ["work_experience", "research", "projects",
               "leadership", "education", "skills"],
  "work_experience": [
     {"id": "qbe_intern", "bullet_indices": [0, 1, 2]}
  ],
  "research": [ {"id": "oscar_sort_waste_analysis", "bullet_indices": [0, 2]} ],
  "projects": [ {"id": "march_madness_model", "bullet_indices": [0, 1]} ],
  "leadership": [ {"id": "sports_analytics_vp", "bullet_indices": [0]} ],
  "education": [ {"id": "uw_madison"} ],   // education entries used as-is
  "skills": {
     "Programming Languages": ["Python", "SQL", "PySpark"],
     "Frameworks & Libraries": ["Pandas", "Scikit-learn"]
  }
}

Any section/id omitted just doesn't appear on the resume. "bullet_indices"
selects + orders bullets from that entry's bullet bank in data/experience.json.

TAILORED FILE SCHEMA (cover letter)
------------------------------------
{
  "recipient": {"company": "Acme Corp", "hiring_manager": "Hiring Team"},
  "date": "July 23, 2026",
  "body_paragraphs": ["First paragraph...", "Second paragraph...", "..."]
}
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import jinja2

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
TEMPLATES_DIR = REPO_ROOT / "templates"


def load_bank(data_dir: Path) -> dict:
    """Merge every data/*.json file into a single bank dict. Each file is
    expected to contain one top-level key (e.g. work_experience, education,
    skills, personal_info, ...)."""
    bank = {}
    for path in sorted(data_dir.glob("*.json")):
        with open(path, "r", encoding="utf-8") as f:
            chunk = json.load(f)
        bank.update(chunk)
    return bank

# ---------------------------------------------------------------------------
# LaTeX-safe Jinja2 environment
# ---------------------------------------------------------------------------
# Default {{ }} / {% %} collide with LaTeX's own braces, so templates use
# \VAR{...}, \BLOCK{ ... }, and \#{ ... } instead (standard LaTeX+Jinja2
# convention).

LATEX_JINJA_ENV = jinja2.Environment(
    block_start_string=r"\BLOCK{",
    block_end_string="}",
    variable_start_string=r"\VAR{",
    variable_end_string="}",
    comment_start_string=r"\#{",
    comment_end_string="}",
    trim_blocks=True,
    lstrip_blocks=True,
    loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
)

_LATEX_ESCAPE_MAP = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}
_LATEX_ESCAPE_RE = re.compile("|".join(re.escape(k) for k in _LATEX_ESCAPE_MAP))


def latex_escape(value):
    """Escape LaTeX special characters in a string (applied to ALL data
    pulled from JSON before it reaches the template, so job-description
    text or resume content can never break compilation)."""
    if value is None:
        return ""
    text = str(value)
    return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_ESCAPE_MAP[m.group()], text)


LATEX_JINJA_ENV.filters["latex_escape"] = latex_escape


# ---------------------------------------------------------------------------
# Data loading + merging
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"error: file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def index_by_id(entries: list) -> dict:
    return {entry["id"]: entry for entry in entries if "id" in entry}


def build_date_range(entry: dict) -> str:
    start = entry.get("start_date", "")
    end = entry.get("end_date", "")
    if entry.get("status") == "incoming":
        return f"{start} - {end} (incoming)"
    return f"{start} - {end}" if (start or end) else ""


def select_bullets(bank_entry: dict, selection: dict) -> list:
    """Pick + order bullets from a bank entry's bullet list using the
    tailored file's bullet_indices (falls back to ALL bullets if omitted)."""
    all_bullets = bank_entry.get("bullets", [])
    indices = selection.get("bullet_indices")
    if indices is None:
        chosen = all_bullets
    else:
        chosen = [all_bullets[i] for i in indices]
    # escape at render time; bullets may be dicts ({"text": ..., "tags": ...})
    return [latex_escape(b["text"] if isinstance(b, dict) else b) for b in chosen]


def merge_experience_section(section_name: str, bank: dict, tailored: dict,
                              date_range=True) -> list:
    bank_entries = index_by_id(bank.get(section_name, []))
    tailored_entries = tailored.get(section_name, [])
    result = []
    for sel in tailored_entries:
        entry_id = sel.get("id")
        bank_entry = bank_entries.get(entry_id)
        if bank_entry is None:
            print(f"warning: '{entry_id}' not found in data/experience.json "
                  f"section '{section_name}' — skipping", file=sys.stderr)
            continue
        merged = {
            "title": bank_entry.get("title"),
            "company": bank_entry.get("company") or bank_entry.get("organization"),
            "organization": bank_entry.get("organization"),
            "location": bank_entry.get("location"),
            "date": bank_entry.get("date"),
            "bullets": select_bullets(bank_entry, sel),
        }
        if date_range:
            merged["date_range"] = build_date_range(bank_entry)
        result.append(merged)
    return result


def build_context(bank: dict, tailored: dict) -> dict:
    sections = tailored.get("sections", [
        "work_experience", "research", "projects", "leadership", "education", "skills"
    ])

    personal_info = dict(bank.get("personal_info", {}))
    personal_info.update(tailored.get("personal_info_overrides", {}))
    for k, v in personal_info.items():
        personal_info[k] = latex_escape(v) if isinstance(v, str) else v

    context = {
        "personal_info": personal_info,
        "summary": latex_escape(tailored.get("summary", "")),
    }

    if "work_experience" in sections:
        context["work_experience"] = merge_experience_section(
            "work_experience", bank, tailored)
    if "research" in sections:
        context["research"] = merge_experience_section("research", bank, tailored)
    if "projects" in sections:
        context["projects"] = merge_experience_section(
            "projects", bank, tailored, date_range=False)
        for p, sel in zip(context["projects"], tailored.get("projects", [])):
            bank_entry = index_by_id(bank.get("projects", []))[sel["id"]]
            p["date"] = latex_escape(bank_entry.get("date", ""))
            techs = sel.get("technologies") or bank_entry.get("tags", [])
            p["technologies"] = [latex_escape(t) for t in techs]
    if "leadership" in sections:
        leadership_bank = index_by_id(bank.get("leadership", []))
        context["leadership"] = []
        for sel in tailored.get("leadership", []):
            entry = leadership_bank.get(sel["id"])
            if not entry:
                continue
            context["leadership"].append({
                "title": latex_escape(entry.get("title", "")),
                "organization": latex_escape(entry.get("organization", "")),
                "bullets": select_bullets(entry, sel),
            })
    if "education" in sections:
        education_bank = index_by_id(bank.get("education", []))
        # education.json entries may not have explicit "id"s; fall back to
        # using all of them if the tailored file doesn't select any.
        if not education_bank:
            education_bank = {i: e for i, e in enumerate(bank.get("education", []))}
        selected = tailored.get("education") or [{"id": i} for i in education_bank]
        context["education"] = []
        for sel in selected:
            entry = education_bank.get(sel["id"])
            if not entry:
                continue
            context["education"].append({
                "institution": latex_escape(entry.get("institution", "")),
                "degree": latex_escape(entry.get("degree", "")),
                "gpa": latex_escape(entry.get("gpa", "")),
                "date_range": build_date_range(entry),
                "achievements": [latex_escape(a) for a in entry.get("achievements", [])],
            })
    if "skills" in sections:
        skills = tailored.get("skills") or bank.get("skills", {})
        context["skills"] = {
            latex_escape(k): [latex_escape(s) for s in v] for k, v in skills.items()
        }

    return context


# ---------------------------------------------------------------------------
# Cover letter context (simpler: mostly pass-through)
# ---------------------------------------------------------------------------

def build_cover_letter_context(bank: dict, tailored: dict) -> dict:
    personal_info = dict(bank.get("personal_info", {}))
    for k, v in personal_info.items():
        personal_info[k] = latex_escape(v) if isinstance(v, str) else v
    return {
        "personal_info": personal_info,
        "recipient": {k: latex_escape(v) for k, v in tailored.get("recipient", {}).items()},
        "date": latex_escape(tailored.get("date", "")),
        "body_paragraphs": [latex_escape(p) for p in tailored.get("body_paragraphs", [])],
    }


# ---------------------------------------------------------------------------
# Render + compile
# ---------------------------------------------------------------------------

def render(template_name: str, context: dict) -> str:
    template = LATEX_JINJA_ENV.get_template(template_name)
    return template.render(**context)


def compile_pdf(tex_path: Path) -> Path:
    """Compile a .tex file to PDF using latexmk, run inside its own
    directory so aux/log files land next to it."""
    out_dir = tex_path.parent
    result = subprocess.run(
        ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error",
         tex_path.name],
        cwd=out_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-2000:], file=sys.stderr)
        sys.exit(f"error: LaTeX compilation failed for {tex_path}")

    # clean up aux/log/etc, keep the .tex and .pdf
    subprocess.run(["latexmk", "-c", tex_path.name], cwd=out_dir,
                    capture_output=True, text=True)

    pdf_path = tex_path.with_suffix(".pdf")
    if not pdf_path.exists():
        sys.exit(f"error: expected output PDF not found at {pdf_path}")
    return pdf_path


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("resume", "cover"):
        sys.exit(f"usage: {sys.argv[0]} <resume|cover> <path/to/tailored.json>")

    doc_type = sys.argv[1]
    tailored_path = Path(sys.argv[2]).resolve()
    job_dir = tailored_path.parent

    bank = load_bank(DATA_DIR)
    tailored = load_json(tailored_path)

    if doc_type == "resume":
        context = build_context(bank, tailored)
        tex_source = render("resume.tex.jinja", context)
        tex_path = job_dir / "resume.tex"
    else:
        context = build_cover_letter_context(bank, tailored)
        tex_source = render("cover_letter.tex.jinja", context)
        tex_path = job_dir / "cover_letter.tex"

    tex_path.write_text(tex_source, encoding="utf-8")
    print(f"wrote {tex_path}")

    if shutil.which("latexmk") is None:
        sys.exit("error: latexmk not found on PATH — install a LaTeX "
                  "distribution (e.g. TeX Live) to compile to PDF.")

    pdf_path = compile_pdf(tex_path)
    print(f"compiled {pdf_path}")


if __name__ == "__main__":
    main()
