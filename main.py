#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import zipfile
import io
import os
import re
import tempfile
import shutil
import math
from PIL import Image
import numpy as np
from tqdm import tqdm
Image.MAX_IMAGE_PIXELS = 500_000_000
# ---------- 配置 ----------
INPUT_CBZ = "input.cbz"           # <-- 改为你的输入文件
OUTPUT_CBZ = "output_fixed.cbz"   # <-- 改为你想要的输出文件
INPUT_DIR = "input"
OUTPUT_DIR = "output"

TARGET_WIDTH = 1500
HEIGHT_MAX = 3000+200
HEIGHT_MIN = 1500

# 判断“白”的灰度阈值（0-255）；行被认为“完全白”时，行内所有像素 >= WHITE_THRESH
WHITE_THRESH = 245
#BLACK_THRESH = 30

# 用于合并判断的带高度（判断上一张底部/下一张顶部是否有内容）
DETECT_BAND_PX = 60

OUTPUT_FORMAT = "PNG"
OUTPUT_FORMAT = "jpeg"
# ---------------------------

# ---------- 工具 ----------
def natural_sort_key(s):
    parts = re.split(r'(\d+)', s)
    return [int(p) if p.isdigit() else p.lower() for p in parts]

def pil_to_gray_np(img: Image.Image):
    return np.asarray(img.convert("L"))

def trim_whitespace_all(img: Image.Image, thresh=WHITE_THRESH):
    """裁掉图片四周的接近白色边（上下左右）。若全白则返回原图（避免返回 0 大小）。"""
    arr = np.array(img.convert("L"))
    mask = arr < thresh  # 非白像素为 True
    if not mask.any():
        # 全白：返回原图（保留尺寸），上游会跳过空白段
        return img.copy()
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    top, bottom = rows[0], rows[-1]
    left, right = cols[0], cols[-1]
    return img.crop((left, top, right+1, bottom+1))

def band_has_content(img: Image.Image, top=True, band_h=DETECT_BAND_PX, thresh=WHITE_THRESH):
    """判断顶部/底部 band 是否有任意非白像素（True = 有内容）"""
    arr = pil_to_gray_np(img)
    h = arr.shape[0]
    band_h = min(max(1, band_h), h)
    if top:
        band = arr[0:band_h, :]
    else:
        band = arr[h-band_h:h, :]
    return (band < thresh).any()

def ensure_width_match_no_upscale(a: Image.Image, b: Image.Image):
    """统一宽度到较小者（只缩小，不放大），保护性地避免 0 大小"""
    wa, ha = a.size
    wb, hb = b.size
    if wa <= 0 or ha <= 0 or wb <= 0 or hb <= 0:
        # 保护：返回最小有效白图，避免 crash
        dummy = Image.new("RGB", (1,1), (255,255,255))
        return dummy, dummy
    target = min(wa, wb)
    if wa != target:
        new_h = max(1, int(round(ha * (target / wa))))
        a = a.resize((target, new_h), Image.LANCZOS)
    if wb != target:
        new_h = max(1, int(round(hb * (target / wb))))
        b = b.resize((target, new_h), Image.LANCZOS)
    return a, b

def vstack_images(a: Image.Image, b: Image.Image):
    """垂直拼接 a (上) 与 b (下)，假设宽度已对齐或 will align via ensure_width_match_no_upscale"""
    a, b = ensure_width_match_no_upscale(a, b)
    w = a.size[0]
    out = Image.new("RGB", (w, a.size[1] + b.size[1]), (255,255,255))
    out.paste(a, (0,0))
    out.paste(b, (0,a.size[1]))
    return out

def split_by_full_white_rows(img: Image.Image, thresh=WHITE_THRESH):
    """
    在单张图片中找到“完全白”的行（行内像素全部 >= thresh），把图按这些行作为分界分成若干部分。
    返回分割后的子图列表（若无分界，返回原图列表 [img]）。
    """
    arr = pil_to_gray_np(img)
    h, w = arr.shape
    # is_full_white_row: True if that row is entirely white (>= thresh)
    is_full = np.all(arr >= thresh, axis=1)
    # 找连续的非全白行段（即实际有效图像段）
    nonwhite_idx = np.where(~is_full)[0]
    if nonwhite_idx.size == 0:
        # 整张都是白 —— 返回原图（之后会被忽略）
        return [img]
    # group nonwhite indices into consecutive runs
    groups = []
    start = nonwhite_idx[0]
    prev = nonwhite_idx[0]
    for idx in nonwhite_idx[1:]:
        if idx == prev + 1:
            prev = idx
            continue
        else:
            groups.append((start, prev))
            start = idx
            prev = idx
    groups.append((start, prev))
    parts = []
    for (s,e) in groups:
        # crop from s to e (inclusive)
        part = img.crop((0, s, w, e+1))
        part = trim_whitespace_all(part)
        # 过滤极短或全白的段
        if part.size[0] > 0 and part.size[1] > 0:
            parts.append(part)
    if not parts:
        return [img]
    return parts

def normalize_width_no_upscale(img: Image.Image, target_w=TARGET_WIDTH):
    """宽度标准化：若宽>target_w 则按比缩小；若宽<target_w 不放大而左右居中补白"""
    w,h = img.size
    if w > target_w:
        new_h = int(round(h * (target_w / w)))
        return img.resize((target_w, new_h), Image.LANCZOS)
    elif w < target_w:
        canvas = Image.new("RGB", (target_w, h), (255,255,255))
        left = (target_w - w)//2
        canvas.paste(img, (left, 0))
        return canvas
    else:
        return img

def chunk_by_fixed_height(img: Image.Image, max_h=HEIGHT_MAX, min_h=HEIGHT_MIN):
    """
    将 img 分成若干块：每块高度 <= max_h；按照要求：第一块取 max_h（若剩余不足再分），
    实现方式为顺序切片：先取前 max_h，剩余继续取 max_h，直到耗尽。
    对最后一块若高度 < min_h 则补白到 min_h。
    """
    w,h = img.size
    parts = []
    y = 0
    while y < h:
        take = min(max_h, h - y)
        part = img.crop((0, y, w, y + take))
        if part.size[1] < min_h:
            canvas = Image.new("RGB", (w, min_h), (255,255,255))
            top = (min_h - part.size[1]) // 2
            canvas.paste(part, (0, top))
            part = canvas
        parts.append(part)
        y += take
    return parts

def remove_full_white_rows(im: Image.Image, threshold=245):
    """删除整行都是白色的像素行"""
    w, h = im.size
    pixels = im.load()
    keep_rows = []
    for y in range(h):
        row_white = True
        for x in range(w):
            r, g, b = pixels[x, y]
            if r < threshold or g < threshold or b < threshold:
                row_white = False
                break
        if not row_white:
            keep_rows.append(y)

    if not keep_rows:
        return im  # 全白，直接返回

    top, bottom = min(keep_rows), max(keep_rows)
    return im.crop((0, top, w, bottom + 1))
# ---------- 主流程 ----------
def process_cbz(input_cbz, output_cbz, verbose=True):
    tmpdir = tempfile.mkdtemp(prefix="cbzproc_")
    try:
        # 1) 读取并按自然排序（不裁白）
        with zipfile.ZipFile(input_cbz, 'r') as zin:
            names = sorted(zin.namelist(), key=natural_sort_key)
            image_entries = [n for n in names if not n.endswith('/') and any(n.lower().endswith(ext) for ext in ('.png','.jpg','.jpeg','.webp','.bmp','.gif'))]
            if verbose:
                print(f"Found {len(image_entries)} image files in archive.")
            images = []
            for name in image_entries:
                with zin.open(name) as f:
                    im = Image.open(io.BytesIO(f.read())).convert("RGB")
                images.append(im)

        # 2) 合并跨页（保持你现在满意的合并逻辑，不改）
        merged_panels = []
        i = 0
        merges = 0
        pbar = tqdm(total=len(images), desc="Merging", unit="img")
        while i < len(images):
            cur_img = images[i]
            j = i
            while j + 1 < len(images):
                next_img = images[j+1]
                cur_has = band_has_content(cur_img, top=False)
                nxt_has = band_has_content(next_img, top=True)
                if cur_has and nxt_has:
                    a, b = ensure_width_match_no_upscale(cur_img, next_img)
                    cur_img = vstack_images(a, b)
                    merges += 1
                    j += 1
                    continue
                break
            # 合并结束后再裁四周白边（这一点不改）
            cur_img = trim_whitespace_all(cur_img)
            merged_panels.append(cur_img)
            i = j + 1
            pbar.update(j - i + 1 if j - i + 1 > 0 else 1)
        pbar.close()
        if verbose:
            print(f"Merging done: input_images={len(images)} -> merged_panels={len(merged_panels)} (merges={merges})")

        # 3) 第二次处理：在每个合并后的图中按**完整白行**进行切分（若存在）
        split_panels = []
        split_count = 0
        pbar = tqdm(total=len(merged_panels), desc="Second-pass split by full-white rows", unit="panel")
        for mp in merged_panels:
            parts = split_by_full_white_rows(mp, thresh=WHITE_THRESH)
            if len(parts) > 1:
                split_count += (len(parts) - 1)
            # parts 已经 trim 过（函数内部会 trim），但再次确保
            for p in parts:
                p = trim_whitespace_all(p)
                # 忽略完全空白的小图（若出现）
                arr = pil_to_gray_np(p)
                if not (arr < WHITE_THRESH).any():
                    # 全白 => 跳过
                    continue
                split_panels.append(p)
            pbar.update(1)
        pbar.close()
        if verbose:
            print(f"After full-row-split: panels={len(split_panels)} (split_count={split_count})")

        # 4) 对每个 panel 归一化宽度（不放大），并对超过 HEIGHT_MAX 的 panel 按固定高度切片（first=3000）
        processed_panels = []
        chunked_count = 0
        pbar = tqdm(total=len(split_panels), desc="Normalize & chunk oversized panels", unit="panel")
        for p in split_panels:
            norm = normalize_width_no_upscale(p, TARGET_WIDTH)
            if norm.size[1] > HEIGHT_MAX:
                parts = chunk_by_fixed_height(norm, max_h=HEIGHT_MAX, min_h=HEIGHT_MIN)
                if len(parts) > 1:
                    chunked_count += (len(parts) - 1)
                processed_panels.extend(parts)
            else:
                processed_panels.append(norm)
            pbar.update(1)
        pbar.close()
        if verbose:
            print(f"Panels after chunking: {len(processed_panels)} (chunked_extra={chunked_count})")

        # 5) 最后排版：顺序放入页面（累加高度，若加入会超过 HEIGHT_MAX 则换页）
        pages = []
        cur_blocks = []
        cur_h = 0
        for panel in tqdm(processed_panels, desc="Layout into pages", unit="blk"):
            ph = panel.size[1]
            if cur_h + ph <= HEIGHT_MAX:
                cur_blocks.append(panel)
                cur_h += ph
            else:
                # flush current page
                if cur_blocks:
                    total_h = sum(b.size[1] for b in cur_blocks)
                    canvas_h = max(total_h, HEIGHT_MIN)
                    canvas = Image.new("RGB", (TARGET_WIDTH, canvas_h), (255,255,255))
                    y = 0
                    for b in cur_blocks:
                        canvas.paste(b, (0, y))
                        y += b.size[1]
                    pages.append(canvas)
                # start new page with this panel
                cur_blocks = [panel]
                cur_h = ph
        # flush last
        if cur_blocks:
            total_h = sum(b.size[1] for b in cur_blocks)
            canvas_h = max(total_h, HEIGHT_MIN)
            canvas = Image.new("RGB", (TARGET_WIDTH, canvas_h), (255,255,255))
            y = 0
            for b in cur_blocks:
                canvas.paste(b, (0, y))
                y += b.size[1]
            pages.append(canvas)

        if verbose:
            print(f"Final pages: {len(pages)}")
        pages = [remove_full_white_rows(pg, threshold=WHITE_THRESH) for pg in pages]


        # 6) 保存到临时目录再压缩为 cbz
        out_dir = os.path.join(tmpdir, "out")
        os.makedirs(out_dir, exist_ok=True)
        for idx, pg in enumerate(pages, start=1):
            fname = f"{idx:04d}.png"
            pg.save(os.path.join(out_dir, fname), format=OUTPUT_FORMAT)

        with zipfile.ZipFile(output_cbz, 'w', compression=zipfile.ZIP_STORED) as zout:
            files = sorted(os.listdir(out_dir), key=natural_sort_key)
            for f in files:
                zout.write(os.path.join(out_dir, f), arcname=f)

        if verbose:
            print(f"Saved -> {output_cbz}")
            print(f" Stats: input_images={len(images)}, merged_panels={len(merged_panels)}, after_row_split={len(split_panels)}, processed_panels={len(processed_panels)}, pages_out={len(pages)}")
            print(f" merges={merges}, row_splits={split_count}, chunked_extra={chunked_count}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ---------- 运行 ----------
if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cbz_files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(".cbz")]
    for fname in cbz_files:
        inp = os.path.join(INPUT_DIR, fname)
        out = os.path.join(OUTPUT_DIR, fname)
        process_cbz(inp, out)
