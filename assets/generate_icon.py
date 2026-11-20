"""生成 assets/icon.ico（窗口与 exe 图标）— 第一版手绘多尺寸。"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "icon.ico"
PNG_OUT = ROOT / "icon.png"

# 含 20/40/96 便于 Win10/11 高分屏任务栏与标题栏选到合适帧
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    bg = (30, 39, 46, 255)
    accent = (58, 130, 246, 255)
    moon = (147, 197, 253, 255)
    d.rounded_rectangle(
        (pad, pad, size - pad - 1, size - pad - 1),
        radius=max(2, size // 5),
        fill=bg,
        outline=accent,
        width=max(1, size // 32),
    )
    cx, cy = size // 2, size // 2
    r = size // 4
    d.ellipse((cx - r, cy - r, cx + r - 1, cy + r - 1), fill=moon)
    cut = r // 2
    d.ellipse(
        (cx + cut // 2, cy - r, cx + r + cut, cy + r),
        fill=bg,
    )
    if size >= 32:
        bar_w = max(2, size // 10)
        y0 = size - pad - size // 6
        x0 = cx - size // 5
        x1 = cx + size // 5
        d.rounded_rectangle(
            (x0, y0, x1, y0 + bar_w), radius=1, fill=accent
        )
    return img


def main() -> None:
    images = [draw_icon(s) for s in SIZES]
    images[-1].save(PNG_OUT, format="PNG")
    # 以 256 为主图写入多帧 ICO（避免第一版仅 16×16 的损坏文件）
    images[-1].save(
        OUT,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=images[:-1],
    )
    print(f"Wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()