# Manitoba Legacy Curriculum Scraper

Scrapes curriculum data from Manitoba's legacy education site (`edu.gov.mb.ca/k12/cur/`) and outputs structured JSON files per grade.

## Currently Supported

- **Science K-9** (Framework 1999/2000) — Extracts clusters, SLOs, and GLO references from PDF documents

## Output Format

Each grade produces a JSON file like `Science_Grade_K.json`:

```json
{
    "province": "Manitoba",
    "subject": "Science",
    "grade": "K",
    "framework_year": "Framework 1999",
    "source_url": null,
    "source_pdf": "https://www.edu.gov.mb.ca/k12/cur/science/outcomes/k-4/grade_k.pdf",
    "organizing_structure": "clusters",
    "groups": [
        {
            "id": "cluster_1",
            "type": "cluster",
            "title": "Trees",
            "description": "In Kindergarten, an investigation of trees...",
            "learning_outcomes": [
                {
                    "code": "K-1-01",
                    "description": "Use appropriate vocabulary related to their investigations of trees...",
                    "glo": ["C5", "D1", "D5"],
                    "glo_description": [
                        "C5. demonstrate curiosity, skepticism, creativity...",
                        "D1. understand essential life structures...",
                        "D5. understand the composition of the Earth's atmosphere..."
                    ]
                }
            ]
        }
    ]
}
```

## Setup

```bash
pip install -e .
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open http://localhost:8000 and click **Scrape Science (K-10)**.

## Docker

```bash
docker build -t mb-scraper .
docker run -p 8000:8000 mb-scraper
```
