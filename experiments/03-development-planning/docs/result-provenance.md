# Provenance of the recorded materials

The five LLM proposals were collected using Chinese prompts. The published prompts are English translations. The feedback labels and two comment lines in each DATA deck were also translated. Well coordinates, pressure targets, production histories, and grid values are preserved.

The original JSON replies, numerical simulation CSVs, solver completion receipts, and per-evaluation records are distributed byte for byte. Checksums in the records and receipts refer to the files used during the study. Inside the [simulation archive](../results/simulation-results.zip), `text_editions.csv` pairs the recorded and published SHA-256 checksums for the five prompts, 30 decks, and 30 feedback files.

Use a fresh study directory for new runs with the published prompts. The [replay program](../reproduce.py) verifies the archived comparison offline.
