"""
One-off diagnostic — NOT part of the pipeline. Finds out in a few seconds
whether pymupdf's OCR can actually run on this machine, and if not, why,
without waiting through a multi-minute --full rebuild to find out.

Usage:
    python ocr_probe.py
"""
import glob
import os

import pymupdf

print(f"pymupdf version: {pymupdf.__version__}")
print(f"TESSDATA_PREFIX env var: {os.environ.get('TESSDATA_PREFIX') or '(not set)'}\n")

candidates = [
    os.environ.get("TESSDATA_PREFIX", ""),
    "/opt/homebrew/share/tessdata",
    "/usr/local/share/tessdata",
    "/usr/share/tessdata",
    *sorted(glob.glob("/usr/share/tesseract-ocr/*/tessdata")),
]

print("Checking candidate tessdata locations:")
found_any = False
for c in candidates:
    if not c:
        continue
    exists = os.path.isdir(c)
    traineddata = glob.glob(os.path.join(c, "*.traineddata")) if exists else []
    status = f"{len(traineddata)} language file(s)" if traineddata else ("empty/no .traineddata" if exists else "no such directory")
    print(f"  {c}: {status}")
    if traineddata:
        found_any = True

if not found_any:
    print(
        "\nNo tessdata found in any known location. Find yours with:\n"
        "  brew --prefix tesseract\n"
        "  find \"$(brew --prefix tesseract)\" -name '*.traineddata'\n"
        "then re-run this script with:\n"
        "  TESSDATA_PREFIX=<the folder that .traineddata file is in> python ocr_probe.py"
    )
else:
    print("\nTrying each one against a real OCR call...")
    for c in candidates:
        if not c or not os.path.isdir(c) or not glob.glob(os.path.join(c, "*.traineddata")):
            continue
        os.environ["TESSDATA_PREFIX"] = c
        try:
            doc = pymupdf.open()
            page = doc.new_page(width=100, height=100)
            page.get_textpage_ocr(flags=0, full=False)
            doc.close()
            print(f"  SUCCESS with TESSDATA_PREFIX={c}")
            print(
                f"\nThis works. build_index.py's own auto-discovery should find this "
                f"automatically now — no need to set TESSDATA_PREFIX by hand. If a real "
                f"--full rebuild still reports OCR unavailable, run:\n"
                f"  TESSDATA_PREFIX={c} python build_index.py --full\n"
                f"and let me know either way."
            )
            break
        except Exception as e:
            print(f"  FAILED with TESSDATA_PREFIX={c}: {e}")
    else:
        print("\nNone of the candidate tessdata folders actually worked — paste this full output back.")
