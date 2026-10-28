# paperless-mrc

*English · [Deutsch](README.de.md)*

Pre-consume script for [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) (tested with 3.3.0).
It shrinks scanned PDFs with *Mixed Raster Content* (MRC, [archive-pdf-tools](https://github.com/internetarchive/archive-pdf-tools))
before Paperless processes them. Paperless then stores only this one small file.

MRC splits every page into a losslessly compressed black-and-white mask (text, lines) and two heavily compressed colour
layers (background, colours of logos, stamps, signatures). Colour is kept wherever it occurs.

## Results with real scans

Four phone scans (macOS/iOS scanner, losslessly stored page images, 6 pages):

| File | before | after |
|---|---:|---:|
| 1 page | 3,767 KB | 75 KB |
| 2 pages | 5,832 KB | 139 KB |
| 1 page | 2,477 KB | 66 KB |
| 2 pages | 559 KB | 95 KB |
| **Total** | **12,637 KB** | **375 KB** |

The existing text layer was kept completely, logos stayed in colour, small print stayed readable.
The mask was CCITT-compressed; with jbig2enc the files get somewhat smaller still.

## What the script does

1. **Scanned pages only:** a page counts as a scan if it consists of exactly one page image and has no visible text.
   Only these pages are re-encoded. Other pages (e.g. an attached digital cover letter), bookmarks and metadata stay
   unchanged. Purely digital PDFs, digitally signed PDFs and directly uploaded images (JPEG, PNG …) stay completely
   unchanged.
   - **Photos** (e.g. damage photos) are left unchanged because MRC visibly degrades them. Pages that are mostly paper
     count as documents. For all others – photos, but also grey or coloured text boxes as in insurance policies – text
     recognition decides: only with enough confidently recognised words is it a document. Pages with almost no
     contrast that are not paper (e.g. a photo of a wall) stay unchanged and are never removed as blank.
   - **Vectorised scans** (some scanner software stores pages as thousands of vector elements without text) are
     rasterised at 300 dpi, compressed and made searchable with Tesseract.
2. **Remove blank pages:** only truly blank scanned pages. Paper tone, noise and show-through from the back do not count
   as content; a page with only a page number is kept.
3. **Render pages** at native resolution, including overlaid graphics (e.g. highlights).
4. **Text layer:** an existing text layer (e.g. from the iOS scanner) is kept. Otherwise Tesseract recognises the text;
   pages are rotated and deskewed first if needed. If the skew is ambiguous (best angle at the edge of the search range
   or not clearly better than the others – e.g. pages without text lines, or a single word next to a logo), the page is
   not deskewed.
5. **MRC encoding** per page (background at half resolution, JPEG2000); obviously wrong page sizes (e.g. 61 × 86 cm
   from phone scans) are corrected to A4.
6. **Verification:** page count, completeness of the kept text layer and of the text of digital pages, error-free
   rendering with Poppler, smaller file. Only then is the working copy replaced.

On **any error** the file stays unchanged and Paperless processes it as before.

## Requirements

- Paperless-ngx 3.x, uv-based installation (layout of the [community-scripts](https://community-scripts.github.io/ProxmoxVE/)).
- `PAPERLESS_OCR_MODE` set to `auto` (default) and `PAPERLESS_ARCHIVE_FILE_GENERATION` set to `auto` (default) or
  `never`. Paperless then detects the text layer of the compressed file, runs no OCR of its own and creates no second
  file.
- Optional `jbig2` (jbig2enc) for the smallest mask; without it CCITT is used.

## Installation

As root inside the Paperless container:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/Philoneous/paperless-mrc/main/install.sh)"
```

(For a private repository, clone it instead and run `bash install.sh`.)

The installer
- installs the system packages (OpenJPEG tools, Poppler, Tesseract language packs),
- sets up the script in its own Python environment under `/opt/paperless-mrc`,
- adds `PAPERLESS_PRE_CONSUME_SCRIPT` and – if not present yet – `PAPERLESS_OCR_LANGUAGE` to
  `/opt/paperless/paperless.conf` (backup of the file placed next to it),
- aborts if a different pre-consume script is already configured there,
- restarts `paperless-task-queue` and `paperless-consumer`.

**Update:** run the same command again. **Remove:** delete the line `PAPERLESS_PRE_CONSUME_SCRIPT=…` and restart both
services.

## Output

Messages appear in the Paperless log with the prefix `paperless-mrc:` – in English by default, in German with
`MRC_LANGUAGE=de`. In addition, the script writes one machine-readable line per document, independent of the
language, e.g. for the Mac app:

```
paperless-mrc-result: {"version": 1, "file": "scan.pdf", "status": "compressed", "reason": "compressed",
  "size_before": 1482508, "size_after": 46886, "pages": 1, "blank_removed": 1, "photos": 0, "vectorised": 0,
  "digital": 0, "text_layer": "ocr"}
```

- `status`: `compressed`, `unchanged` or `error`
- `reason`: `compressed`, `not_pdf`, `signed`, `no_scanned_pages`, `mixed_disabled`, `nothing_to_compress`
  (plus `photos`, `blank`), `not_smaller` (plus sizes), `error` (plus `message`)
- sizes in bytes; `text_layer`: `kept`, `ocr` or `mixed`

## Configuration

The script takes these Paperless settings from `paperless.conf` (with the same defaults):

| Variable | Effect in the script |
|---|---|
| `PAPERLESS_OCR_LANGUAGE` | Tesseract languages, e.g. `deu+eng` |
| `PAPERLESS_OCR_DESKEW` | Correct skew (only pages without an existing text layer) |
| `PAPERLESS_OCR_ROTATE_PAGES` | Rotate pages (only pages without an existing text layer) |
| `PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD` | Minimum confidence of the rotation detection |
| `PAPERLESS_THREADS_PER_WORKER` | Pages processed at the same time (default as in Paperless: cores ÷ `PAPERLESS_TASK_WORKERS`) |

Values set only in the web interface under *Configuration* are not visible to the script – that is why the installer
also writes the languages to `paperless.conf`.

Own settings (optional, also in `paperless.conf`; without an entry the default applies):

| Variable | Default | Effect |
|---|---|---|
| `MRC_REMOVE_BLANK_PAGES` | `true` | Remove blank scanned pages |
| `MRC_BLANK_INK_PERCENT` | `0.005` | A page is blank below this ink share in % (a page number alone is about 0.05 %) |
| `MRC_BG_DOWNSAMPLE` | `2` | Background at 1/n of the scan resolution (text and lines stay at full resolution) |
| `MRC_BG_COMPRESSION_RATE` | `200` | JPEG2000 compression rate of the background; higher = smaller, but colour areas and light-grey text suffer |
| `MRC_FIT_A4` | `true` | Scale obviously wrong page sizes (e.g. 72 ppi phone scans) to A4 |
| `MRC_SKIP_PHOTOS` | `true` | Leave photo pages unchanged |
| `MRC_PHOTO_PAPER_PERCENT` | `50` | Pages with less paper area in % are checked by text recognition (measured: documents on white paper 61–98 %, photos 11–43 %, insurance pages with coloured boxes below) |
| `MRC_PHOTO_MIN_WORDS` | `10` | … and count as a photo below this many confidently recognised words (confidence ≥ 60, ≥ 3 characters) |
| `MRC_BLANK_PAPER_PERCENT` | `90` | A page can only be blank if at least this share of its area in % is paper tone (protects low-contrast photos) |
| `MRC_VECTOR_PAGES` | `true` | Rasterise and compress vectorised scans |
| `MRC_VECTOR_MIN_ITEMS` | `1000` | A page without image and text counts as a vectorised scan from this many vector elements |
| `MRC_VECTOR_DPI` | `300` | Raster resolution for vectorised scans |
| `MRC_DESKEW_MIN_ANGLE` | `0.2` | Smaller skews (in degrees) are not corrected |
| `MRC_DESKEW_MAX_ANGLE` | `5` | Search range ± in degrees; a result at the edge counts as ambiguous and is not corrected |
| `MRC_DESKEW_MIN_CONFIDENCE` | `1.3` | Only deskew if the best angle clearly stands out (score ≥ factor × median over the search range). Prevents logos or stamps on text-poor pages from tilting a straight page |
| `MRC_MIXED_PDFS` | `true` | Process PDFs with non-scanned pages (these pages stay unchanged); `false`: only pure scan PDFs |
| `MRC_KEEP_TEXT_LAYER` | `true` | Keep an existing text layer; `false`: always recognise again with Tesseract (then also rotate/deskew) |
| `MRC_ROTATE_CHECK` | `true` | If the orientation detection is unsure (below `PAPERLESS_OCR_ROTATE_PAGES_THRESHOLD`) but suggests a rotation, run text recognition in both orientations and rotate only if that gives at least 1.5× as many (and at least 10) confidently recognised words – e.g. landscape forms scanned in portrait |
| `MRC_JOBS` | – | Pages processed at the same time; overrides `PAPERLESS_THREADS_PER_WORKER` (otherwise cores ÷ `PAPERLESS_TASK_WORKERS`) |
| `MRC_SHARPEN` | `150` | Sharpening before encoding in % (unsharp mask); light-grey thin text otherwise partly ends up in the downsampled background and looks blurry. `0` = off |
| `MRC_SHARPEN_RADIUS` | `1.5` | Sharpening radius in pixels at 200 dpi (scaled with the resolution) |
| `MRC_MASK_FACTOR` | `0.5` | Sensitivity of the sharp text mask (factor on recode_pdf's Sauvola thresholds): smaller = light-grey strokes also stay sharp instead of ending up in the downsampled background; `1` = recode_pdf default |
| `MRC_MAX_DPI` | `0` | Maximum resolution in dpi for compressed pages (e.g. `300`); higher-resolution scans are downscaled – faster and smaller, finest details are lost. `0` = off |
| `MRC_TIMING` | `false` | Write run times per page and step to the log (for analysis) |
| `MRC_LANGUAGE` | `en` | Language of the log messages: `en` or `de` |

Deliberately **not** switchable: digitally signed PDFs stay unchanged (otherwise the signature becomes invalid), and the
file is only replaced if verification passed and the result is smaller.

## Limitations

- **Lossy:** the original is replaced; afterwards only the MRC version exists.
- **Duplicate detection:** Paperless compares the incoming file with the stored one. Since what the script produces is
  stored, Paperless no longer recognises a re-uploaded, byte-identical original as a duplicate.
- **"Reprocess"** in Paperless does not run the script again (the file is already compressed).
- Annotations (comments, highlights) on scanned pages are burned into the page image and can no longer be edited.
- Pages with an existing text layer are not rotated or deskewed, because the text layer would no longer match the image.

## Development

```bash
uv sync
uv run pytest                                   # synthetic test cases
PAPERLESS_MRC_TESTFILES=/path/to/scans uv run pytest -k echte   # optional: your own scans
```

Requires `tesseract` (with `deu`), `opj_compress` (libopenjp2-tools) and `pdftoppm` (poppler-utils).

## Licence

GNU Affero General Public License v3.0 or later (`AGPL-3.0-or-later`), see [LICENSE](LICENSE) – matching the
AGPL-licensed dependencies PyMuPDF and archive-pdf-tools.
