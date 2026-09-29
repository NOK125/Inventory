#!/usr/bin/env python3
"""สร้าง/อัปเดตโฟลเดอร์ codebase/app จาก static/ ให้เปิดได้โดยไม่ต้องรันเซิร์ฟเวอร์

ใช้ mock-api.js (จำลอง API พร้อมข้อมูลตัวอย่าง) แทน server.py
เหมาะสำหรับนำไปใช้ใน Claude Design หรือเปิดดูหน้าตาด้วยการดับเบิลคลิก index.html

รัน:  python tools/build_codebase.py
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
OUT = ROOT / "codebase" / "app"

DEMO_BANNER = """  <style>
    .demo-banner { position: fixed; right: 12px; bottom: 12px; z-index: 30; background: #b45309; color: #fff;
      font: 600 12px/1.4 "Segoe UI", Tahoma, sans-serif; padding: 4px 10px; border-radius: 99px; opacity: .9; }
    @media print { .demo-banner { display: none; } }
  </style>
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("app.js", "style.css"):
        shutil.copy2(STATIC / name, OUT / name)

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    if '<script src="app.js"></script>' not in html or "</head>" not in html:
        raise SystemExit("static/index.html เปลี่ยนโครงสร้าง ต้องแก้สคริปต์นี้ให้ตรงกัน")
    html = html.replace("</head>", DEMO_BANNER + "</head>", 1)
    html = html.replace(
        '<script src="app.js"></script>',
        '<div class="demo-banner">โหมดตัวอย่าง — ข้อมูลไม่ถูกบันทึก</div>\n'
        '  <script src="mock-api.js"></script>\n'
        '  <script src="app.js"></script>', 1)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"อัปเดต {OUT.relative_to(ROOT)} แล้ว")


if __name__ == "__main__":
    main()
