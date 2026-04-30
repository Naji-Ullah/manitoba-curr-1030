"""Manitoba Legacy English Language Arts curriculum scraper (Senior 1-4).

Senior 1 & 2: Uses individual outcome PDFs (outcome1.pdf - outcome5.pdf)
  - 5 GLOs, each with specific learning outcomes coded (N.N.N)
Senior 3 & 4: Uses full document PDFs with 3 focus areas
  - Comprehensive, Literary, Transactional — each with 5 GLOs
"""

import json
import logging
import re
from pathlib import Path

import fitz
import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.edu.gov.mb.ca/k12/cur/ela/docs"

GLO_TITLES: dict[str, str] = {
    "1": "Explore thoughts, ideas, feelings, and experiences.",
    "2": "Comprehend and respond personally and critically to oral, print, and other media texts.",
    "3": "Manage ideas and information.",
    "4": "Enhance the clarity and artistry of communication.",
    "5": "Celebrate and build community.",
}


def _download(url: str, dest: Path) -> Path:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


def _parse_outcomes_from_page(text: str) -> list[dict]:
    """Parse outcomes from a single page of text using (N.N.N) codes as delimiters."""
    text = text.replace("\uf0a7", "").replace("\uf0b7", "")

    text_flat = re.sub(r"\n", " ", text)
    text_flat = re.sub(r"\s+", " ", text_flat)

    parts = re.split(r"\((\d\.\d\.\d)\)", text_flat)

    outcomes: list[dict] = []
    for i in range(1, len(parts), 2):
        code = parts[i]
        pre = parts[i - 1].strip()
        post = parts[i + 1].strip() if i + 1 < len(parts) else ""

        # Title: last few Title Case words before the code
        words = pre.split()
        title_words: list[str] = []
        for w in reversed(words):
            if re.match(r"^[A-Z][a-z]+$", w) or w.lower() in [
                "and", "with", "to", "of", "the", "in", "for", "a",
            ]:
                title_words.insert(0, w)
            elif w == "Others\u2019" or re.match(r"^[A-Z][a-z]+[\u2019']s$", w):
                title_words.insert(0, w)
            else:
                break
        title = " ".join(title_words)

        # Description: post text minus trailing title words of next outcome
        if i + 2 < len(parts):
            desc_words = post.split()
            while desc_words:
                w = desc_words[-1]
                if re.match(r"^[A-Z][a-z]+$", w) or w.lower() in [
                    "and", "with", "to", "of", "the", "in", "for", "a",
                ]:
                    desc_words.pop()
                elif w == "Others\u2019" or re.match(r"^[A-Z][a-z]+[\u2019']s$", w):
                    desc_words.pop()
                else:
                    break
            desc = " ".join(desc_words)
        else:
            desc = post

        outcomes.append({
            "code": code,
            "title": title,
            "description": desc,
        })

    return outcomes


def _scrape_s1_s2(grade: str, tmp_dir: Path, progress_callback) -> list[dict]:
    """Scrape Senior 1 or 2 using individual outcome PDFs."""
    grade_key = grade.lower()  # s1 or s2
    clusters: list[dict] = []

    for glo_num in range(1, 6):
        url = f"{BASE_URL}/{grade_key}_framework/outcome{glo_num}.pdf"
        pdf_path = tmp_dir / f"{grade_key}_outcome{glo_num}.pdf"

        if progress_callback:
            progress_callback(f"Downloading ELA {grade} GLO {glo_num}...")

        try:
            _download(url, pdf_path)
        except Exception as e:
            if progress_callback:
                progress_callback(f"ERROR downloading GLO {glo_num}: {e}")
            continue

        doc = fitz.open(str(pdf_path))
        text = doc[0].get_text()
        doc.close()

        outcomes = _parse_outcomes_from_page(text)

        glo_title = GLO_TITLES.get(str(glo_num), f"GLO {glo_num}")
        slos = []
        for o in outcomes:
            slos.append({
                "code": o["code"],
                "description": o["description"],
                "glo": [f"GLO {glo_num}"],
                "glo_description": [f"GLO {glo_num}: {glo_title}"],
            })

        cluster_title = f"GLO {glo_num}: {glo_title}"
        clusters.append({
            "id": cluster_title,
            "title": cluster_title,
            "description": glo_title,
            "specific_learning_outcomes": slos,
        })

    return clusters


def _scrape_s3_s4(grade: str, tmp_dir: Path, progress_callback) -> list[dict]:
    """Scrape Senior 3 or 4 from full document PDF with 3 focus areas."""
    grade_key = grade.lower()
    url = f"{BASE_URL}/{grade_key}_framework/{grade_key}_fulldoc.pdf"
    pdf_path = tmp_dir / f"{grade_key}_fulldoc.pdf"

    if progress_callback:
        progress_callback(f"Downloading ELA {grade} full document...")

    _download(url, pdf_path)

    doc = fitz.open(str(pdf_path))
    toc = doc.get_toc()

    # Find focus area sections and GLO page ranges
    focus_areas: list[tuple[str, int]] = []
    glo_entries: list[tuple[str, int]] = []
    for level, title, page in toc:
        if "Focus" in title and "Outcomes" in title:
            # Clean title
            clean = title.replace(" and Standards", "").strip()
            focus_areas.append((clean, page))
        if "General Learning Outcome" in title or "General Leanring" in title or "General Learnng" in title:
            glo_entries.append((title, page))

    clusters: list[dict] = []

    for fa_idx, (focus_name, fa_start) in enumerate(focus_areas):
        fa_end = focus_areas[fa_idx + 1][1] if fa_idx + 1 < len(focus_areas) else doc.page_count

        # Find GLOs within this focus area
        fa_glos = [(t, p) for t, p in glo_entries if fa_start <= p < fa_end]

        for glo_idx, (glo_title_raw, glo_start) in enumerate(fa_glos):
            glo_end = fa_glos[glo_idx + 1][1] if glo_idx + 1 < len(fa_glos) else fa_end

            # Extract GLO number
            m = re.search(r"(\d)", glo_title_raw)
            glo_num = m.group(1) if m else str(glo_idx + 1)

            # Get text from the first page of this GLO section
            page_idx = glo_start - 1
            if page_idx < 0 or page_idx >= doc.page_count:
                continue

            text = doc[page_idx].get_text()
            outcomes = _parse_outcomes_from_page(text)

            if not outcomes:
                continue

            glo_title = GLO_TITLES.get(glo_num, f"GLO {glo_num}")
            cluster_title = f"{focus_name} - GLO {glo_num}: {glo_title}"

            slos = []
            for o in outcomes:
                slos.append({
                    "code": o["code"],
                    "description": o["description"],
                    "glo": [f"GLO {glo_num}"],
                    "glo_description": [f"GLO {glo_num}: {glo_title}"],
                })

            clusters.append({
                "id": cluster_title,
                "title": cluster_title,
                "description": f"{focus_name} — {glo_title}",
                "specific_learning_outcomes": slos,
            })

    doc.close()
    return clusters


def scrape_all_ela(
    output_dir: Path,
    progress_callback=None,
) -> dict[str, list]:
    """Scrape ELA Senior 1-4."""
    results: dict[str, list] = {}
    tmp_dir = Path("/tmp/ela_pdfs")
    tmp_dir.mkdir(exist_ok=True)

    for grade in ["S1", "S2", "S3", "S4"]:
        if progress_callback:
            progress_callback(f"Scraping ELA {grade}...")

        try:
            if grade in ("S1", "S2"):
                clusters = _scrape_s1_s2(grade, tmp_dir, progress_callback)
            else:
                clusters = _scrape_s3_s4(grade, tmp_dir, progress_callback)
        except Exception as e:
            if progress_callback:
                progress_callback(f"ERROR scraping ELA {grade}: {e}")
            continue

        results[grade] = clusters

        output_data = {
            "subject": "English Language Arts",
            "grade": grade,
            "course": f"{grade} English Language Arts",
            "framework_year": "Framework 1998",
            "clusters": clusters,
        }

        filename = f"ELA_{grade}.json"
        filepath = output_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=4, ensure_ascii=False)

        total = sum(len(c["specific_learning_outcomes"]) for c in clusters)
        if progress_callback:
            progress_callback(f"Saved {filename}: {len(clusters)} clusters, {total} outcomes")

    return results
