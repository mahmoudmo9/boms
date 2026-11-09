# Reference data sources (v0.9.0)

Files here are loaded by `python -m app.cli reference-import <dataset> [--file path]` (the installer and every update
run `seed`, which imports them). BOMS never downloads reference data at runtime.

| Dataset | File | Source | Release / version | Downloaded | Licence |
|---|---|---|---|---|---|
| `airports` | `airports.csv.gz` (gzip of `airports.csv`, sha256 of the original `1b46b6c1bd27d12c50ace581130faf7c69f7a2df5268dcb4ebaaa06d530d2d28`, 86,350 rows, 8,799 with an IATA code) | OurAirports, https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv | `main` branch as of the download date | 2026-11-09 | Public domain (OurAirports) |
| `unlocode` | not shipped — see below | UNECE, https://unece.org/trade/cefact/unlocode-code-list-country-and-territory (CSV release, e.g. `loc242csv.zip`) | — | **not downloaded**: `service.unece.org` refused by this build environment's network policy (proxy 403) | UNECE terms of use |
| `elf` | not shipped — see below | GLEIF, https://www.gleif.org/en/about-lei/code-lists/iso-20275-entity-legal-forms-code-list (CSV) | — | **not downloaded**: `www.gleif.org` refused (proxy 403) | GLEIF, CC0 |
| `locations` | `locations_curated.csv` (130 rows: Iranian ports, cities and airports and the main ports of CN, AE, TR, IN, DE, IT, RU, OM and other partners, with Persian names) | BOMS-curated from UN/LOCODE codes | 2026-11 | — | BOMS |
| `legal_forms` | `legal_forms_curated.csv` (Iranian forms of the Commercial Code with Persian abbreviations, plus common foreign forms for the duplicate check) | BOMS-curated; ELF codes are filled when the GLEIF file is imported | 2026-11 | — | BOMS |
| `containers` | `container_types.csv` | ISO 6346:2022 size/type codes (common ones) | ISO 6346:2022 | — | codes only |
| `transport_modes` | `transport_modes.csv` | UN/ECE Recommendation 19 (Codes for Modes of Transport) | Rec. 19 | — | UNECE |
| `incoterms` | `incoterms.csv` | Incoterms® 2020 (ICC), rule codes and names only | 2020 | — | names / codes only |
| `units` | `units_unece.csv` | UN/ECE Recommendation 20 codes for the existing units (package units as Rec. 21 codes with the `X` prefix, as Rec. 20 annex III allows) and common trade units added | Rec. 20 rev. 17 | — | UNECE |

**Not verified.** The curated locations carry UN/LOCODE codes but could not be checked against the official file in this
build (`verified = false`). Importing the official UN/LOCODE CSV later (`reference-import unlocode --file <path to the
unzipped CSV folder or file>`) loads every location, marks the curated rows verified when the official file has them
(and reports any that it does not), and keeps their Persian names. The same for the GLEIF ELF CSV
(`reference-import elf --file <path>`).
