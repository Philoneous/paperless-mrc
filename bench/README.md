# Readability benchmark

How the default quality settings were chosen (needs the DejaVu fonts, e.g. `fonts-dejavu-core`). A test page with known text (body text, small print down to 5 pt,
thin, light-grey and coloured text, text on coloured backgrounds) is rendered, turned into a simulated office scan
(200 and 300 dpi: slight blur, paper tone, noise, JPEG) and compressed with each setting. Every line is then recognized
again with Tesseract from the image only and compared with the known text (character error rate); SSIM against the
clean page measures fidelity. `crops.py` puts the same lines from several results side by side for visual checks.

```bash
uv run python bench/make_pages.py pages
uv run python bench/run_bench.py pages results scan= default= sharp100=sharpen:100 mask1=mask_sensitivity:1.0
uv run python bench/report.py results/results.json default
uv run python bench/crops.py pages 200 crops.png "Sehr hellgrau 7" results/pdf/default@200.pdf results/pdf/sharp100@200.pdf
```

Result (November 2026): the defaults (sharpening 150 %, radius 1.5, mask factor 0.5, background 1/2 at rate 200, no
maximum resolution) gave the most complete and even strokes for faint and thin text at both resolutions. Less
sharpening (100 %) or a smaller radius scored a higher SSIM – closer to the light tone of the original – but strokes of
faint text broke up visibly; 200 % and more increased recognition errors. A full-resolution background made files about
1.7 times as large without any gain in readability; 1/3 or rate 400 saved about 11 % but increased errors at 200 dpi.
`MRC_MAX_DPI=200` halved a 300-dpi page, but digits in 6 pt print started being misread.
