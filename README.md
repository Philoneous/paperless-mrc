# paperless-mrc – shrink scanned PDFs in Paperless-ngx

*English · [Deutsch](README.de.md)*

**paperless-mrc makes scanned documents in [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) typically
5 to 30 times smaller – while text stays sharp, colours are kept and the document stays searchable.** It runs
automatically as a pre-consume script: every new scan is compressed before Paperless stores it, so your archive only
ever contains the small file.

It uses *Mixed Raster Content* (MRC), the technique behind compact PDF archives such as the Internet Archive's, via
[archive-pdf-tools](https://github.com/internetarchive/archive-pdf-tools). Text recognition (OCR) is done with
[Tesseract](https://github.com/tesseract-ocr/tesseract).

> On a Mac? The app [PDF MRC](https://github.com/Philoneous/mac-pdf-mrc) uses the same engine to compress PDFs with a
> right-click in Finder – no server needed.

## Typical results

| Document | before | after |
|---|---:|---:|
| One-page colour letter (test page, simulated office scan, 300 dpi) | 956 KB | 126 KB |
| Same letter at 200 dpi | 496 KB | 65 KB |
| Four real phone scans, 6 pages in total (iPhone/Mac scanner) | 12,637 KB | 375 KB |

Small print down to 5 pt, light-grey text, coloured text, logos, stamps and signatures stay readable. Sizes measured
with the CCITT mask; with jbig2enc installed the files get somewhat smaller still.

## How it works

A scanned page is a photo of paper. MRC splits it into three layers, each compressed the way that suits it best:

- **Text layer:** all text and lines as a sharp black-and-white image at full resolution, compressed losslessly
  (JBIG2 or CCITT) – this is why text stays crisp.
- **Background:** paper, coloured areas and pictures at reduced resolution, compressed with JPEG 2000.
- **Colour of the text:** a small image that gives letters, logos and stamps their colour.

A normal scan stores every page as one large photo; MRC only keeps the detail where it matters.

## What it does with each document

1. **Only scanned pages are touched.** A page counts as scanned if it consists of a single page image without visible
   text. Digital pages (e.g. a generated cover letter in front of a scan), bookmarks and metadata stay exactly as they
   are. Purely digital PDFs, **digitally signed or encrypted PDFs** and uploaded images (JPEG, PNG …) are not changed at all.
   - **Photos stay as they are**, because MRC would visibly degrade them. A page that is mostly paper counts as a
     document; for all other pages (photos, but also forms with shaded boxes) text recognition decides.
   - **Vectorized scans** – some scanner software stores a page as thousands of drawing elements instead of an image –
     are turned into an image, compressed and made searchable.
2. **Blank pages are removed** – e.g. empty back sides from double-sided scanning. Paper tone, noise and show-through
   do not count as content; a page with only a page number is kept, and so are faint pages (a pale photo, a faded
   receipt).
3. **Text recognition:** an existing text layer (e.g. from the scanner) is kept. Otherwise Tesseract recognizes the
   text – after turning upside-down or sideways pages the right way up and straightening skewed pages.
4. **Compression** of each page with MRC; implausible page sizes (e.g. phone scans stored many times larger than A4)
   are corrected to A4.
5. **Verification:** same number of pages, text layer complete, the file renders without errors and is smaller. Only
   then is the original replaced.

If **anything goes wrong**, the file stays unchanged and Paperless processes it as usual.

## Requirements

- Paperless-ngx 3.x (tested with 3.3.0) installed **without Docker** on Debian/Ubuntu with uv and systemd – the layout
  of the [Proxmox VE Helper-Scripts](https://community-scripts.github.io/ProxmoxVE/) (`/opt/paperless`). Docker
  installations are not supported by the installer.
- In Paperless: OCR mode `auto` (default) and archive file generation `auto` (default) or `never`. Paperless then uses
  the text layer of the compressed file, runs no OCR of its own and does not create a second file.
- Optional: `jbig2` ([jbig2enc](https://github.com/agl/jbig2enc)) for the smallest files; without it CCITT is used.

## Installation

As root inside the Paperless container (or VM):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Philoneous/paperless-mrc/main/install.sh)"
```

The installer guides you through the setup:

1. **Language** of the installer and of the messages (English or German).
2. **The most important settings** – OCR languages, removing blank pages, leaving photos unchanged, PDFs with digital
   pages, existing text layer, paper format, keeping the original until checked (with API token, which is checked
   right away). Enter keeps the value shown in brackets; the defaults are chosen for the best readability.
3. **Detailed settings** only if you want them – grouped (quality and size, page selection, text recognition, blank
   pages, other), each with its range and what it does.

It then installs the system packages and OCR language packs, sets up paperless-mrc in its own Python environment under
`/opt/paperless-mrc`, writes only the settings that differ from the default to `/opt/paperless/paperless.conf` (a
backup is placed next to it), adds the pre-consume script and restarts `paperless-task-queue` and
`paperless-consumer`. It stops if a different pre-consume script is already configured.

**Update:** run the same command again. The installer shows your current settings and offers to keep them; then it
only asks about options that have been added since your last setup (none → no questions). You can also go through all
settings again. **Without questions** (e.g. in scripts): `MRC_YES=1 bash -c "…"` keeps the existing settings.
**Uninstall:** remove the line `PAPERLESS_PRE_CONSUME_SCRIPT=…` from `paperless.conf` and restart both services.

## Optional: keep the original until you have checked it

Normally the compressed file replaces the original. If you would rather check the result first, paperless-mrc can keep
the original as a second **version** of the document (Paperless-ngx 3 or later) and delete it later:

- The compressed file becomes the document; the original is attached as the version *Original*. In the document
  view you can switch between both versions and compare them.
- A select field **Original (MRC)** decides what happens to the original:

  | Choice | Effect |
  |---|---|
  | **Delete after 30 days** (default) | The original is deleted automatically after the period (`MRC_KEEP_ORIGINAL_DAYS`) |
  | **Keep** | The original stays permanently – e.g. if the compressed version is not good enough |
  | **Delete now** | The original is deleted within the hour – typically after you have checked the document |

- The choices are labelled in the language selected in Paperless (*Settings → Language* of the user whose API token
  is used); if it is set to the browser language, which the server cannot know, they are in English. `MRC_LANGUAGE`
  overrides this.
- After deletion only the small compressed file remains and the field disappears, so filtering the document list by
  *Original (MRC)* shows exactly the documents that still have an original (handy as a saved view for reviewing).
- An hourly timer (`paperless-mrc-cleanup`) does the deleting. It only deletes in clear cases; an unknown value, or a
  field of the same name that paperless-mrc did not create, leaves everything as it is.

**Switch on:** answer *yes* in the installer and enter an API token (create it in Paperless under *My Profile*). The
option is off by default. Without questions: `KEEP_ORIGINAL=1 MRC_YES=1 bash -c "…"`, then add the token to
`/opt/paperless/paperless.conf` as `MRC_API_TOKEN=<token>` and restart `paperless-task-queue` and
`paperless-consumer`. The installer sets up the
post-consume script, the folder `/opt/paperless-mrc/originals` and the timer; it stops if a different post-consume
script is already configured. **Switch off:** answer *no* in the installer (or set `MRC_KEEP_ORIGINAL=false`
and restart both services) – new documents then replace the original as before, and the timer still handles the
originals that are already there.

Good to know:
- Until it is deleted, the original takes up as much space as before. If the original has no text layer, Paperless
  also runs its own text recognition on that version, which costs some server time.
- Paperless moves deleted versions to its trash; the space is freed when the trash is emptied (after 30 days by
  default, `PAPERLESS_EMPTY_TRASH_DELAY`).
- If the original cannot be put aside, the file is not compressed at all – an original is never lost. If attaching it
  fails (e.g. the token is missing), it stays in `/opt/paperless-mrc/originals` and the timer attaches it later.

## Configuration

Without any configuration the defaults apply; they were chosen for the best readability of the result. paperless-mrc
reads these Paperless settings from `paperless.conf`:

| Variable | Effect |
|---|---|
| `PAPERLESS_OCR_LANGUAGE` | Tesseract languages, e.g. `deu+eng` |
| `PAPERLESS_OCR_DESKEW` | Straighten skewed pages (only pages without an existing text layer) |
| `PAPERLESS_OCR_ROTATE_PAGES` | Turn pages the right way up (only pages without an existing text layer) |
| `PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD` | How sure the orientation detection must be before a page is rotated (0–100, default 12) |
| `PAPERLESS_THREADS_PER_WORKER` | Pages processed at the same time (default as in Paperless: cores ÷ `PAPERLESS_TASK_WORKERS`) |

Values set only in the web interface (*Configuration*) are not visible to the script; this is why the installer also
writes the OCR languages to `paperless.conf`.

Additional settings, also in `paperless.conf`. Values outside the range are limited to it; an invalid value (not a
number) is replaced by the default and reported in the log.

| Variable | Default | Range | Effect |
|---|---|---|---|
| **Quality and size** | | | |
| `MRC_SHARPEN` | `150` | 0–300 | Sharpening in % before compression so that faint, thin text stays crisp. 0 = off (faint text can look patchy); high values make text bolder but also emphasize noise and stains |
| `MRC_SHARPEN_RADIUS` | `1.5` | 0.5–5 | Width of the sharpening in pixels at 200 dpi (scaled with the resolution). Small = only fine edges, large = visible halos |
| `MRC_MASK_FACTOR` | `0.5` | 0.1–1 | Which pixels go into the sharp text layer. Smaller = faint text and thin lines also stay sharp, but more specks are kept; 1 = recode_pdf's own setting (faint text may become blurry) |
| `MRC_BG_DOWNSAMPLE` | `2` | 1–4 | Background at 1/n of the scan resolution (text always stays at full resolution). 1 = best colours and pictures, larger; 4 = smallest, coloured areas get blocky |
| `MRC_BG_COMPRESSION_RATE` | `200` | 50–800 | JPEG 2000 compression of the background. 50 = barely compressed; 800 = very small, coloured areas and pictures get blotchy |
| `MRC_MAX_DPI` | `0` | 0, 150–1200 | Downscale scans above this resolution before compressing: faster and smaller, but the finest details are lost. 0 = off (keep the scan's resolution) |
| `MRC_FIT_A4` | `true` | | Scale implausibly large page sizes (shorter side larger than A3, e.g. 72-ppi phone scans) down to the target size |
| `MRC_FIT_PAGE_SIZE` | `a4` | `a4`, `letter`, `legal` | Target size for that scaling (aspect ratio is kept) |
| **Page selection** | | | |
| `MRC_MIXED_PDFS` | `true` | | Also process PDFs that contain digital pages (these stay unchanged); `false` = only PDFs that consist entirely of scans |
| `MRC_SKIP_PHOTOS` | `true` | | Leave photo pages unchanged |
| `MRC_PHOTO_PAPER_PERCENT` | `50` | 0–100 | Pages with less paper area (in %) are checked with text recognition. 0 = never check (every page counts as a document), 100 = check every page. Documents on white paper typically have 60–98 %, photos 10–45 % |
| `MRC_PHOTO_MIN_WORDS` | `10` | 0–100 | A checked page counts as a photo with fewer confidently recognized words (≥ 3 characters). 0 = never a photo |
| `MRC_VECTOR_PAGES` | `true` | | Turn vectorized scans into an image, compress them and make them searchable |
| `MRC_VECTOR_MIN_ITEMS` | `1000` | 1–100,000 | A page without image and text counts as a vectorized scan from this many drawing elements. Low values also convert simple digital drawings |
| `MRC_VECTOR_DPI` | `300` | 150–600 | Resolution for vectorized scans. Higher = small print sharper, but larger and slower |
| **Text recognition** | | | |
| `MRC_KEEP_TEXT_LAYER` | `true` | | Keep an existing text layer; `false` = always recognize again (pages are then also rotated and straightened) |
| `MRC_ROTATE_CHECK` | `true` | | If the orientation detection is unsure but suggests a rotation, recognize the text in both orientations and rotate only if that gives clearly more words – helps with landscape forms scanned in portrait |
| `MRC_DESKEW_MIN_ANGLE` | `0.2` | 0–2 | Smaller skews (degrees) are left as they are. 0 = correct every detected skew |
| `MRC_DESKEW_MAX_ANGLE` | `5` | 0.5–45 | Search range ± in degrees. Larger = also strongly skewed pages, but slower. A result at the edge of the range counts as ambiguous and is not corrected |
| `MRC_DESKEW_MIN_CONFIDENCE` | `1.3` | 1–3 | Only straighten if the best angle clearly stands out. 1 = always (logos or stamps on pages with little text can tilt a straight page); 3 = only pages with many clear lines of text |
| **Blank pages** | | | |
| `MRC_REMOVE_BLANK_PAGES` | `true` | | Remove blank scanned pages |
| `MRC_BLANK_INK_PERCENT` | `0.005` | 0–1 | A page is blank below this share of ink in %. 0 = never remove; a page with only a page number has about 0.01 % |
| `MRC_BLANK_INK_CONTRAST` | `20` | 10–100 | For the blank check, a pixel counts as ink if it is this many brightness levels darker than the paper around it. Lower = faint content keeps a page (10: strong show-through may too); higher = only clear marks count (40 = before 11/2026: pale photos and faded receipts were removed) |
| `MRC_BLANK_PAPER_PERCENT` | `90` | 0–100 | A page can only be blank if at least this share (%) looks like paper – protects low-contrast photos (e.g. of a white wall) |
| **Other** | | | |
| `MRC_JOBS` | – | 1–64 | Pages processed at the same time; overrides `PAPERLESS_THREADS_PER_WORKER` |
| `MRC_POPPLER_CHECK` | `true` | | Also render the result with Poppler (`pdftoppm`) and discard it on errors |
| `MRC_LANGUAGE` | `en` | | Language of the log messages: `en` or `de` |
| `MRC_TIMING` | `false` | | Log the time each step takes per page |
| **Keep the original (optional)** | | | |
| `MRC_KEEP_ORIGINAL` | `false` | | Keep the original as a version until you have checked it (see above) |
| `MRC_KEEP_ORIGINAL_DAYS` | `30` | 1–3650 | Default period after which the original is deleted |
| `MRC_API_TOKEN` | – | | Paperless API token (from *My Profile*), needed to attach and delete versions |
| `MRC_API_URL` | `http://localhost:8000` | | Address of the Paperless API from inside the container (port from `PAPERLESS_PORT`) |
| `MRC_ORIGINALS_DIR` | `/opt/paperless-mrc/originals` | | Where originals wait until they are attached |

Deliberately **not** configurable: digitally signed PDFs stay unchanged (the signature would become invalid), and the
original is only replaced if the result passed verification and is smaller.

## Log output

Messages appear in the Paperless log with the prefix `paperless-mrc:` (English by default, German with
`MRC_LANGUAGE=de`). In addition, there is one machine-readable line per document:

```
paperless-mrc-result: {"version": 1, "file": "scan.pdf", "status": "compressed", "reason": "compressed",
  "size_before": 1482508, "size_after": 46886, "pages": 1, "blank_removed": 1, "photos": 0, "vectorised": 0,
  "digital": 0, "text_layer": "ocr"}
```

- `status`: `compressed`, `unchanged` or `error`
- `reason`: `compressed`, `not_pdf`, `signed`, `encrypted`, `original_version`, `no_scanned_pages`, `mixed_disabled`, `nothing_to_compress`
  (with `photos`, `blank`), `not_smaller` (with sizes), `error` (with `message`)
- sizes in bytes; `text_layer`: `kept`, `ocr` or `mixed`

## Good to know

- **The compression is lossy:** by default the original is replaced and afterwards only the compressed version
  exists. To check first, switch on [keeping the original](#optional-keep-the-original-until-you-have-checked-it).
- **Duplicate detection:** Paperless compares the checksum of an incoming file with the stored one. Since the stored
  file is the compressed one, uploading the identical original again is no longer recognized as a duplicate (it is
  while the original is kept as a version).
- **"Reprocess"** in Paperless does not run paperless-mrc again (the file is already compressed).
- Annotations (comments, highlights) on scanned pages are burned into the image and can no longer be edited.
- Pages with an existing text layer are not rotated or straightened, because the text layer would no longer match.

## Support

paperless-mrc is free. If it saves you time or storage, you can support its development on
[Ko-fi](https://ko-fi.com/Philoneous) (PayPal or card, no account needed) – also via the *Sponsor* button at the top of
this page. Contributions are voluntary and not tax-deductible donations.

## Development

**New setting?** Add it to `src/paperless_mrc/catalog.py` with `since=REVISION + 1` and increase `REVISION`. The
installer then asks existing users about it on their next update; `tests/test_catalog.py` fails if a setting read by
the code is missing from the catalog or its default differs.

```bash
uv sync
uv run pytest                                                  # synthetic test documents
PAPERLESS_MRC_TESTFILES=/path/to/scans uv run pytest -k echte   # optional: your own scans
```

Requires `tesseract` (with `deu`), `opj_compress` (libopenjp2-tools) and `pdftoppm` (poppler-utils; not needed with
`MRC_POPPLER_CHECK=false`).

## License

Copyright (C) 2026 Philoneous. GNU Affero General Public License v3.0 or later (`AGPL-3.0-or-later`), see
[LICENSE](LICENSE) – matching the AGPL-licensed dependencies PyMuPDF and archive-pdf-tools.

The MRC encoding is done by [archive-pdf-tools](https://github.com/internetarchive/archive-pdf-tools) and
[archive-hocr-tools](https://github.com/internetarchive/archive-hocr-tools) by the Internet Archive (AGPL-3.0), PDF
handling by [PyMuPDF](https://github.com/pymupdf/PyMuPDF)/MuPDF by Artifex (AGPL-3.0) and
[pikepdf](https://github.com/pikepdf/pikepdf) (MPL-2.0), text recognition by
[Tesseract](https://github.com/tesseract-ocr/tesseract) (Apache-2.0). paperless-mrc is an independent project and is not
affiliated with or endorsed by Paperless-ngx or the Internet Archive.
