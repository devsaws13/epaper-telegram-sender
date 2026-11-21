# -*- coding: utf-8 -*-
import datetime
import gc
import os
import tempfile
import time
from io import BytesIO

import requests
from bs4 import BeautifulSoup
from PIL import Image

# --- CONFIGURATION FROM GITHUB SECRETS ---
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
MAX_TELEGRAM_BYTES = 48 * 1024 * 1024  # 48 MB safety buffer (Telegram cap is 50 MB)

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

MAGAZINES = {
    6: "ravipurti", 0: None, 1: "sahiyar", 2: "shatdal",
    3: "dharmalok", 4: "chitralok", 5: "zagmag"
}

CITIES = [
    "ahmedabad", "ahmedabad-east", "gujarat-samachar-plus",
    "mumbai", "baroda", "surat", "rajkot-saurashtra",
    "bhavnagar", "bhuj", "rajkot-city"
]

DISTRICTS = [
    "kheda-anand", "gandhinagar", "mehsana", "sabarkantha",
    "surendranagar", "bharuch-panchmahal", "vapi-valsad",
    "bhavnagar-local", "patan", "banaskantha", "junagadh",
    "saurashtra"
]

GUJARATI_NAMES = {
    "ravipurti": "રવિપૂર્તિ",
    "sahiyar": "સહિયર",
    "shatdal": "શતદલ",
    "dharmalok": "ધર્મલોક",
    "chitralok": "ચિત્રલોક",
    "zagmag": "ઝગમગ",
    "ahmedabad": "અમદાવાદ",
    "ahmedabad-east": "અમદાવાદ પૂર્વ",
    "gujarat-samachar-plus": "ગુજરાત સમાચાર પ્લસ",
    "mumbai": "મુંબઈ",
    "baroda": "વડોદરા",
    "surat": "સુરત",
    "rajkot-saurashtra": "રાજકોટ-સૌરાષ્ટ્ર",
    "bhavnagar": "ભાવનગર",
    "bhuj": "ભુજ",
    "rajkot-city": "રાજકોટ શહેર",
    "kheda-anand": "ખેડા-આણંદ",
    "gandhinagar": "ગાંધીનગર",
    "mehsana": "મહેસાણા",
    "sabarkantha": "સાબરકાંઠા",
    "surendranagar": "સુરેન્દ્રનગર",
    "bharuch-panchmahal": "ભરૂચ-પંચમહાલ",
    "vapi-valsad": "વાપી-વલસાડ",
    "bhavnagar-local": "ભાવનગર લોકલ",
    "patan": "પાટણ",
    "banaskantha": "બનાસકાંઠા",
    "junagadh": "જૂનાગઢ",
    "saurashtra": "સૌરાષ્ટ્ર"
}

GUJARATI_DAYS = {
    0: "સોમ", 1: "મંગળ", 2: "બુધ", 3: "ગુરુ", 4: "શુક્ર", 5: "શનિ", 6: "રવિ"
}


class StreamingPDFWriter:
    def __init__(self, filepath):
        self.filepath = filepath
        self.f = open(filepath, "wb")
        self.offsets = {}
        self.page_kids = []
        self.page_count = 0
        self.f.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        self.offsets[1] = self.f.tell()
        self.f.write(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")

    def add_jpeg_page(self, jpeg_bytes, width, height):
        self.page_count += 1
        k = self.page_count
        img_id = 3 * k
        content_id = 3 * k + 1
        page_id = 3 * k + 2

        self.offsets[img_id] = self.f.tell()
        img_header = (
            f"{img_id} 0 obj\n"
            f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
            f"/Length {len(jpeg_bytes)} >>\nstream\n"
        ).encode("ascii")
        self.f.write(img_header)
        self.f.write(jpeg_bytes)
        self.f.write(b"\nendstream\nendobj\n")

        stream_data = f"q {width} 0 0 {height} 0 0 cm /Im1 Do Q".encode("ascii")
        self.offsets[content_id] = self.f.tell()
        content_obj = (
            f"{content_id} 0 obj\n<< /Length {len(stream_data)} >>\nstream\n"
        ).encode("ascii") + stream_data + b"\nendstream\nendobj\n"
        self.f.write(content_obj)

        self.offsets[page_id] = self.f.tell()
        page_obj = (
            f"{page_id} 0 obj\n"
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
            f"/Resources << /XObject << /Im1 {img_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>\nendobj\n"
        ).encode("ascii")
        self.f.write(page_obj)
        self.page_kids.append(f"{page_id} 0 R")

    def finalize(self):
        kids_str = " ".join(self.page_kids)
        self.offsets[2] = self.f.tell()
        pages_obj = (
            f"2 0 obj\n<< /Type /Pages /Kids [{kids_str}] /Count {self.page_count} >>\nendobj\n"
        ).encode("ascii")
        self.f.write(pages_obj)

        xref_offset = self.f.tell()
        max_obj = 3 * self.page_count + 2
        self.f.write(f"xref\n0 {max_obj + 1}\n".encode("ascii"))
        self.f.write(b"0000000000 65535 f \n")
        for obj_id in range(1, max_obj + 1):
            self.f.write(f"{self.offsets[obj_id]:010d} 00000 n \n".encode("ascii"))

        trailer = (
            f"trailer\n<< /Size {max_obj + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
        self.f.write(trailer)
        self.f.close()

    def abort(self):
        try:
            self.f.close()
        except Exception:
            pass


def fetch_edition_pdf(keyword, date_str, out_dir, compress=False):
    pdf_path = os.path.join(out_dir, f"{keyword}_{date_str}.pdf")
    base_url = f"https://epaper.gujaratsamachar.com/{keyword}/{date_str}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    seen_urls = set()
    page_num = 1
    session = requests.Session()
    session.headers.update(headers)
    writer = None

    try:
        while True:
            url = f"{base_url}/{page_num}"
            try:
                resp = session.get(url, timeout=15)
                if resp.status_code != 200 or "404" in resp.url:
                    break
            except Exception as e:
                print(f"[{keyword}] Page {page_num} fetch error: {e}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            img_url = None
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if not src:
                    continue
                src_lower = src.lower()
                if any(x in src_lower for x in ["logo", "icon", "assets", "svg", "thumb"]):
                    continue
                if any(x in src_lower for x in ["upload", "epaper", keyword, "page"]):
                    img_url = src
                    break

            if not img_url:
                break

            if not img_url.startswith("http"):
                img_url = "https://epaper.gujaratsamachar.com" + img_url
            if "thumbnail" in img_url:
                img_url = img_url.replace("thumbnail", "master")
            if img_url in seen_urls:
                break
            seen_urls.add(img_url)

            img_resp = session.get(img_url, timeout=20)
            if img_resp.status_code != 200:
                break

            raw_data = img_resp.content
            with Image.open(BytesIO(raw_data)) as pil_img:
                w, h = pil_img.size
                is_baseline_rgb = (
                    pil_img.format == "JPEG"
                    and pil_img.mode == "RGB"
                    and not pil_img.info.get("progressive")
                )

                if is_baseline_rgb and not compress:
                    jpeg_bytes = raw_data
                else:
                    if pil_img.mode != "RGB":
                        pil_img = pil_img.convert("RGB")
                    max_w = 2000 if compress else 3200
                    quality = 80 if compress else 92
                    if pil_img.width > max_w:
                        ratio = max_w / float(pil_img.width)
                        pil_img = pil_img.resize(
                            (max_w, int(pil_img.height * ratio)),
                            Image.Resampling.LANCZOS,
                        )
                        w, h = pil_img.size
                    buf = BytesIO()
                    pil_img.save(buf, format="JPEG", quality=quality, subsampling=0, progressive=False)
                    jpeg_bytes = buf.getvalue()

            if writer is None:
                writer = StreamingPDFWriter(pdf_path)
            writer.add_jpeg_page(jpeg_bytes, w, h)
            page_num += 1
            gc.collect()

        if writer and writer.page_count > 0:
            writer.finalize()
            return pdf_path, writer.page_count

        if writer:
            writer.abort()
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        return None, 0
    finally:
        session.close()


def send_telegram_document(filepath, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    for attempt in range(3):
        with open(filepath, "rb") as doc:
            resp = requests.post(
                url,
                data={"chat_id": CHAT_ID, "caption": caption},
                files={"document": (os.path.basename(filepath), doc, "application/pdf")},
                timeout=120,
            )
        if resp.status_code == 200:
            return True
        if resp.status_code == 429:
            retry_after = resp.json().get("parameters", {}).get("retry_after", 10)
            print(f"Rate limited by Telegram. Waiting {retry_after}s...")
            time.sleep(retry_after + 1)
        else:
            print(f"Telegram upload failed ({resp.status_code}): {resp.text}")
            time.sleep(5)
    return False


def main():
    now_ist = datetime.datetime.now(IST)
    today_str = now_ist.strftime("%d-%m-%Y")
    guj_day = GUJARATI_DAYS[now_ist.weekday()]

    targets = []
    today_mag = MAGAZINES.get(now_ist.weekday())
    if today_mag:
        targets.append(today_mag)
    targets.extend(CITIES)
    targets.extend(DISTRICTS)

    print(f"Starting daily sync for {today_str} ({len(targets)} editions)...")
    sent_count = 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        for kw in targets:
            guj_name = GUJARATI_NAMES.get(kw, kw.title())
            print(f"Fetching {kw}...")

            pdf_path, pages = fetch_edition_pdf(kw, today_str, tmp_dir, compress=False)
            if not pdf_path:
                print(f"Skipped {kw} (not published / holiday).")
                continue

            # If full-HD PDF exceeds Telegram's 50 MB Bot API limit, rebuild slightly compressed
            if os.path.getsize(pdf_path) > MAX_TELEGRAM_BYTES:
                print(f"{kw} exceeded 48 MB; rebuilding compressed version for Telegram...")
                os.remove(pdf_path)
                pdf_path, pages = fetch_edition_pdf(kw, today_str, tmp_dir, compress=True)

            if pdf_path and os.path.getsize(pdf_path) <= MAX_TELEGRAM_BYTES:
                caption = f"📰 {guj_name} ({guj_day}, {today_str}) | {pages} પેજ"
                if send_telegram_document(pdf_path, caption):
                    sent_count += 1
                    print(f"Sent {kw} ({pages} pages) to Telegram.")
                os.remove(pdf_path)
                time.sleep(3)  # Prevent Telegram flood limits
            else:
                print(f"Skipped {kw}: still above Telegram 50 MB limit.")

    print(f"Done. Delivered {sent_count}/{len(targets)} editions.")


if __name__ == "__main__":
    main()
