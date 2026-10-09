#!/usr/bin/env python3
"""oku.py için en küçük MCP (stdio, JSON-RPC) sunucusu.

Araştırma çalışanlarına `webfetch` yerine SIKIŞTIRILMIŞ sayfa okuma verir (jeton tasarrufu + tutarlı enjeksiyon uyarısı):
  sayfa_oku(url, soru?, token?)      sorguya göre yalnız ilgili pasajlar (BM25) + başlık anahatları
  sayfada_ara(url, ifadeler[])       rakam/alıntı sayfada geçiyor mu? (bağlamıyla)
Ortam: OKU_ONBELLEK=dizin → sayfa deposu (aynı sayfa tekrar çekilmez).
stdout YALNIZ JSON-RPC satırları içerir; günlük stderr'e gider.
"""
import json
import os
import sys

sys.dont_write_bytecode = True  # skill dizininde __pycache__/.pyc üretme (taranamayan ikili dosya)
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oku  # noqa: E402

TOOLS = [
    {"name": "sayfa_oku",
     "description": "Bir web sayfasını tarayıcısız okur, gürültüyü atar ve YALNIZ ilgili pasajları kısa Markdown olarak döndürür. "
                    "Tam sayfayı bağlama almaktan çok daha az jeton harcar. soru: ne aradığın (kısa anahtar kelimeler).",
     "inputSchema": {"type": "object", "properties": {
         "url": {"type": "string", "description": "http/https adresi"},
         "soru": {"type": "string", "description": "sayfada aranan konu/anahtar kelimeler"},
         "token": {"type": "integer", "description": "çıktı bütçesi (varsayılan 900, en çok 3000)"}},
         "required": ["url"]}},
    {"name": "sayfada_ara",
     "description": "Bir rakamın, sürümün ya da birebir alıntının sayfada GEÇİP GEÇMEDİĞİNİ denetler ve bağlamını verir. İddia doğrulamak için kullan.",
     "inputSchema": {"type": "object", "properties": {
         "url": {"type": "string"},
         "ifadeler": {"type": "array", "items": {"type": "string"}, "description": "aranacak ifade/rakamlar (en çok 6)"}},
         "required": ["url", "ifadeler"]}},
]


SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
_READ_CALLS = 0


def read_budget():
    """Hafif işçiye verilen süreç başı okuyucu sınırı; diğer kullanımlar sınırsızdır."""
    raw = os.environ.get("OKU_CAGRI_BUTCE")
    if raw is None:
        return None
    if not raw.isdecimal() or int(raw) < 1:
        raise ValueError("OKU_CAGRI_BUTCE pozitif tam sayı olmalı")
    return int(raw)


def call_tool(name, args):
    if not isinstance(args, dict):
        raise ValueError("arguments nesne olmalı")
    cache = os.environ.get("OKU_ONBELLEK")
    url = args.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url (metin) zorunlu")
    if name == "sayfa_oku":
        soru = args.get("soru")
        r = oku.read(url.strip(), soru=soru if isinstance(soru, str) else None,
                     token=max(200, min(int(args.get("token") or 900), 3000)), cache_dir=cache)
    elif name == "sayfada_ara":
        raw = args.get("ifadeler")
        phrases = [str(p) for p in (raw if isinstance(raw, list) else [raw] if isinstance(raw, str) else []) if str(p).strip()][:6]
        if not phrases:
            raise ValueError("ifadeler boş")
        r = oku.read(url.strip(), ara=phrases, cache_dir=cache)
    else:
        raise ValueError(f"bilinmeyen araç: {name}")
    return oku.render(r), (not r["ok"])


def error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle(req):
    """Tek JSON-RPC isteğini işler; yanıt sözlüğü ya da (bildirimse) None döner."""
    if not isinstance(req, dict):
        return error(None, -32600, "geçersiz istek (nesne bekleniyor)")
    method, rid = req.get("method"), req.get("id")
    if rid is None:  # bildirim (ör. notifications/initialized) — yanıt verilmez
        return None
    if not isinstance(method, str):
        return error(rid, -32600, "geçersiz istek (method yok)")
    if method == "initialize":
        asked = (req.get("params") or {}).get("protocolVersion") if isinstance(req.get("params"), dict) else None
        version = asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]   # istemci bilinmeyen sürüm isterse bizimkini öner
        return {"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": version, "capabilities": {"tools": {}},
                                                          "serverInfo": {"name": "oku", "version": "1.1"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = req.get("params") if isinstance(req.get("params"), dict) else {}
        try:
            global _READ_CALLS
            if params.get("name") in ("sayfa_oku", "sayfada_ara"):
                limit = read_budget()
                if limit is not None and _READ_CALLS >= limit:
                    raise ValueError("Okuma bütçesi doldu; mevcut kanıtla dört bölümlü nihai notu yaz, eksikleri Boşluklar bölümüne koy.")
                _READ_CALLS += 1  # hata veren okuma da bütçeyi tüketir; yinelenen çağrılar sınırsız olamaz
            text, is_error = call_tool(params.get("name"), params.get("arguments") or {})
        except Exception as e:  # araç hatası protokol hatası değildir
            text, is_error = f"HATA: {e}", True
        return {"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}], "isError": is_error}}
    return error(rid, -32601, f"yöntem yok: {method}")


def emit(resp):
    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            emit(error(None, -32700, "JSON ayrıştırma hatası"))
            continue
        try:
            if isinstance(req, list):   # JSON-RPC toplu istek
                out = [r for r in (handle(x) for x in req) if r is not None]
                if out:
                    emit(out)
                continue
            resp = handle(req)
        except Exception as e:   # sunucu hiçbir girdide çökmez
            resp = error(req.get("id") if isinstance(req, dict) else None, -32603, f"iç hata: {type(e).__name__}")
        if resp is not None:
            emit(resp)


if __name__ == "__main__":
    main()
