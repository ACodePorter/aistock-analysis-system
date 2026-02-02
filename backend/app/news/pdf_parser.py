import asyncio
import hashlib
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx

from .pdf_manager import get_cached_text, save_cached_text

logger = logging.getLogger(__name__)

# cache directory for downloaded pdfs and extracted text
BASE_CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "temp", "pdf_cache")
os.makedirs(BASE_CACHE, exist_ok=True)

# limit concurrent pdf extractions
_pdf_semaphore = asyncio.Semaphore(int(os.getenv('PDF_MAX_CONCURRENCY', '3')))


def _hash_key(url: str) -> str:
    return hashlib.sha256(url.encode('utf-8')).hexdigest()


def _cache_paths(hashkey: str):
    pdf_path = os.path.join(BASE_CACHE, f"{hashkey}.pdf")
    txt_path = os.path.join(BASE_CACHE, f"{hashkey}.txt")
    return pdf_path, txt_path


def _extract_text_sync(pdf_path: str) -> str:
    """同步文本提取：优先使用 pypdf -> pdfminer.six -> 可选 OCR（若安装）"""
    # try pypdf
    try:
        from pypdf import PdfReader
        text_parts = []
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            try:
                t = page.extract_text() or ''
            except Exception:
                t = ''
            if t:
                text_parts.append(t)
        text = '\n'.join(text_parts).strip()
        if text:
            return text
    except Exception:
        logger.debug('pypdf extraction failed or not available')

    # try pdfminer
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(pdf_path) or ''
        if text:
            return text.strip()
    except Exception:
        logger.debug('pdfminer extraction failed or not available')

    # fallback OCR if pillow + pytesseract available
    try:
        from PIL import Image
        import pytesseract
        # simple per-page rasterization using pypdf to render pages as images is not implemented here
        # try converting first page via pdf2image if available
        try:
            from pdf2image import convert_from_path
            images = convert_from_path(pdf_path, first_page=1, last_page=3)
            texts = []
            for im in images:
                texts.append(pytesseract.image_to_string(im, lang='chi_sim'))
            text = '\n'.join(texts).strip()
            if text:
                return text
        except Exception:
            logger.debug('pdf2image not available or convert failed')
    except Exception:
        logger.debug('OCR libs not available')

    return ''


async def download_pdf(url: str, timeout: float = 30.0) -> Optional[str]:
    """下载 PDF 到缓存并返回本地路径。若已缓存则直接返回。"""
    key = _hash_key(url)
    pdf_path, txt_path = _cache_paths(key)
    if os.path.exists(pdf_path):
        return pdf_path

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and resp.content:
                # save
                with open(pdf_path, 'wb') as f:
                    f.write(resp.content)
                return pdf_path
    except Exception as e:
        logger.debug(f"Failed to download pdf {url}: {e}")
    return None


_executor = ThreadPoolExecutor(max_workers=2)


async def extract_text_from_pdf(url: str) -> Optional[str]:
    """高层协程：下载并解析 PDF，使用 Mongo + disk 缓存，同时限制并发。"""
    # check mongo cache first
    try:
        cached = await get_cached_text(url)
        if cached:
            return cached
    except Exception:
        logger.debug('pdf cache lookup failed')

    key = _hash_key(url)
    pdf_path, txt_path = _cache_paths(key)

    # if text cached on disk, return and save to mongo
    if os.path.exists(txt_path):
        try:
            with open(txt_path, 'r', encoding='utf-8') as f:
                txt = f.read()
                try:
                    await save_cached_text(url, txt, status='ok')
                except Exception:
                    pass
                return txt
        except Exception:
            pass

    # download
    pdf_local = await download_pdf(url)
    if not pdf_local:
        try:
            await save_cached_text(url, None, status='failed', error='download_failed')
        except Exception:
            pass
        return None

    async with _pdf_semaphore:
        loop = asyncio.get_running_loop()
        try:
            text = await loop.run_in_executor(_executor, _extract_text_sync, pdf_local)
            if text:
                try:
                    with open(txt_path, 'w', encoding='utf-8') as f:
                        f.write(text)
                except Exception:
                    logger.debug('Failed to write cached text')
                try:
                    await save_cached_text(url, text, status='ok')
                except Exception:
                    logger.debug('Failed to save to mongo cache')
                return text
            else:
                try:
                    await save_cached_text(url, None, status='empty', error='no_text_extracted')
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f'Error extracting pdf text: {e}')
            try:
                await save_cached_text(url, None, status='failed', error=str(e))
            except Exception:
                pass

    return None
