import argparse


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-download EasyOCR weights used by ui_click OCR fallback."
    )
    parser.add_argument(
        "--lang",
        default="en",
        help="Comma-separated language list for EasyOCR (default: en)",
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        help="Enable GPU for EasyOCR initialization.",
    )
    args = parser.parse_args()

    langs = [x.strip() for x in args.lang.split(",") if x.strip()]
    if not langs:
        langs = ["en"]

    try:
        import easyocr
    except Exception as e:
        print(f"[ERROR] easyocr import failed: {e}")
        return 1

    print(f"[OCR] Initializing EasyOCR for languages: {','.join(langs)}")
    try:
        try:
            easyocr.Reader(langs, gpu=args.gpu, verbose=False, download_enabled=True)
        except TypeError:
            easyocr.Reader(langs, gpu=args.gpu, download_enabled=True)
    except Exception as e:
        print(f"[ERROR] EasyOCR init/download failed: {e}")
        return 1

    print("[OCR] Models are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
