"""Manitoba Arts Education curriculum scraper (K-8, all 4 disciplines).

Extracts Recursive Learnings from Dance, Drama, Music, and Visual Arts
K-8 framework PDFs. Outcomes organized by Learning Areas (Making,
Creating, Connecting, Responding) with grade-band codes.

Code format: {GradeBand} {Prefix}–{LearningArea}{Num}.{SubNum}
e.g.: K–4 DA–M1.1, 5–8 DR–CR1.6, K MU–M1.1
"""

import json
import logging
import re
from pathlib import Path

import fitz
import httpx

logger = logging.getLogger(__name__)

DISCIPLINES: dict[str, dict] = {
    "Dance": {
        "prefix": "DA",
        "url": "https://www.edu.gov.mb.ca/k12/cur/arts/docs/dance_k8_2nd.pdf",
    },
    "Drama": {
        "prefix": "DR",
        "url": "https://www.edu.gov.mb.ca/k12/cur/arts/docs/drama_k8_2nd.pdf",
    },
    "Music": {
        "prefix": "M",
        "url": "https://www.edu.gov.mb.ca/k12/cur/arts/docs/music_k8_2nd.pdf",
    },
    "Visual Arts": {
        "prefix": "VA",
        "url": "https://www.edu.gov.mb.ca/k12/cur/arts/docs/visual_k8_2nd.pdf",
    },
}

LEARNING_AREAS: dict[str, str] = {
    "M": "Making",
    "CR": "Creating",
    "C": "Connecting",
    "R": "Responding",
}


def _download(url: str, dest: Path) -> Path:
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


def _extract_outcomes(pdf_path: Path, prefix: str) -> list[dict]:
    """Extract all outcomes from an arts K-8 framework PDF.

    Returns list of dicts with keys: grade_band, code, full_code, description,
    learning_area_code, learning_area_name, recursive_learning.
    """
    doc = fitz.open(str(pdf_path))
    outcomes: list[dict] = []

    # Build code pattern for this discipline
    # Codes look like: K–4 DA–M1.1 or 5–8 DR–CR1.6
    code_pattern = re.compile(
        rf"^([\dK]+(?:[–-]\d+)?)\s+{re.escape(prefix)}[–-]([A-Z]+)(\d+)\.(\d+)$"
    )

    for page_num in range(doc.page_count):
        page = doc[page_num]
        blocks = page.get_text("dict")["blocks"]

        # Collect all text lines with y-position for this page
        page_lines: list[tuple[float, str]] = []
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                text = " ".join(s["text"] for s in line["spans"]).strip()
                if not text or len(text) < 3:
                    continue
                # Normalize dashes
                text = text.replace(" – ", "–").replace("– ", "–").replace(" –", "–")
                y = line["bbox"][1]
                page_lines.append((y, text))

        # Sort by y position
        page_lines.sort(key=lambda x: x[0])

        # Find code lines and capture description from preceding line(s)
        for i, (y, text) in enumerate(page_lines):
            m = code_pattern.match(text)
            if not m:
                continue

            grade_band = m.group(1)
            la_code = m.group(2)
            rl_num = m.group(3)
            sub_num = m.group(4)
            full_code = f"{grade_band} {prefix}–{la_code}{rl_num}.{sub_num}"

            # Get description: collect text above this code until we hit
            # another code or a header
            desc_parts: list[str] = []
            for j in range(i - 1, max(i - 5, -1), -1):
                prev_y, prev_text = page_lines[j]
                if code_pattern.match(prev_text):
                    break
                if re.match(r"^(Grade|Kindergarten|The learner|RECURSIVE)", prev_text):
                    break
                if re.match(r"^[A-Z]\s+[a-z]", prev_text) and len(prev_text) < 20:
                    break
                # Skip headers
                if any(x in prev_text for x in [
                    "R e c u r s i v e", "M a k i n g", "C r e a t i n g",
                    "C o n n e c t i n g", "R e s p o n d i n g",
                    "K i n d e r g a r t e n", "Appendix",
                ]):
                    break
                if prev_text.startswith("*"):
                    break
                desc_parts.insert(0, prev_text)

            description = " ".join(desc_parts).strip()
            # Clean up: remove bullet chars, extra whitespace
            description = re.sub(r"[\uf0a7\uf0b7]", "", description)
            description = re.sub(r"\s+", " ", description).strip()

            la_name = LEARNING_AREAS.get(la_code, "")
            if not la_name:
                continue  # Skip misparses with invalid learning area codes
            rl_title = f"{prefix}–{la_code}{rl_num}"

            outcomes.append({
                "grade_band": grade_band,
                "code": full_code,
                "description": description,
                "learning_area_code": la_code,
                "learning_area_name": la_name,
                "recursive_learning": rl_title,
            })

    doc.close()

    # Deduplicate by code
    seen: set[str] = set()
    unique: list[dict] = []
    for o in outcomes:
        if o["code"] not in seen:
            seen.add(o["code"])
            unique.append(o)

    return unique


def scrape_all_arts(
    output_dir: Path,
    progress_callback=None,
) -> dict[str, list]:
    """Scrape Arts Education K-8 (Dance, Drama, Music, Visual Arts)."""
    results: dict[str, list] = {}
    tmp_dir = Path("/tmp/arts_pdfs")
    tmp_dir.mkdir(exist_ok=True)

    for disc_name, disc_info in DISCIPLINES.items():
        prefix = disc_info["prefix"]
        url = disc_info["url"]

        if progress_callback:
            progress_callback(f"Downloading {disc_name} K-8 framework PDF...")

        try:
            pdf_path = tmp_dir / f"{disc_name.lower().replace(' ', '_')}_k8.pdf"
            _download(url, pdf_path)
        except Exception as e:
            if progress_callback:
                progress_callback(f"ERROR downloading {disc_name}: {e}")
            continue

        if progress_callback:
            progress_callback(f"Parsing {disc_name} K-8 outcomes...")

        outcomes = _extract_outcomes(pdf_path, prefix)

        # Group by Learning Area as clusters
        la_groups: dict[str, list[dict]] = {}
        for o in outcomes:
            la_key = o["learning_area_name"]
            la_groups.setdefault(la_key, [])
            la_groups[la_key].append(o)

        clusters: list[dict] = []
        for la_name, la_outcomes in la_groups.items():
            la_code = la_outcomes[0]["learning_area_code"]
            slos = []
            for o in la_outcomes:
                slos.append({
                    "code": o["code"],
                    "description": o["description"],
                    "glo": [f"{la_name} ({la_code})"],
                    "glo_description": [
                        f"{la_name}: The learner develops skills and understanding in {la_name.lower()}."
                    ],
                })

            cluster_title = f"{la_name} ({la_code})"
            clusters.append({
                "id": cluster_title,
                "title": cluster_title,
                "description": f"Learning Area: {la_name}",
                "specific_learning_outcomes": slos,
            })

        results[disc_name] = clusters

        output_data = {
            "subject": f"Arts Education - {disc_name}",
            "grade": "K-8",
            "course": f"K-8 {disc_name}",
            "framework_year": "Framework 2015",
            "clusters": clusters,
        }

        filename = f"Arts_{disc_name.replace(' ', '')}_K8.json"
        filepath = output_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=4, ensure_ascii=False)

        total = sum(len(c["specific_learning_outcomes"]) for c in clusters)
        if progress_callback:
            progress_callback(
                f"Saved {filename}: {len(clusters)} learning areas, {total} outcomes"
            )

    return results
