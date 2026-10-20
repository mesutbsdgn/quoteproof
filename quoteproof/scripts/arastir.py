#!/usr/bin/env python3
"""quoteproof çalıştırıcısı: PLAN.json → paralel araştırma çalışanları → notlar/ → denetim.

Kullanım:
  arastir.py PLAN.json -d ARASTIRMA_DIZINI [--arka otomatik|opencode|cli] [--model AD]
             [-e dusuk|orta|yuksek] [-j 3] [-t 420] [--kuru] [--link-yok] [--arama-yok] [--devam]

Arka uçlar (model/sağlayıcı/anahtar ayrıntıları koda gömülü değildir: quoteproof.json — bkz. ayar.py, quoteproof.example.json):
  opencode  OpenCode ajan çalışma ortamı (plan modu; araç kilidi kapalı-varsayılan: yalnız yerleşik `websearch` + `oku_*` MCP ya da `webfetch`).
  cli       Yapılandırmada tanımlı komut satırı arka ucu (cli_backend; çıktı "responses-json", düz "text", "claude-stream-json" ya da "codex-jsonl"; istem argümanla ya da stdin'den).
  otomatik  (varsayılan) önce opencode, başarısızsa cli. Kullanılamayan arka uçlar zincirden çıkarılır.

PLAN.json: [{"slug","konu","amac","sorular":[...],"kaynaklar","kisitlar",
             "single_publisher_host":"rfc-editor.org" (isteğe bağlı)}, ...]
Çıktı dizini: istemler/<slug>.md · notlar/<slug>.md · calisma.json · denetim.md · dogrulama.md · destek.md ·
             bagimsizlik.md (kaynak bağımsızlığı: kopya kümeleri tek oy)
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys

sys.dont_write_bytecode = True  # skill dizininde __pycache__/.pyc üretme (taranamayan ikili dosya)
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ayar  # noqa: E402
import bagimsizlik  # noqa: E402
import destek  # noqa: E402
import kapsama  # noqa: E402
import denetle  # noqa: E402

TEMPLATE = HERE.parent / "references" / "arastirmaci-istemi.md"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
PUBLISHER_HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
MIN_NOTE_BYTES = 300
MAX_PARALLEL = 4
# Araştırma çalışanı yalnız arama/okuma yapar: kabuk ve dosya yazma kapalı.
OPENCODE_PERMISSIONS = {"permission": {"bash": "deny", "edit": "deny", "write": "deny", "external_directory": "deny", "doom_loop": "deny"}}
REQUIRED_SECTION = "Alıntılı bulgular"   # çalışan çıktı sözleşmesi (references/arastirmaci-istemi.md)
# 8 Eki 2026 (İHA araştırma deneyi): bir çalışan araştırma yapmadan "Plan Modu etkin, onayınıza sunuyorum" planı döndürdü; planda
# "Alıntılı bulgular" ifadesi geçtiği için düz alt dize denetimi onu BAŞARILI saydı. Artık: gerçek markdown başlığı + varsayılan MIN_URLS
# (konu bazında min_url_required) benzersiz URL + plan/onay dili yok + (OpenCode'da) en az bir arama/okuma aracı çağrısı.
HEADING_RE = re.compile(r"(?m)^#{2,4}[ \t]*Alıntılı bulgular\b")
URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
_HOST_RE = re.compile(r"https?://([^/\s)>\]\"']+)", re.I)   # ziyaret edilen alan adı (boşluk turu "zaten okuduk" notu)
PLAN_RE = re.compile(r"(?i)plan modu|onay(?:ına|ınıza|ınızı|ınız)\s+(?:sun|bekle)|yaklaşımı onay|onaylarsanız|onay vermenizi|awaiting (?:your )?approval")
# 8 Eki 2026: arama sağlayıcısı oturum boyunca 429 verdi; çalışan "Araştırma tamamlanamadı, arama altyapısı çöktü" yazıp 3 denemede aynı duvara çarptı.
# Yalnız arama aracı/sağlayıcısı hatası açıkça raporlanınca aynı arka ucu yeniden deneme (rc=10). Araştırma içeriğindeki HTTP 429/rate-limit
# bilgileri tek başına hata sinyali değildir (örn. robots.txt belgeleri 429 istisnasından söz eder).
RATE_RE = re.compile(
    r"(?i)(?:"
    r"\bapi error:\s*(?:rate limit|429\b|overloaded)"                       # O5: cli `text` kipinde exit 0 + stdout'a düşen API hatası
    r"|\brate limit reached\b"
    r"|\boverloaded\b"
    r"|\barama (?:altyapısı|sağlayıcısı) çöktü\b"
    r"|(?:\bwebsearch\b|\bsearch (?:provider|tool|backend)\b|\barama (?:aracı|sağlayıcısı|altyapısı)\b)"
    r"[^.\n]{0,160}(?:\b429\b|rate.?limit|hız sınırı)[^.\n]{0,100}(?:döndür\w*|return\w*|hit|failed|error|exceed\w*)"
    r"|\baraştırma tamamlanamadı\b[^\n]{0,300}"
    r"(?:\bwebsearch\b|\bsearch (?:provider|tool|backend)\b|\barama (?:aracı|sağlayıcısı|altyapısı)\b)"
    r"[^\n]{0,160}(?:\b429\b|rate.?limit|hız sınırı)"
    r")"
)
STEP_RE = re.compile(r"(?i)maximum number of steps|adım sınırı|step limit|max.?steps")


def sinir_nedeni(text):
    """Notta açık arama sağlayıcısı hatası ve/veya adım bütçesi izi varsa kısa neden (yoksa None). İkisi ayrı raporlanır: çözümleri farklıdır
    (hız sınırı → sağlayıcı/arama; adım bütçesi → efor ya da konu daraltma)."""
    rate, step = bool(RATE_RE.search(text)), bool(STEP_RE.search(text))
    if rate and step:
        return "arama hız sınırı (429) ve adım bütçesi bitti"
    if rate:
        return "arama hız sınırı (429)"
    if step:
        return "adım bütçesi bitti (OpenCode adım sınırı)"
    return None
BROAD_TOPIC_ENTITIES = 6   # bir konuda bu kadar ya da daha çok varlık (ülke/ürün/şirket) sayılıyorsa uyar: 24 adımlık bütçeye sığmaz
MIN_URLS = 3        # varsayılan kabul eşiği; dar konular planda min_url_required ile düşürebilir
MIN_URLS_REQUIRED_MIN = 2  # kabul eşiğinde en az iki farklı URL ile çapraz kaynak gerekir
WEAK_URLS = 8       # bunun altı kabul edilir ama "zayıf" işaretlenir (çıkış kodu 73; örn. arama 429'a düştü)
BOSLUK_TAVAN = 3    # --bosluk-turu üst sınırı: ek tur başına ölçülen yararlı kazanç ilk 1–3 turda (STORM M=5, open_deep_research 6, ScholarGym T=5 ortalamalarının altında, ucuz hat olduğumuz için)
BOSLUK_HOST_SINIRI = 12  # ek turun istemine "bunları zaten okuduk" notu için en çok bu kadar alan adı yazılır
SECRET_FIELD = r"(?:[a-z0-9]+[_-])?(?:secret[_-]?access[_-]?key|api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|private[_-]?key|token|secret|authorization|bearer|password|passwd|credential)"
SECRET_FIELD_RE = re.compile(rf"^(?:{SECRET_FIELD})$", re.I)
# K1: GENİŞ maske (hata metni, log, calisma.json). Alan adına sol sınır (\b) konur ve yalnız boşlukla ayrılmış
# (":" ya da "=" OLMAYAN) biçimde değerin gerçekten gizli-benzeri olması istenir; böylece "Her token için fiyat" gibi düzyazı yutulmaz.
SECRET_RE = re.compile(
    rf"(?i)(?P<prefix>[\"']?\b{SECRET_FIELD}[\"']?(?P<sep>\s*[:=]\s*|\s+))"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|Bearer\s+[^\s,;}\]]+|[^\s,;}\]]+)"
)
# K1: not gövdesi için DAR maske. Yalnız (i) bilinen anahtar önekleri ve (ii) BİRLEŞİK alan adlı atamalar
# (yalnız ":" ya da "=" ayraçlı) maskelenir. Düzyazıdaki tek başına "token"/"secret"/"credential" alan adı SAYILMAZ;
# boşlukla ayrılmış ("token için") biçim ASLA maskelenmez.
NOT_ASSIGN_FIELD = r"(?:api[_-]?key|access[_-]?token|secret[_-]?access[_-]?key|client[_-]?secret|private[_-]?key|password|passwd)"
NOT_ASSIGN_RE = re.compile(
    rf"(?i)(?P<prefix>[\"']?\b{NOT_ASSIGN_FIELD}[\"']?\s*[:=]\s*)"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)"
)
NOT_TOKEN_RE = re.compile(
    r"(?i)(?:"
    r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_\-]{20,}"
    r"|(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}"
    r"|(?<![A-Za-z0-9])(?:ghp|gho|ghs)_[A-Za-z0-9]{20,}"
    r"|(?<![A-Za-z0-9])github_pat_[A-Za-z0-9_]{20,}"
    r"|(?<![A-Za-z0-9])xox[bap]-[A-Za-z0-9-]{10,}"
    r"|(?<![A-Za-z0-9])AIza[0-9A-Za-z_\-]{20,}"
    r"|(?<![A-Za-z0-9])eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"
    r"|\bBearer\s+[A-Za-z0-9._\-+/=]{20,}"
    r")"
)
# Araç çağrısı döngüsünü sınırlar: sınıra gelince OpenCode araçsız nihai cevap yazmaya zorlar (aksi halde sonsuza dek arayabilir).
STEPS_BY_EFFORT = {"dusuk": 16, "orta": 24, "yuksek": 32}
# "arama/okuma aracı çağrıldı mı" denetiminde sayılan araç adları (küçük harf önekleri); `toolsearch`, `command_execution`, `file_change` SAYILMAZ.
ARAMA_ARAC_ONEKLERI = ("websearch", "oku_", "webfetch", "web_search", "mcp_tool_call")
HAFIF_ADIM = 9      # --hafif kipinde nihai metne daha erken geç; MCP okuyucu ayrıca gerçek çağrı sınırına sahiptir
# Alt süreçlere (OpenCode ve onun MCP sunucuları) yalnız bu değişkenler geçer; kalan ortam (başka servis anahtarları vb.) sızmaz.
ENV_ALLOWLIST = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ", "XDG_CONFIG_HOME",
                 "XDG_DATA_HOME", "XDG_CACHE_HOME", "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy")


# ----------------------------------------------------------------------------- yardımcılar
def api_key():
    """Çalışan arka ucunun anahtarı (yapılandırmadaki değişken adı → ortam → key_files). Yalnız alt sürecin ortamına verilir; asla yazdırılmaz."""
    return ayar.api_key()


def clean_env(extra=None):
    """İzin listesindeki değişkenler + açıkça verilenler."""
    env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
    env.update(extra or {})
    return env


def run_cmd(cmd, env=None, cwd=None, timeout=300, stdin_text=None):
    """(rc, stdout, stderr, zaman_asimi).

    Çıktı borularla değil geçici dosyalarla alınır: OpenCode'un başlattığı MCP alt süreçleri ana süreç bittikten sonra da
    borunun ucunu açık tutabilir ve `communicate()` süre aşımına kadar takılırdı. Ana süreç bitince (ya da süre dolunca)
    tüm süreç grubu sonlandırılır; böylece artık süreç de kalmaz. stdin varsayılan olarak /dev/null'dır (`opencode run` boru stdin'i EOF'a kadar bekleyebilir);
    yalnız `stdin_text` verilirse (cli arka ucunun `prompt_via: stdin` kipi) o metin geçici bir DOSYADAN okunur (boru değil: tıkanma/yarım yazma yok) ve
    metin bitince EOF görülür. Zaman aşımında o ana kadarki çıktı yine döner."""
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out_f, \
         tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as err_f:
        in_f = None
        if stdin_text is not None:
            in_f = tempfile.TemporaryFile("w+", encoding="utf-8")
            in_f.write(stdin_text)
            in_f.seek(0)
        streams = {"stdin": in_f if in_f is not None else subprocess.DEVNULL, "stdout": out_f, "stderr": err_f}
        try:
            proc = subprocess.Popen(cmd, **streams, text=True, env=env, cwd=cwd, start_new_session=True)
        finally:
            if in_f is not None:
                in_f.close()   # alt süreç kendi kopyasını devraldı
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        proc.wait()
        out_f.seek(0)
        err_f.seek(0)
        return (124 if timed_out else proc.returncode), out_f.read(), err_f.read(), timed_out


def load_template():
    text = TEMPLATE.read_text(encoding="utf-8")
    body = text.split("\n---\n", 1)[1] if "\n---\n" in text else text
    return body.strip() + "\n"


OKUMA_MCP = ("- Sayfa okurken `oku` araçlarını kullan (`webfetch` kapalı): `oku_sayfa_oku` (url, soru, token) sayfanın yalnız soruna uyan pasajlarını "
             "döndürür; `oku_sayfada_ara` (url, ifadeler) bir rakamın/alıntının sayfada geçip geçmediğini ve bağlamını verir. Önce arama özetine bak, "
             "umut verici sayfayı `oku_sayfa_oku` ile kısa oku, yalnız gerekirse derinleş.")
OKUMA_GENEL = "- Arama özetlerine (snippet) güvenme; umut verici sayfaların içeriğine bak ve alıntıyı sayfadan al."


HAFIF_ARAMA = ("- Web aramasını kullan. Sorguları kısa (5 kelimeden az) yaz ve her seferinde farklı biçimde ifade et; aynı sorguyu tekrarlama. "
               "Toplam yaklaşık 10–15 arama yap, fazlasını yapma.")
HAFIF_BUTCE = ("- **Bütçen:** yaklaşık 15 araç çağrısı. Bütçe bitince ya da yeni bilgi gelmemeye başlayınca ARAMAYI BIRAK ve elindekiyle çıktıyı yaz; "
               "boş elle dönme, eksikleri **Boşluklar**'a yaz.")


def hafif_butce(n_soru):
    """Hafif kip bütçesi konunun büyüklüğüne ölçeklenir: soru başına 3 araç çağrısı + 2; arama sayısı soru + 2. (Tam kip: 10–15 arama, ~15 çağrı.)"""
    n = max(1, n_soru)
    return n + 2, 3 * n + 2


def hafif_okuma_siniri(n_soru):
    """Soru başına en çok iki okuma, toplam altı; kalan adımlar nihai nota ayrılır."""
    return min(6, max(2, 2 * max(1, n_soru)))


def render(item, template, okuma=OKUMA_GENEL, hafif=False):
    sorular = item.get("sorular") or []
    numbered = "\n".join(f"{i}. {s.strip()}" for i, s in enumerate(sorular, 1)) or "1. (belirtilmedi — konuyu kapsamlı ele al)"
    values = {
        "konu": item["konu"].strip(),
        "soru_sayisi": str(len(sorular) or 1),
        "amac": item.get("amac", "").strip() or "Konuyu kaynaklı ve doğrulanabilir biçimde özetle.",
        "sorular": numbered,
        "kaynaklar": item.get("kaynaklar", "").strip() or "resmî dokümanlar, birincil kaynaklar, güvenilir yayınlar",
        "kisitlar": item.get("kisitlar", "").strip() or "yok",
        "bugun": date.today().isoformat(),
        "okuma": okuma,
    }
    out = template
    if hafif:   # jeton maliyeti: arama sonuçları bağlama girer ve her adımda yeniden gönderilir → az ve dar arama, ölçekli bütçe
        n_ara, n_cagri = hafif_butce(len(sorular))
        out = out.replace(HAFIF_ARAMA, f"- Web aramasını kullan. Sorguları kısa (5 kelimeden az) yaz; aynı sorguyu tekrarlama. **Toplam en çok {n_ara} arama; "
                                       "her aramada en çok 4 sonuç iste (`numResults: 4`)** ve mümkünse aynı mesajda 2 farklı sorguyu birlikte gönder.")
        out = out.replace(HAFIF_BUTCE, f"- **Bütçen:** en çok {n_cagri} araç çağrısı (arama + sayfa okuma). Birincil kaynağın URL'sini bulunca aramayı BIRAK; "
                                       "alıntıyı doğrudan o sayfadan al. Bütçe bitince ya da yeni bilgi gelmemeye başlayınca elindekiyle çıktıyı yaz; "
                                       "eksikleri **Boşluklar**'a yaz.")
        if okuma == OKUMA_MCP:
            out = out.replace("- **Bütçen:**", f"- MCP okuyucu en çok {hafif_okuma_siniri(len(sorular))} çağrı kabul eder; sınır dolunca yeni okuma deneme, dört bölümlü nihai notu yaz.\n- **Bütçen:**", 1)
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", value)
    return out


def broad_topics(plan):
    """Tek konuda çok sayıda varlık (ör. 9 ülke) sayan slug'lar: [(slug, varlık_sayısı)]. 8 Eki 2026: 9 ülkelik konu 24 adıma sığmadı, 3 denemede çöktü."""
    out = []
    for item in plan if isinstance(plan, list) else []:
        parts = [x for x in re.split(r",|;|\bve\b|/", str(item.get("konu", ""))) if x.strip()]
        if len(parts) >= BROAD_TOPIC_ENTITIES:
            out.append((item.get("slug", "?"), len(parts)))
    return out


def validate(plan):
    errors, seen = [], set()
    if not isinstance(plan, list) or not plan:
        return ["plan boş veya liste değil"]
    for i, item in enumerate(plan, 1):
        if not isinstance(item, dict):
            errors.append(f"#{i}: nesne değil")
            continue
        slug = item.get("slug", "")
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            errors.append(f"#{i}: slug geçersiz ({slug!r}); a-z, 0-9, '-' kullan")
        if isinstance(slug, str):
            if slug in seen:
                errors.append(f"#{i}: slug tekrarı ({slug})")
            seen.add(slug)
        if not isinstance(item.get("konu"), str) or not item["konu"].strip():
            errors.append(f"#{i}: 'konu' zorunlu (metin)")
        sorular = item.get("sorular")
        if not isinstance(sorular, list) or not sorular or not all(isinstance(q, str) and q.strip() for q in sorular):
            errors.append(f"#{i}: 'sorular' en az bir metin içeren liste olmalı")
        for key in ("amac", "kaynaklar", "kisitlar"):
            if key in item and not isinstance(item[key], str):
                errors.append(f"#{i}: '{key}' metin olmalı")
        if "single_publisher_host" in item and (not isinstance(item["single_publisher_host"], str)
                or not PUBLISHER_HOST_RE.fullmatch(item["single_publisher_host"])):
            errors.append(f"#{i}: 'single_publisher_host' yalnız küçük harfli DNS alan adı olmalı")
        try:
            kapsama.olgulari_oku(item)
        except kapsama.OlguHatasi as e:
            errors.append(f"#{i}: {e}")
        if "min_url" in item and not (isinstance(item["min_url"], int) and not isinstance(item["min_url"], bool) and MIN_URLS <= item["min_url"] <= 30):
            errors.append(f"#{i}: 'min_url' {MIN_URLS} ile 30 arasında tam sayı olmalı (bu konu için 'zayıf not' eşiği; varsayılan {WEAK_URLS})")
        if "min_url_required" in item and not (isinstance(item["min_url_required"], int) and not isinstance(item["min_url_required"], bool) and MIN_URLS_REQUIRED_MIN <= item["min_url_required"] <= 30):
            errors.append(f"#{i}: 'min_url_required' {MIN_URLS_REQUIRED_MIN} ile 30 arasında tam sayı olmalı (varsayılan kabul eşiği {MIN_URLS})")
    return errors


# Konu bazlı yazılmamış olgu listesi uyarısı. Hata değil: çıkış kodunu değiştirmez, yalnız stderr'e yazılır.
OLGULAR_AYNI_UYARI = "olgular konular arasında aynı; kapsama anlamsız düşük çıkar — her konuya yalnız o konunun olgularını yaz"


def plan_uyarilari(plan):
    """Plan doğrulamasından AYRI uyarılar: birden çok konunun `olgular` listesi birebir aynıysa kapsama ölçümü bozulur.

    Aynı olgu listesini her konuya kopyalamak (konu bazlı yazmamak) her konuda diğer konuların olgularını da arar; kapsama
    yapay olarak düşük/ıskalı çıkar. Dönen metinler main'de stderr'e yazılır; validate'in dönüşü ve çıkış kodu değişmez."""
    if not isinstance(plan, list) or len(plan) < 2:
        return []
    gruplar = {}
    for item in plan:
        if not isinstance(item, dict):
            continue
        try:
            facts = kapsama.olgulari_oku(item)
        except kapsama.OlguHatasi:
            continue
        if not facts:
            continue
        anahtar = tuple((f["ad"], f["ara"]) for f in facts)   # rx nesnesi kimliği değil, okunur eşleşme anahtarı
        gruplar.setdefault(anahtar, []).append(str(item.get("slug", "?")))
    return [f"{OLGULAR_AYNI_UYARI} (konular: {', '.join(slugs)})" for slugs in gruplar.values() if len(slugs) > 1]


# ----------------------------------------------------------------------------- ayrıştırıcılar (çevrimdışı test edilebilir)
def parse_opencode_events(stdout):
    """OpenCode --format json olaylarından nihai cevabı, araç sayımını, hataları ve jetonu çıkarır.

    Nihai cevap = `step_finish.reason == "stop"` ile biten adımın metni (gerçek akışta ölçüldü: ara adımlar "tool-calls" ile biter).
    Araç çağrısıyla biten (ör. adım sınırına/zaman aşımına takılan) bir akışta ara düşünce metni "cevap" sayılmaz; `tamam` False döner."""
    steps, reasons, step, tools, errors, tokens = {}, {}, 0, {}, [], [0, 0]
    profile = {}   # yalnız sayılar ve araç adları: sayfa metni, istem ve araç argümanları saklanmaz

    def metric(n):
        return profile.setdefault(n, {"adim": n, "araclar": {}, "neden": None,
                                      "taze": 0, "onbellek": 0, "cikti": 0, "akil": 0})
    detail = {"taze": 0, "onbellek": 0, "cikti": 0, "akil": 0}   # maliyet dökümü: önbellekten okunan girdi taze girdiden çok ucuzdur, toplama gömülmesin
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        part = ev.get("part") if isinstance(ev.get("part"), dict) else {}
        kind = ev.get("type")
        if kind == "step_start":
            step += 1
            metric(step)
        elif kind == "text" and part.get("text"):
            steps.setdefault(step, []).append(part["text"])
        elif kind == "tool_use":
            name = part.get("tool") or "?"
            tools[name] = tools.get(name, 0) + 1
            per_step = metric(step)["araclar"]
            per_step[name] = per_step.get(name, 0) + 1
        elif kind == "step_finish":
            reasons[step] = part.get("reason")
            t = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
            cache = t.get("cache") if isinstance(t.get("cache"), dict) else {}
            current = metric(step)
            current["neden"] = reasons[step]
            current["taze"] += t.get("input") or 0
            current["onbellek"] += cache.get("read") or 0
            current["cikti"] += t.get("output") or 0
            current["akil"] += t.get("reasoning") or 0
            tokens[0] += (t.get("input") or 0) + (cache.get("read") or 0)
            tokens[1] += (t.get("output") or 0) + (t.get("reasoning") or 0)
            detail["taze"] += t.get("input") or 0
            detail["onbellek"] += cache.get("read") or 0
            detail["cikti"] += t.get("output") or 0
            detail["akil"] += t.get("reasoning") or 0
        elif kind == "error" or isinstance(ev.get("error"), dict):
            errors.append(redact(json.dumps(ev.get("error", ev), ensure_ascii=False))[:200])
    stop_steps = [n for n, r in reasons.items() if r == "stop" and n in steps]
    if stop_steps:
        final, done = "\n".join(steps[max(stop_steps)]).strip(), True
    else:           # "stop" ile biten adım yok → kesilmiş ya da tanınmayan akış: ara düşünce metni nihai cevap SAYILMAZ (kapalı-varsayılan)
        final, done = "", False
    return {"metin": final, "araclar": tools, "hatalar": errors, "jeton": tokens, "tamam": done,
            "son_neden": reasons[max(reasons)] if reasons else None, "ayrinti": detail,
            "adimlar": [profile[n] for n in sorted(profile)]}


def _mask_value(value):
    """Maske değerini biçimi koruyarak üret (JSON/YAML tırnakları, Bearer öneki)."""
    if len(value) >= 2 and value[0] in ("\"", "'") and value[-1] == value[0]:
        return value[0] + "[GİZLİ]" + value[0]   # JSON/YAML tırnaklarını koru
    if value.lower().startswith("bearer "):
        return "Bearer [GİZLİ]"
    return "[GİZLİ]"


def _gizli_benzeri(value):
    """Boşlukla (":" ya da "=" olmadan) ayrılmış bir değerin gerçekten gizli-benzeri olup olmadığı:
    ≥20 karakter, boşluksuz, harf ve rakam karışık. Böylece düzyazı sözcükler ("Her token için fiyat") maskelenmez."""
    v = value.strip("\"'")
    return len(v) >= 20 and not any(c.isspace() for c in v) and any(c.isalpha() for c in v) and any(c.isdigit() for c in v)


def redact(text):
    """Metin/JSON içindeki anahtar değerlerini karartır (hata metni, log, calisma.json için GENİŞ maske).
    Yalnız boşlukla ayrılmış (":" ya da "=" OLMAYAN) değer gizli-benzeri değilse düzyazı kabul edilir ve dokunulmaz."""
    def mask(match):
        sep = match.groupdict().get("sep") or ""
        if ":" not in sep and "=" not in sep and not _gizli_benzeri(match.group("value")):
            return match.group(0)
        return match.group("prefix") + _mask_value(match.group("value"))
    return SECRET_RE.sub(mask, text or "")


def redact_not(text):
    """Not gövdesi için DAR maske (K1): yalnız bilinen anahtar önekleri ve birleşik alan adlı atamalar (":" ya da "=").
    Düzyazı ("Her token için fiyat", "the secret sauce", "token: gizli_olmayan_kısa") ASLA bozulmaz;
    tek başına "token"/"secret"/"credential" alan adı sayılmaz."""
    def assign(match):
        return match.group("prefix") + _mask_value(match.group("value"))

    def token(match):
        return "Bearer [GİZLİ]" if match.group(0).lower().startswith("bearer") else "[GİZLİ]"

    return NOT_TOKEN_RE.sub(token, NOT_ASSIGN_RE.sub(assign, text or ""))


def redact_data(value):
    """Yapılandırılmış çıktıdaki sır alanlarını özyinelemeli karart; diğer metinleri de tara."""
    if isinstance(value, dict):
        return {key: ("[GİZLİ]" if isinstance(key, str) and SECRET_FIELD_RE.fullmatch(key) else redact_data(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def write_note(path, text):
    """Her arka uç için ortak, gizli değerleri karartan not yazma kapısı. Not DÜZYAZIdır: dar maske (redact_not)."""
    Path(path).write_text(redact_not((text or "").rstrip("\n") + "\n"), encoding="utf-8")


def redact_file(path):
    """Var olan metin/JSON çıktısını da maskele; JSON yapısını mümkünse koru."""
    path = Path(path)
    try:
        original = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if path.suffix.lower() == ".json":
        try:
            safe = json.dumps(redact_data(json.loads(original)), ensure_ascii=False, indent=2) + "\n"
        except json.JSONDecodeError:
            safe = redact(original)
    else:
        safe = redact(original)
    if safe != original:
        path.write_text(safe, encoding="utf-8")


def hata_ozeti(err, out="", rc=None, ad="", sinir=200):
    """Başarısız bir alt sürecin okunur özeti. Yalnız son satıra bakmak yanıltıcıydı (JSON hata çıktısında son satır "}" olabiliyor):
    harf/rakam içeren son 3 satır alınır, stderr boşsa stdout'a bakılır; komut adı ve çıkış kodu başa yazılır. Anahtar benzeri değerler maskelenir."""
    def anlamli(metin):
        return [l.strip() for l in (metin or "").splitlines() if sum(c.isalnum() for c in l) >= 3]
    satirlar = anlamli(err)[-3:] or anlamli(out)[-3:]
    govde = " | ".join(satirlar) if satirlar else "çıktı yok (komut sessiz bitti)"
    ozet = redact(f"{ad + ' ' if ad else ''}rc={rc}: {govde}")
    return ozet if len(ozet) <= sinir else "…" + ozet[-(sinir - 1):]


def _plan_dili(text):
    """İlk 1200 karakterde plan/onay dili var mı (O4). '#' ile başlayan BAŞLIK satırları hariç tutulur:
    konusu 'plan modu' olan geçerli notun başlığı redde yol açmasın; ama gövdedeki gerçek onay isteme yakalanır."""
    satirlar = [l for l in text[:1200].splitlines() if not l.lstrip().startswith("#")]
    return PLAN_RE.search("\n".join(satirlar))


def check_contract(text, minimum=MIN_NOTE_BYTES, minimum_urls=MIN_URLS, expected_questions=None):
    """Çalışan çıktısının sözleşmeye uyup uymadığı: (ok, neden). Boş/kısa/başlıksız/kaynaksız/plan metni çıktı başarı sayılmaz."""
    if len(text.encode("utf-8")) < minimum:
        return False, f"çıktı çok kısa (<{minimum} bayt)"
    if _plan_dili(text):   # plan/onay dili notun BAŞINDA olur; konu gereği başlıkta geçen anmalar reddedilmez
        return False, "plan/onay metni döndürdü (araştırma yapılmadı): 'Plan Modu' bahanesiyle onay istedi"
    if not HEADING_RE.search(text):
        return False, f"'{REQUIRED_SECTION}' başlığı yok (çıktı sözleşmesi bozuk)"
    if expected_questions is not None:
        questions = denetle.parse_note_text(text)
        if len(questions) != expected_questions:
            return False, f"{len(questions)} soru bölümü var (planda {expected_questions}); ek/eksik '##' başlığı"
        for q in questions:
            missing = [s for s in denetle.SECTIONS if s not in q["bolumler"]]
            if missing:
                return False, f"'{q['baslik'][:50]}': eksik bölüm → {', '.join(missing)}"
    n_urls = len(set(URL_RE.findall(text)))
    if n_urls < minimum_urls:
        return False, f"yalnız {n_urls} benzersiz URL (<{minimum_urls}): kaynaklı bulgu yok"
    return True, ""


def _kod_blogu_disi_basliklar(lines):
    """'## ' ile başlayan başlık satır indeksleri; ``` / ~~~ kod bloklarının içindekiler sayılmaz."""
    out, fence = [], None
    for i, line in enumerate(lines):
        govde = line.lstrip()
        if fence is not None:
            if govde.startswith(fence):
                fence = None
            continue
        if govde.startswith("```") or govde.startswith("~~~"):
            fence = govde[:3]
            continue
        if line.startswith("## "):
            out.append(i)
    return out


def fazla_bolumleri_kes(text, expected):
    """Plandaki soru sayısından fazla SONDA '##' bölümü varsa keser: (yeni_metin, atilan_sayı).

    Yalnız ilk `expected` bölüm dört `###` bölümle (denetle.SECTIONS) tamsa ve fazlalık tamamen sondaysa kesilir;
    uyarı stdout'a yazılır. Fazlalık ortadaysa (yani ilk `expected` bölümden biri eksikse) ya da kod bloğu içinde
    '##' satırı varsa metin değişmez: eski davranış (check_contract reddi) sürer."""
    if not expected or expected < 1:
        return text, 0
    questions = denetle.parse_note_text(text)
    if len(questions) <= expected:
        return text, 0
    if any(s not in q["bolumler"] for q in questions[:expected] for s in denetle.SECTIONS):
        return text, 0
    lines = text.splitlines()
    basliklar = _kod_blogu_disi_basliklar(lines)
    if len(basliklar) != len(questions):   # kod bloğu içindeki '##' satırı: güvenilir kesim yok
        return text, 0
    atilan = len(questions) - expected
    yeni = "\n".join(lines[:basliklar[expected]]).rstrip("\n") + "\n"
    if len(denetle.parse_note_text(yeni)) != expected:
        return text, 0
    print(f"arastir: ⚠ notta {len(questions)} '##' bölümü vardı (planda {expected}); sondaki {atilan} fazlalık bölüm kesildi", flush=True)
    return yeni, atilan


def url_count(text):
    return len(set(URL_RE.findall(text)))


def parse_responses_json(stdout):
    """"responses-json" biçimli komut çıktısından (output[]: web_search_call / message) cevap metni, arama sayısı ve jeton."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return {"metin": "", "arama": 0, "jeton": [0, 0]}
    texts, searches = [], 0
    for item in data.get("output") or []:
        if item.get("type") == "web_search_call":
            searches += 1
        elif item.get("type") == "message":
            for c in item.get("content") or []:
                if c.get("type") in ("output_text", "text") and c.get("text"):
                    texts.append(c["text"])
    usage = data.get("usage") or {}
    return {"metin": "\n".join(texts).strip(), "arama": searches,
            "jeton": [usage.get("input_tokens", 0), usage.get("output_tokens", 0)]}


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def parse_text_output(stdout):
    """"text" biçimi: komutun standart çıktısının TAMAMI nottur. Terminal renk/başlık kaçış dizileri (ANSI) atılır, uçlar kırpılır.
    Araç/jeton bilgisi düz metinde yoktur: `araclar` boş, `jeton` [0, 0] döner (sözleşme denetimi yine URL/başlık/plan metni kurallarını uygular)."""
    return {"metin": ANSI_RE.sub("", stdout or "").replace("\r\n", "\n").strip(), "arama": 0, "jeton": [0, 0]}


def _sayi(value):
    """JSON sayı alanını güvenle int'e çevirir (bool/metin/None → 0): sürüm farkı ya da eksik alan ayrıştırmayı düşürmesin."""
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _cli_sonuc(metin="", jeton=None, araclar=None, ayrinti=None, maliyet_usd=None, hata=""):
    """cli ayrıştırıcılarının ortak dönüş biçimi (opencode alanlarıyla aynı adlar + isteğe bağlı `maliyet_usd`)."""
    return {"metin": metin, "jeton": jeton if jeton is not None else [0, 0], "araclar": araclar if araclar is not None else {},
            "ayrinti": ayrinti if ayrinti is not None else {"taze": 0, "onbellek": 0, "cikti": 0}, "maliyet_usd": maliyet_usd, "hata": hata}


def parse_claude_stream_json(stdout):
    """"claude-stream-json" biçimi (`claude -p --output-format stream-json --verbose`): satır başına bir JSON olayı.
    Nihai cevap SON `result` satırının `result` alanıdır; jeton o satırın `usage`'ından (girdi = input+cache_creation+cache_read),
    para maliyeti `total_cost_usd`'den gelir. Araç sayısı `assistant` olaylarındaki `tool_use` içeriklerinden sayılır
    (ad küçük harfe çevrilir; `ToolSearch` gibi yerleşik aramalar araç sayısına yazılır ama arama/okuma denetiminde sayılmaz).
    Resume edilen oturumda maliyet kümülatiftir; her çalışan yeni oturum olduğundan yalnız son `result` okunur (toplama yapılmaz).
    Bilinmeyen olay/alanlar sessizce atlanır (gerçek claude koşusuyla doğrulandı)."""
    araclar, sonuc = {}, None
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            olay = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(olay, dict):
            continue
        if olay.get("type") == "assistant":
            message = olay.get("message") if isinstance(olay.get("message"), dict) else {}
            for c in message.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name"):
                    ad = str(c["name"]).lower()
                    araclar[ad] = araclar.get(ad, 0) + 1
        elif olay.get("type") == "result":
            sonuc = olay
    if sonuc is None:
        return _cli_sonuc(hata="akışta nihai `result` satırı yok (kesilmiş ya da tanınmayan biçim)")
    usage = sonuc.get("usage") if isinstance(sonuc.get("usage"), dict) else {}
    girdi, taze_olusturma = _sayi(usage.get("input_tokens")), _sayi(usage.get("cache_creation_input_tokens"))
    onbellek, cikti = _sayi(usage.get("cache_read_input_tokens")), _sayi(usage.get("output_tokens"))
    jeton = [girdi + taze_olusturma + onbellek, cikti]
    ayrinti = {"taze": girdi + taze_olusturma, "onbellek": onbellek, "cikti": cikti}
    ham_maliyet = sonuc.get("total_cost_usd")
    maliyet = float(ham_maliyet) if isinstance(ham_maliyet, (int, float)) and not isinstance(ham_maliyet, bool) else None
    if sonuc.get("is_error"):
        return _cli_sonuc(jeton=jeton, araclar=araclar, ayrinti=ayrinti, maliyet_usd=maliyet,
                          hata=redact(str(sonuc.get("result") or "claude akışı hata bildirdi"))[:200])
    return _cli_sonuc(metin=str(sonuc.get("result") or "").strip(), jeton=jeton, araclar=araclar,
                      ayrinti=ayrinti, maliyet_usd=maliyet)


CODEX_ARAC_TIPLERI = ("command_execution", "mcp_tool_call", "web_search", "file_change")


def parse_codex_jsonl(stdout):
    """"codex-jsonl" biçimi (`codex exec --json`): JSONL olay akışı (thread.started, item.started/updated/completed, turn.completed, ...).
    Nihai cevap SON `item.completed` olayının `agent_message` metnidir; jeton `turn.completed.usage`'dan gelir — codex PARASAL MALİYET VERMEZ
    (`maliyet_usd` None). Araç öğeleri `item.completed` olaylarından `id` ile tekilleştirilerek sayılır. `turn.failed`/`error` → metin boş + hata dolu.
    Bu biçim GERÇEK codex ile TEST EDİLMEDİ (kota kapalı): davranış codex belgesine dayanır. Bilinmeyen olay/alanlar sessizce atlanır."""
    metin, hata, gorulen, araclar = "", "", set(), {}
    usage = {}
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            olay = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(olay, dict):
            continue
        tip = olay.get("type")
        if tip == "item.completed":
            item = olay.get("item") if isinstance(olay.get("item"), dict) else {}
            itip = str(item.get("type") or "").lower()
            if itip == "agent_message" and item.get("text"):
                metin = str(item["text"]).strip()
            elif itip in CODEX_ARAC_TIPLERI:
                anahtar = item.get("id") or f"{itip}:{len(gorulen)}"
                if anahtar not in gorulen:
                    gorulen.add(anahtar)
                    araclar[itip] = araclar.get(itip, 0) + 1
        elif tip == "turn.completed" and isinstance(olay.get("usage"), dict):
            usage = olay["usage"]
        elif tip in ("turn.failed", "error"):
            for kaynak in (olay.get("error"), olay.get("message")):
                if isinstance(kaynak, dict) and kaynak.get("message"):
                    hata = str(kaynak["message"])
                    break
                if isinstance(kaynak, str) and kaynak.strip():
                    hata = kaynak
                    break
            else:
                hata = str(tip)
    girdi, onbellek = _sayi(usage.get("input_tokens")), _sayi(usage.get("cached_input_tokens"))
    cikti = _sayi(usage.get("output_tokens"))
    jeton = [girdi, cikti]
    ayrinti = {"taze": max(0, girdi - onbellek), "onbellek": onbellek, "cikti": cikti}
    if hata:
        return _cli_sonuc(jeton=jeton, araclar=araclar, ayrinti=ayrinti, hata=redact(hata)[:200])
    if not metin:
        return _cli_sonuc(jeton=jeton, araclar=araclar, ayrinti=ayrinti,
                          hata="akışta nihai `agent_message` yok (kesilmiş ya da tanınmayan biçim)")
    return _cli_sonuc(metin=metin, jeton=jeton, araclar=araclar, ayrinti=ayrinti)


_oc_v2 = None


def opencode_argv(model, prompt_text, workdir, effort):
    """`opencode run` argümanları (v1: --dir var; v2: --standalone, --dir/--variant yok)"""
    global _oc_v2
    if _oc_v2 is None:
        try:
            helptext = subprocess.run(["opencode", "run", "--help"], capture_output=True, text=True, timeout=30, env=clean_env(),
                                      stdin=subprocess.DEVNULL).stdout
        except (subprocess.TimeoutExpired, OSError):
            helptext = ""
        _oc_v2 = "--standalone" in helptext
    variant = {"orta": "orta", "yuksek": "yuksek"}.get(effort)
    base = ["opencode", "run"]
    if _oc_v2:
        base += ["--standalone", "--auto", "--format", "json", "--agent", "plan", "--model", f"{model}{'#' + variant if variant else ''}"]
    else:
        base += ["--dir", str(workdir), "--auto", "--format", "json", "--agent", "plan", "--model", model]
        if variant:
            base += ["--variant", variant]
    return base + [prompt_text]


# ----------------------------------------------------------------------------- arka uç çalıştırıcıları
def opencode_config(effort, reader_cache=None, search=True, hafif=False, read_limit=None):
    """Çalışan yapılandırması: en az yetki. `tools` kapalı-varsayılandır (`"*": false`): kullanıcının genel OpenCode MCP'leri
    (kullanıcının kendi eklediği her MCP sunucusu), `read/grep/glob/task/skill` gibi yerleşikler dahil yalnız burada açıkça verilenler çalışır.
    Gerçek OpenCode ile ölçüldü: bu ayarla model yalnız `oku_sayfa_oku, oku_sayfada_ara, websearch` araçlarını görür."""
    cfg = json.loads(json.dumps(OPENCODE_PERMISSIONS))
    steps = STEPS_BY_EFFORT.get(effort, 16)
    cfg["agent"] = {"plan": {"steps": min(steps, HAFIF_ADIM) if hafif else steps}}
    tools = {"*": False}
    if search:
        tools["websearch"] = True
    if reader_cache:
        # Sıkıştırılmış sayfa okuyucu (oku MCP) + tam-sayfa webfetch kapalı: jeton tasarrufu ve tutarlı enjeksiyon uyarısı.
        cfg["permission"]["webfetch"] = "deny"
        cfg["mcp"] = {"oku": {"type": "local", "command": [sys.executable, str(HERE / "mcp_oku.py")],
                              "environment": {"OKU_ONBELLEK": str(reader_cache)}, "enabled": True}}
        if read_limit is not None:
            cfg["mcp"]["oku"]["environment"]["OKU_CAGRI_BUTCE"] = str(read_limit)
        tools["oku_*"] = True
    else:
        tools["webfetch"] = True
    cfg["tools"] = tools
    return cfg


def work_opencode(prompt_text, note, base, model_key, effort, timeout, search, reader=True, hafif=False, read_limit=None):
    key = api_key()
    if ayar.needs_key() and not key:
        return {"rc": 5, "hata": f"anahtar bulunamadı ({ayar.api_key_env()}: ortam ya da key_files; bkz. quoteproof.example.json)"}
    workdir = base / ".oc-calisma"
    workdir.mkdir(exist_ok=True)
    extra = {"OPENCODE_CONFIG_CONTENT": json.dumps(opencode_config(effort, base / "kaynaklar" if reader else None, search, hafif, read_limit))}
    if ayar.needs_key():
        extra[ayar.api_key_env()] = key
    if search:
        extra.update(ayar.load()["runtime_env"])   # çalışma ortamının yerleşik arama aracını açan değişkenler
    env = clean_env(extra)
    cmd = opencode_argv(ayar.model_id(model_key, "opencode"), prompt_text, workdir, effort)
    rc, out, err, timed_out = run_cmd(cmd, env=env, cwd=str(workdir), timeout=timeout + 60)
    parsed = parse_opencode_events(out)
    if timed_out:
        return {"rc": 6, "hata": "OpenCode zaman aşımı", "jeton": parsed["jeton"], "araclar": parsed["araclar"], "ayrinti": parsed["ayrinti"], "adimlar": parsed["adimlar"]}
    if rc != 0 or parsed["hatalar"]:
        why = parsed["hatalar"][0] if parsed["hatalar"] else hata_ozeti(err, out, rc or 3, "opencode")
        return {"rc": rc or 3, "hata": redact(why)[:200], "jeton": parsed["jeton"], "araclar": parsed["araclar"], "ayrinti": parsed["ayrinti"], "adimlar": parsed["adimlar"]}
    if not parsed["tamam"]:
        return {"rc": 7, "hata": f"akış nihai cevap (reason=stop) olmadan bitti (adım sınırı/kesinti; son adım nedeni: {parsed['son_neden'] or 'yok'})", "jeton": parsed["jeton"],
                "araclar": parsed["araclar"], "ayrinti": parsed["ayrinti"], "adimlar": parsed["adimlar"]}
    write_note(note, parsed["metin"])
    return {"rc": 0, "jeton": parsed["jeton"], "araclar": parsed["araclar"], "ayrinti": parsed["ayrinti"], "adimlar": parsed["adimlar"]}


def work_cli(prompt_text, note, model_key, timeout):
    """Yapılandırmadaki komut satırı arka ucu (cli_backend). Komut şablonu ayar.cli_command ile doldurulur."""
    cmd = ayar.cli_command(ayar.model_id(model_key, "cli"), prompt_text, timeout)
    if not cmd:
        return {"rc": 127, "hata": "cli arka ucu yapılandırılmamış (cli_backend; bkz. quoteproof.example.json)"}
    if not shutil.which(cmd[0]):
        return {"rc": 127, "hata": f"komut bulunamadı: {cmd[0]}"}
    via_stdin = ayar.cli_prompt_via() == "stdin"
    rc, out, err, timed_out = run_cmd(cmd, env=clean_env(), timeout=timeout + 60, stdin_text=prompt_text if via_stdin else None)
    if timed_out:
        return {"rc": 6, "hata": "cli zaman aşımı"}
    fmt = ayar.cli_format()
    if fmt in ("claude-stream-json", "codex-jsonl"):   # jeton/araç/maliyet ölçülebilen yeni biçimler (text/responses-json yolu aynen kalır)
        parsed = parse_claude_stream_json(out) if fmt == "claude-stream-json" else parse_codex_jsonl(out)
        if rc != 0 or parsed["hata"] or not parsed["metin"]:
            why = parsed["hata"] or hata_ozeti(err, out, rc or 0, os.path.basename(cmd[0]) + " (boş yanıt)")
            return {"rc": rc or 3, "hata": redact(why)[:200]}
        write_note(note, parsed["metin"])
        return {"rc": 0, "jeton": parsed["jeton"], "araclar": parsed["araclar"],
                "ayrinti": parsed["ayrinti"], "maliyet_usd": parsed["maliyet_usd"]}
    text_mode = fmt == "text"
    parsed = parse_text_output(out) if text_mode else parse_responses_json(out)
    if rc != 0 or not parsed["metin"]:
        return {"rc": rc or 3, "hata": hata_ozeti(err, out, rc or 3, os.path.basename(cmd[0])) if rc else
                hata_ozeti(err, out, 0, os.path.basename(cmd[0]) + " (boş yanıt)")}
    write_note(note, parsed["metin"])
    return {"rc": 0, "jeton": parsed["jeton"], "araclar": {} if text_mode else {"web_search": parsed["arama"]}}


SEQUENCES = {"otomatik": ["opencode", "opencode", "cli"], "opencode": ["opencode", "opencode"], "cli": ["cli", "cli"]}


def available_backends():
    """Bu makinede gerçekten çalışabilecek arka uçlar (0 token): opencode = ikili + (gerekiyorsa) anahtar + tanımlı model; cli = yapılandırılmış komutun ikilisi."""
    have = set()
    try:
        configured = bool(ayar.load()["models"])
        if configured and shutil.which("opencode") and (api_key() or not ayar.needs_key()):
            have.add("opencode")
        cmd = ayar.load()["cli_backend"]
        if configured and cmd and shutil.which(cmd["command"][0]):
            have.add("cli")
    except ayar.ConfigError:
        pass
    return have


def build_sequence(mode, have):
    """İstenen zincirden kullanılamayan arka uçları çıkarır (ör. anahtar yokken otomatik → doğrudan cli)."""
    return [b for b in SEQUENCES[mode] if b in have]


def next_index(sequence, index, failed_rc):
    """Başarısız denemeden sonraki adım: zaman aşımı (rc=6) aynı arka uçta tekrarlanmaz, bir sonraki FARKLI arka uca geçilir."""
    nxt = index + 1
    if failed_rc in (6, 10):
        while nxt < len(sequence) and sequence[nxt] == sequence[index]:
            nxt += 1
    return nxt


def run_worker(item, base, args, start_delay=0.0, sequence=None):
    if start_delay:
        time.sleep(start_delay)  # OpenCode'lar aynı anda açılırsa ortak SQLite kilidi ("database is locked") çıkabiliyor
    slug = item["slug"]
    note = base / "notlar" / f"{slug}.md"
    template = load_template()
    sequence = sequence if sequence is not None else SEQUENCES[args.arka]
    result = {"slug": slug, "ok": False, "deneme": 0, "arka": None, "rc": None, "hata": "", "bayt": 0, "sure_sn": 0, "denemeler": [],
              "jeton": [0, 0], "araclar": {}, "maliyet_usd": None, "ek_bolum_atildi": 0}
    started = time.time()
    budget = args.sure * 2.5 + 120   # çalışan başına toplam duvar saati tavanı: zincir sonsuza dek uzamasın
    index = 0
    while index < len(sequence):
        backend = sequence[index]
        result.update(deneme=result["deneme"] + 1, arka=backend)
        if note.exists():
            note.unlink()
        use_mcp = backend == "opencode" and args.okuyucu == "mcp"
        try:
            hafif = getattr(args, "hafif", False) is True
            prompt_text = render(item, template, OKUMA_MCP if use_mcp else OKUMA_GENEL, hafif)
            if backend == "opencode":
                # Okuyucunun gerçek sınırı istemdeki toplam araç bütçesinden düşüktür;
                # modelin son adımlarda kaynakları derleyip metin üretmesine yer kalır.
                read_limit = hafif_okuma_siniri(len(item["sorular"])) if hafif and use_mcp else None
                r = work_opencode(prompt_text, note, base, args.model, args.efor, args.sure, not args.arama_yok,
                                  use_mcp, hafif, read_limit)
            else:
                r = work_cli(prompt_text, note, args.model, args.sure)
        except Exception as e:   # bir çalışanın beklenmedik çökmesi tüm koşuyu düşürmesin
            r = {"rc": 8, "hata": redact(f"{type(e).__name__}: {e}")[:200]}
        result["rc"], result["hata"] = r["rc"], r.get("hata", "")
        for k in (0, 1):   # jeton/araç sayıları tüm denemeler boyunca birikir (maliyet gerçeği)
            result["jeton"][k] += (r.get("jeton") or [0, 0])[k]
        for name, n in (r.get("araclar") or {}).items():
            result["araclar"][name] = result["araclar"].get(name, 0) + n
        if r.get("maliyet_usd") is not None:   # yalnız maliyet bildiren arka uçlar (claude-stream-json) toplama katılır
            result["maliyet_usd"] = (result["maliyet_usd"] or 0.0) + r["maliyet_usd"]
        text = note.read_text(encoding="utf-8", errors="replace") if note.exists() else ""
        if r["rc"] == 0:   # sondaki fazladan '##' bölümü notu düşürmek yerine kes (çalışanı baştan koşturmayalım)
            kesik, atilan = fazla_bolumleri_kes(text, len(item["sorular"]))
            if atilan:
                write_note(note, kesik)
                text = note.read_text(encoding="utf-8", errors="replace")
                result["ek_bolum_atildi"] = atilan
        size = len(text.encode("utf-8"))
        result["bayt"] = size
        ok_contract, why = check_contract(text, minimum_urls=item.get("min_url_required", MIN_URLS),
                                          expected_questions=len(item["sorular"])) if r["rc"] == 0 else (False, "")
        tools_used = r.get("araclar")
        # opencode'da araç listesi her zaman ölçülür; cli'de yalnız araç sayısı ayrıştırılabilen yeni biçimlerde (text/responses-json eski davranışta kalır).
        arac_olculebilir = backend == "opencode" or (backend == "cli" and ayar.cli_format() in ("claude-stream-json", "codex-jsonl"))
        if ok_contract and arac_olculebilir and isinstance(tools_used, dict) and \
                not any(k.startswith(ARAMA_ARAC_ONEKLERI) for k in tools_used):
            ok_contract, why = False, "hiç arama/okuma aracı çağrılmadı (not modelin ezberinden yazıldı, araştırma sayılmaz)"
        if r["rc"] == 0 and not ok_contract:
            neden = sinir_nedeni(text[:6000])
            if neden:
                why = f"{neden}: {why}"
                rc_fail = 10
            else:
                rc_fail = 9
            r = {**r, "rc": rc_fail, "hata": why}
            result["rc"], result["hata"] = rc_fail, why
            bad = base / "hatali"   # incelemek için sakla; notlar/ dışında olduğundan denetime girmez
            bad.mkdir(exist_ok=True)
            note.replace(bad / f"{slug}.deneme{result['deneme']}.md")
        result["denemeler"].append({"arka": backend, "rc": r["rc"], "hata": r.get("hata", ""), "bayt": size,
                                    "jeton": r.get("jeton") or [0, 0], "araclar": r.get("araclar") or {},
                                    "ayrinti": r.get("ayrinti"), "maliyet_usd": r.get("maliyet_usd"),
                                    "adimlar": r.get("adimlar") or []})   # deneme başına maliyet/teşhis
        if r["rc"] == 0:
            result["ok"] = True
            break
        index = next_index(sequence, index, r["rc"])
        if index < len(sequence):
            if time.time() - started > budget:
                result["denemeler"].append({"arka": "-", "rc": 6, "hata": "çalışan toplam süre tavanı doldu; zincir kesildi", "bayt": 0})
                break
            time.sleep(4)
    if not sequence:
        result.update(rc=69, hata="kullanılabilir arka uç yok (yapılandırma: quoteproof.example.json)")
    result["sure_sn"] = round(time.time() - started)
    return result


def weak_notes(base, results, plan):
    """Başarılı ama kaynak kapsamı zayıf notlar. Eşik: `min_url`, yoksa `min_url_required`, ikisi de yoksa WEAK_URLS."""
    thresholds = {item["slug"]: item.get("min_url", item.get("min_url_required", WEAK_URLS)) for item in plan}
    weak = []
    for slug_ok in [r["slug"] for r in results if r["ok"]]:
        note_path = base / "notlar" / f"{slug_ok}.md"
        if note_path.exists() and url_count(note_path.read_text(encoding="utf-8", errors="replace")) < thresholds.get(slug_ok, WEAK_URLS):
            weak.append(slug_ok)
    return weak


def _ziyaret_hostlari(dirs):
    """Notlardaki URL'lerden ziyaret edilen alan adları (en çok BOSLUK_HOST_SINIRI, sırayla).
    Ek boşluk turunun istemine "şu alan adlarını daha önce okuduk" notu için kullanılır (aynı URL'leri yeniden taramamak)."""
    out = []
    for d in dirs:
        p = Path(d)
        if not p.is_dir():
            continue
        for f in sorted(p.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for host in _HOST_RE.findall(text):
                host = host.split(":", 1)[0].lower()
                if host and host not in out:
                    out.append(host)
                    if len(out) >= BOSLUK_HOST_SINIRI:
                        return out
    return out


def guncelleme_kisiti(mevcut, adlar, hostlar):
    """Ek turun `kisitlar` metnine GÜNCELLEME KİPİ cümlesini ekler: yalnız eksik olguları ara + zaten okunan alan adları."""
    ek = ("GÜNCELLEME KİPİ: yalnız şu eksik olguları ara: " + "; ".join(adlar)
          + "; şu alan adlarını daha önce okuduk: " + (", ".join(hostlar) if hostlar else "(yok)"))
    mevcut = (mevcut or "").strip()
    return f"{mevcut} {ek}".strip() if mevcut else ek


def bosluk_karari(onceki_eksik_adlari, simdiki_eksik_adlari, tur, tavan):
    """Boşluk turu durma kararı (saf): ("devam"|"dur", neden).

    Üç eksen (araştırma dayanağı): kalite eşiği (eksik kaldı mı), durgunluk (bu turda yeni olgu kapsanmadı mı), tur/bütçe tavanı.
    Durgunluk: birleşik kapsama monoton olduğundan `simdiki`, `onceki`nin alt kümesidir; eşitse bu tur yeni olgu kapsamadı."""
    if not simdiki_eksik_adlari:
        return "dur", "eksik kalmadı"
    if set(simdiki_eksik_adlari) >= set(onceki_eksik_adlari):
        return "dur", "bu turda hiç yeni olgu kapsanmadı (durgunluk)"
    if tur >= tavan:
        return "dur", "tavana ulaşıldı"
    return "devam", ""


def _eksik_adlari(res):
    return [e["ad"] for r in res.values() for e in r["eksik"]]


def _cocuk_komut(plan_yolu, dizin, args):
    """Boşluk turu çocuk koşusu: aynı betik, ana koşunun bayrakları taşınır, --hafif ve --bosluk-turu 0 ile (özyineleme olmaz)."""
    cmd = [sys.executable, str(Path(__file__).resolve()), str(plan_yolu), "-d", str(dizin),
           "--hafif", "--bosluk-turu", "0", "--arka", args.arka, "-e", args.efor,
           "-j", str(args.jobs), "-t", str(args.sure), "--okuyucu", args.okuyucu]
    if getattr(args, "model", None):
        cmd += ["--model", args.model]
    if getattr(args, "arama_yok", False):
        cmd.append("--arama-yok")
    return cmd


def bosluk_ozet_render(kayitlar, nihai_res, kaynaklar):
    """`bosluk-ozet.md`: tur tablosu (tur, eksik önce→sonra, yeni kapsanan, çocuk çıkış kodu, süre) + nihai birleşik kapsama + birleştirme komutu."""
    L = ["# Boşluk turları (otomatik)", "",
         "Eksik kalan olgular için hedefli ek çalıştırmalar; her tur birleşik kapsamaya göre değerlendirilir.", "",
         "| Tur | Eksik önce → sonra | Yeni kapsanan olgular | Çocuk kodu | Süre |", "|---:|---:|---|---:|---:|"]
    for k in kayitlar:
        yeni = ", ".join(k.get("yeni") or []) or "—"
        rc = k.get("rc")
        L.append(f"| {k['tur']} | {len(k['onceki'])} → {len(k['simdiki'])} | {yeni} | "
                 f"{rc if rc is not None else '—'} | {k.get('sure', '—')} sn |")
        if k.get("neden"):
            L.append(f"\nDurdurma nedeni: {k['neden']} (tur {k['tur']}).\n")
    L += ["", "## Nihai birleşik kapsama", "", kapsama.render(nihai_res).rstrip(), ""]
    if len(kaynaklar) >= 2:
        L += ["", "Birleştirme: `uzlas.py " + " ".join(kaynaklar) + " --yaz birlesik/`"]
    return "\n".join(L) + "\n"


def _birlestir(base, ana_notlar, cocuk_dirs):
    """Mevcut `uzlas.py`'ı otomatik çağırıp birleşik notları yazar; başarısızsa uyarır, ana akışı düşürmez."""
    dirs = [d for d in cocuk_dirs if Path(d).is_dir()]
    if not dirs:
        return
    cmd = [sys.executable, str(HERE / "uzlas.py"), str(ana_notlar)] + [str(d) for d in dirs]
    cmd += ["--cikti", str(base / "bosluk-uzlasi.md"), "--yaz", str(base / "birlesik")]
    try:
        rc = subprocess.run(cmd, check=False).returncode
    except OSError as e:
        print(f"arastir: UYARI birleştirme (uzlas.py) çalışmadı ({type(e).__name__}: {e}); birleşik/ elle üretilmeli", file=sys.stderr)
        return
    if rc != 0:
        print(f"arastir: UYARI uzlas.py çıkış kodu {rc}; birleşik not üretilemedi (elle: uzlas.py ... --yaz birlesik/)", file=sys.stderr)
    else:
        print(f"arastir: birleşik not → {base / 'birlesik'}", flush=True)


def bosluk_turlari(plan, base, args, ilk_res, ana_notlar):
    """N>0 ve eksik olgu varken otomatik boşluk turları (0 jeton karar + çocuk koşular). Döner: (nihai_res, hala_esik_altinda).

    Maliyet güvenliği: toplam çocuk turu args.bosluk_turu'nu geçemez; her çocuk kendi --sure bütçesiyle sınırlıdır."""
    n = args.bosluk_turu
    if n <= 0:   # kapalı: hiçbir çocuk koşu açılmaz, mevcut akış aynen
        return ilk_res, any(r["kapsanan"] / max(1, r["toplam"]) < kapsama.VARSAYILAN_ESIK for r in ilk_res.values())
    guncel, onceki = ilk_res, _eksik_adlari(ilk_res)
    kayitlar, cocuk_dirs = [], []
    for k in range(1, n + 1):
        ep = kapsama.eksik_plan(guncel)
        if not ep:
            break
        hostlar = _ziyaret_hostlari([ana_notlar] + cocuk_dirs)
        for item in ep:
            item["kisitlar"] = guncelleme_kisiti(item.get("kisitlar", ""), [o["ad"] for o in item.get("olgular", [])], hostlar)
        ep_yolu = base / f"bosluk-{k}-PLAN.json"
        ep_yolu.write_text(json.dumps(redact_data(ep), ensure_ascii=False, indent=2), encoding="utf-8")
        cocuk_dir = base / f"bosluk-{k}"
        print(f"arastir: boşluk turu {k}/{n}: {len(ep)} konu, {len(onceki)} eksik olgu → {ep_yolu.name}", flush=True)
        t0 = time.time()
        try:
            rc = subprocess.run(_cocuk_komut(ep_yolu, cocuk_dir, args), check=False).returncode
        except OSError as e:
            print(f"arastir: UYARI boşluk turu {k} başlatılamadı ({type(e).__name__}: {e}); turlar durduruldu", file=sys.stderr)
            kayitlar.append({"tur": k, "onceki": onceki, "simdiki": onceki, "yeni": [], "rc": None,
                             "sure": round(time.time() - t0), "neden": "çocuk koşu başlatılamadı"})
            break
        sure = round(time.time() - t0)
        if rc not in (0, 73):
            print(f"arastir: UYARI boşluk turu {k} başarısız (çıkış kodu {rc}); turlar durduruldu, eksikler elle kapatılmalı", file=sys.stderr)
            kayitlar.append({"tur": k, "onceki": onceki, "simdiki": onceki, "yeni": [], "rc": rc, "sure": sure,
                             "neden": f"çocuk çıkış kodu {rc}"})
            break
        cocuk_dirs.append(cocuk_dir / "notlar-temiz")
        dirs = [str(ana_notlar)] + [str(d) for d in cocuk_dirs]
        labels = ["bu çalıştırma"] + [f"bosluk-{i}" for i in range(1, len(cocuk_dirs) + 1)]
        guncel = kapsama.run(plan, dirs, labels=labels)
        simdiki = _eksik_adlari(guncel)
        yeni = [a for a in onceki if a not in simdiki]
        karar, neden = bosluk_karari(onceki, simdiki, k, n)
        kayitlar.append({"tur": k, "onceki": onceki, "simdiki": simdiki, "yeni": yeni, "rc": rc, "sure": sure,
                         "karar": karar, "neden": neden})
        onceki = simdiki
        if karar == "dur":
            break
    kaynaklar = [str(ana_notlar)] + [str(d) for d in cocuk_dirs]
    (base / "bosluk-ozet.md").write_text(redact(bosluk_ozet_render(kayitlar, guncel, kaynaklar)), encoding="utf-8")
    _birlestir(base, ana_notlar, cocuk_dirs)
    hala_dusuk = any(r["kapsanan"] / max(1, r["toplam"]) < kapsama.VARSAYILAN_ESIK for r in guncel.values())
    return guncel, hala_dusuk


# ----------------------------------------------------------------------------- ana akış
def temizle_turetilmis(base):
    """Önceki koşudan kalan TÜRETİLMİŞ çıktıları sil (D1): bu koşunun sonucuymuş gibi görünmesinler.
    `notlar/` (--devam istemli notları yeniden kullanır) ve `kaynaklar/` (okuma önbelleği) KORUNUR."""
    for stale in ("destek.md", "kapsama.md", "eksik-PLAN.json", "bagimsizlik.md", "bosluk-ozet.md"):
        (base / stale).unlink(missing_ok=True)
    for dizin in ("notlar-temiz", "birlesik"):
        shutil.rmtree(base / dizin, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", help="PLAN.json yolu")
    ap.add_argument("-d", "--dizin", help="araştırma dizini (varsayılan: plan dosyasının dizini)")
    ap.add_argument("--arka", default="otomatik", choices=["otomatik", "opencode", "cli"])
    ap.add_argument("--model", default=None, help="yapılandırmadaki model adı (varsayılan: default_model)")
    ap.add_argument("-e", "--efor", default="dusuk", choices=["dusuk", "orta", "yuksek"])
    ap.add_argument("-j", "--is", dest="jobs", type=int, default=3, help=f"paralel çalışan (en çok {MAX_PARALLEL})")
    ap.add_argument("-t", "--sure", type=int, default=420, help="çalışan başına saniye tavanı")
    ap.add_argument("--kuru", action="store_true", help="yalnız istemleri üret, çalışan koşturma")
    ap.add_argument("--hafif", action="store_true", help=f"jeton tasarrufu: konuya ölçekli az arama/çağrı bütçesi, aramada en çok 4 sonuç, adım tavanı {HAFIF_ADIM} (alıntı sözleşmesi ve doğrulama aynen)")
    ap.add_argument("--link-yok", action="store_true", help="denetimde bağlantı kontrolünü atla")
    ap.add_argument("--okuyucu", default="mcp", choices=["mcp", "yerlesik"],
                    help="mcp: OpenCode çalışanı sayfayı sıkıştırılmış okur (oku MCP, webfetch kapalı) · yerlesik: OpenCode webfetch (tam sayfa)")
    ap.add_argument("--dogrula-yok", action="store_true", help="otomatik iddia–kaynak doğrulamasını (dogrula.py) atla")
    ap.add_argument("--arama-yok", action="store_true", help="çalışma ortamının yerleşik `websearch` aracını açma (yalnız webfetch/MCP kalır)")
    ap.add_argument("--devam", action="store_true",
                    help="kesilen koşuyu sürdür: aynı istemle (özet) tamamlanmış ve sözleşmeye uyan notlar yeniden üretilmez")
    ap.add_argument("--bosluk-turu", type=int, default=0, choices=list(range(BOSLUK_TAVAN + 1)),
                    help=f"eksik olgular için otomatik hedefli ek çalıştırma turu (0–{BOSLUK_TAVAN}; varsayılan 0 = kapalı, geriye uyumlu). "
                         "Her tur birleşik kapsamaya göre değerlendirilir; durgunlukta ya da tavanda durur")
    args = ap.parse_args()

    plan_path = Path(args.plan)
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"arastir: plan okunamadı: {e}", file=sys.stderr)
        return 64
    for slug_b, n_b in broad_topics(plan):
        print(f"arastir: ⚠ geniş konu '{slug_b}' ({n_b} varlık): bütçeye sığmaz, çalışan yarım kalır. En çok 3-4 varlık/konu olacak şekilde böl (MECE).", flush=True)
    errors = validate(plan)
    if errors:
        print("arastir: plan hatalı:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 64
    for uyari in plan_uyarilari(plan):   # hata değil: yalnız uyarı, çıkış kodu değişmez
        print(f"arastir: ⚠ {uyari}", file=sys.stderr)

    base = (Path(args.dizin) if args.dizin else plan_path.parent).resolve()  # mutlak yol: alt süreçlerin cwd/--dir çözümü PWD'ye bağlı kalmasın
    (base / "istemler").mkdir(parents=True, exist_ok=True)
    (base / "notlar").mkdir(parents=True, exist_ok=True)
    template = load_template()
    primary_mcp = args.arka in ("otomatik", "opencode") and args.okuyucu == "mcp"
    for item in plan:
        prompt = render(item, template, OKUMA_MCP if primary_mcp else OKUMA_GENEL, getattr(args, "hafif", False) is True)
        (base / "istemler" / f"{item['slug']}.md").write_text(redact(prompt), encoding="utf-8")
    print(f"arastir: {len(plan)} istem yazıldı → {base}/istemler")
    if args.kuru:
        return 0

    # Koşu başında önceki türetilmiş çıktıları sil (D1): erken dönüşlerde (rc=69/70/78) bile eski notlar-temiz/ kalmasın.
    temizle_turetilmis(base)

    # Ön kontroller (0 token)
    try:
        args.model = args.model or ayar.default_model()
        if not args.model:
            raise ayar.ConfigError("hiç model tanımlı değil")
        if args.model not in ayar.load()["models"]:
            raise ayar.ConfigError(f"model '{args.model}' yapılandırmada yok (tanımlılar: {', '.join(ayar.model_names())})")
    except ayar.ConfigError as e:
        print(f"arastir: yapılandırma sorunu: {e}\n         quoteproof.example.json dosyasını ~/.config/quoteproof/config.json olarak kopyalayıp doldurun.", file=sys.stderr)
        return 78
    have = available_backends()
    sequence = build_sequence(args.arka, have)
    if not sequence:
        print(f"arastir: '{args.arka}' için kullanılabilir arka uç yok. {ayar.describe()}", file=sys.stderr)
        return 69
    skipped = [b for b in dict.fromkeys(SEQUENCES[args.arka]) if b not in have]
    if skipped:
        print(f"arastir: kullanılamayan arka uç atlandı: {', '.join(skipped)} → zincir: {' → '.join(sequence)}", flush=True)

    # Önceki koşudan kalan çıktılar bu koşunun sonucuymuş gibi görünmesin (--devam: yalnız aynı istemli, sözleşmeye uyan notlar korunur)
    previous = {}
    if args.devam:
        try:
            previous = {r["slug"]: r for r in json.loads((base / "calisma.json").read_text(encoding="utf-8")) if isinstance(r, dict) and "slug" in r}
        except (OSError, json.JSONDecodeError, TypeError):
            previous = {}
    for stale in ("denetim.md", "dogrulama.md", "dogrulama.json"):
        (base / stale).unlink(missing_ok=True)
    if not args.devam:
        (base / "calisma.json").unlink(missing_ok=True)   # --devam: önceki kontrol noktası, bu koşu ilk sonucunu yazana dek KORUNUR
    prompt_hash = {item["slug"]: hashlib.sha256(render(item, template, OKUMA_MCP if primary_mcp else OKUMA_GENEL, getattr(args, "hafif", False) is True).encode("utf-8")).hexdigest()[:16]
                   for item in plan}
    reused, todo = [], []
    for item in plan:
        slug, note = item["slug"], base / "notlar" / f"{item['slug']}.md"
        prev = previous.get(slug)
        reusable = bool(prev and prev.get("ok") and prev.get("hash") == prompt_hash[slug] and note.exists())
        if reusable:
            raw_note = note.read_text(encoding="utf-8", errors="replace")
            safe_note = redact_not(raw_note)
            safe_note, atilan = fazla_bolumleri_kes(safe_note, len(item["sorular"]))   # sondaki fazlalık yeniden koşuya yol açmasın
            if atilan:
                prev = {**prev, "ek_bolum_atildi": atilan}
            if safe_note != raw_note:
                note.write_text(safe_note, encoding="utf-8")
            reusable = check_contract(safe_note, minimum_urls=item.get("min_url_required", MIN_URLS),
                                      expected_questions=len(item["sorular"]))[0]
        if reusable:
            reused.append({**prev, "devam": True})
        else:
            note.unlink(missing_ok=True)
            todo.append(item)
    if reused:
        print(f"arastir: --devam: {len(reused)} konu önceki koşudan yeniden kullanıldı ({', '.join(r['slug'] for r in reused)})", flush=True)

    jobs = max(1, min(args.jobs, MAX_PARALLEL, len(todo) or 1))
    print(f"arastir: {len(todo)} çalışan, paralel {jobs}, arka uç {' → '.join(sequence)}, model {args.model}, efor {args.efor}, tavan {args.sure}s", flush=True)
    results = list(reused)

    def checkpoint():
        """Her konu bitince atomik kontrol noktası: kesilen koşu --devam ile tamamlanan konuları yeniden üretmeden sürer."""
        done = {r["slug"]: r for r in results}
        merged = [done.pop(item["slug"]) for item in plan if item["slug"] in done]
        tmp = base / "calisma.json.tmp"
        tmp.write_text(json.dumps(redact_data(merged), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, base / "calisma.json")

    if reused:
        checkpoint()
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(run_worker, item, base, args, n * 1.5, sequence): item for n, item in enumerate(todo)}
        for fut in as_completed(futures):   # biten çalışan hemen yazdırılır; sıradaki yavaş çalışan çıktıyı bekletmez
            item = futures[fut]
            try:
                r = fut.result()
            except Exception as e:
                r = {"slug": item["slug"], "ok": False, "deneme": 0, "arka": None, "rc": 8, "hata": redact(f"{type(e).__name__}: {e}")[:200],
                     "bayt": 0, "sure_sn": 0, "denemeler": []}
            r["hash"] = prompt_hash[item["slug"]]
            results.append(r)
            checkpoint()
            durum = "ok  " if r["ok"] else "HATA"
            extra = "" if r["ok"] else f" rc={r['rc']} {r['hata']}"
            tools = ",".join(f"{k}×{v}" for k, v in (r.get("araclar") or {}).items())
            jt = r.get("jeton") or [0, 0]
            print(f"  {durum} {r['slug']:<24} {r['sure_sn']:>4}s {r['bayt'] / 1024:5.1f}KB arka={r['arka']} deneme={r['deneme']} "
                  f"jeton={jt[0]}/{jt[1]} {tools}{extra}", flush=True)
            for d in r["denemeler"]:
                if d["rc"] != 0:
                    print(f"       ↳ başarısız deneme: {d['arka']} rc={d['rc']} {d['hata']}", flush=True)
    order = {item["slug"]: n for n, item in enumerate(plan)}
    results.sort(key=lambda r: order.get(r["slug"], 0))
    (base / "calisma.json").write_text(json.dumps(redact_data(results), ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(base / ".oc-calisma", ignore_errors=True)

    failed = [r["slug"] for r in results if not r["ok"]]
    if len(failed) == len(results):
        print("arastir: HİÇ çalışan başarılı olmadı. Arka uçları yoklayın: `python3 scripts/ayar.py` (yapılandırma durumu), `opencode models`.", file=sys.stderr)
        return 70
    if failed:
        print(f"arastir: başarısız konular (raporda 'boşluk' olarak belirt): {', '.join(failed)}")

    good = [f"{r['slug']}.md" for r in results if r["ok"]]   # yalnız bu koşunun başarılı notları denetlenir/doğrulanır
    weak = weak_notes(base, results, plan)
    if weak:
        print(f"arastir: ⚠ ZAYIF not (eşik altı benzersiz kaynak; varsayılan <{WEAK_URLS}, konuda `min_url` veya `min_url_required` ile değişir): {', '.join(weak)}. Arama hız sınırına (429) takılmış olabilir: "
              f"notlar/<slug>.md'yi silip `-j 2` ile `--devam` koştur ya da konuyu bölüp yeniden çalıştır.", flush=True)
    code = 0
    cmd = [sys.executable, str(HERE / "denetle.py"), str(base / "notlar")]
    cmd += ["--plan", str(plan_path), "--cikti", str(base / "denetim.md"), "--dosyalar", *good]
    if args.link_yok:
        cmd.append("--link-yok")
    print("\n" + "=" * 60)
    rc = subprocess.run(cmd, check=False).returncode
    redact_file(base / "denetim.md")
    if rc != 0:
        print(f"arastir: UYARI denetle.py beklenmedik çıkış kodu {rc}; denetim güvenilmez", file=sys.stderr)
        code = max(code, 71)
    if not args.dogrula_yok and not args.link_yok:
        print("\n" + "=" * 60)
        vcmd = [sys.executable, str(HERE / "dogrula.py"), str(base / "notlar")]
        vcmd += ["--plan", str(plan_path), "--cikti", str(base / "dogrulama.md"), "--onbellek", str(base / "kaynaklar"),
                 "--temiz-yaz", str(base / "notlar-temiz"), "--dosyalar", *good]
        rc = subprocess.run(vcmd, check=False).returncode
        redact_file(base / "dogrulama.md")
        redact_file(base / "dogrulama.json")
        if rc != 0:
            print(f"arastir: UYARI dogrula.py çıkış kodu {rc}; otomatik doğrulama YAPILMADI, iddiaları elle doğrulayın", file=sys.stderr)
            code = max(code, 72)
    if not args.dogrula_yok and not args.link_yok:   # yayın kopyası uzlaşı sayılmaz: içerikçe aynı sayfalar tek kaynak (0 jeton; sayfalar dogrula.py önbelleğinden)
        nd = base / "notlar-temiz" if (base / "notlar-temiz").is_dir() else base / "notlar"
        try:
            bres = bagimsizlik.run(nd, str(base / "kaynaklar"), files=good)
            (base / "bagimsizlik.md").write_text(redact(bagimsizlik.render(bres)), encoding="utf-8")
            bs = bagimsizlik.summarize(bres)
            print("\n" + "=" * 60)
            print(f"arastir: kaynak bağımsızlığı: {bs['okunabilir_alan_adi']} okunabilir alan adı → {bs['bagimsiz']} bağımsız kaynak "
                  f"({bs['kopya_grubu']} kopya grubu; {bs['okunamayan']} sayfa okunamadı) → {base / 'bagimsizlik.md'}")
            if bs["kopya_grubu"]:
                print(f"arastir: ⚠ {bs['kopya_grubu']} kopya grubu: aynı yazının farklı alan adlarında yayımlandığı sayfalar "
                      f"tek kaynak sayıldı; bağımsız teyit için başka yayımlayıcı ara (bkz. bagimsizlik.md)", flush=True)
        except Exception as e:   # yardımcı denetim: hata ana akışı düşürmez
            print(f"arastir: UYARI bagimsizlik.py çalışmadı ({type(e).__name__}: {e}); kaynak bağımsızlığı denetlenmedi", file=sys.stderr)
    if not args.dogrula_yok and not args.link_yok:   # Özet/Çıkarımlar cümlelerindeki somut öğeler alıntı/sayfalarla destekli mi (0 jeton; sayfalar dogrula.py'nin önbelleğinden gelir)
        nd = base / "notlar-temiz" if (base / "notlar-temiz").is_dir() else base / "notlar"
        try:
            dres = destek.run(nd, cache_dir=str(base / "kaynaklar"), files=good)
            (base / "destek.md").write_text(redact(destek.render(dres)), encoding="utf-8")
            if (base / "notlar-temiz").is_dir():   # yalnız temizlenmiş kopyaları işaretle; orijinal notlar/'a dokunma
                n_isaret = destek.isaretle(base / "notlar-temiz", dres)
                if n_isaret:
                    print(f"arastir: ⚠ {n_isaret} Özet/Çıkarımlar cümlesi notlar-temiz/'de 'kaynakta bulunamadı' diye işaretlendi", flush=True)
            dc = destek.summarize(dres)
            strong = destek.strong_count(dres)
            print("\n" + "=" * 60)
            print(f"arastir: destek kontrolü: {dc['isaretli']}/{dc['cumle']} Özet/Çıkarımlar cümlesinde alıntıda olmayan somut öğe ({dc['uyarı']} uyarı · {dc['bilgi']} bilgi) → {base / 'destek.md'}")
            if strong:
                print(f"arastir: ⚠ {strong} somut öğe notun atıf yaptığı HİÇBİR sayfada bulunamadı (uydurma, çeviri ya da hesaplanmış değer olabilir): destek.md'deki `hiçbir-yerde` satırlarını rapora almadan kaynakta elle doğrula", flush=True)
        except Exception as e:   # yardımcı denetim: hata ana akışı düşürmez
            print(f"arastir: UYARI destek.py çalışmadı ({type(e).__name__}: {e}); Özet/Çıkarımlar cümleleri otomatik denetlenmedi", file=sys.stderr)
    kapsama_dusuk = False
    if any(it.get("olgular") for it in plan):   # beklenen olgulara göre kapsama (0 jeton): eksikler için ek plan yazılır
        nd = base / "notlar-temiz" if (base / "notlar-temiz").is_dir() else base / "notlar"
        res = kapsama.run(plan, [nd], labels=["bu çalıştırma"], files=good)
        (base / "kapsama.md").write_text(redact(kapsama.render(res)), encoding="utf-8")
        print("\n" + "=" * 60)
        for slug, r in res.items():
            if r["kapsanan"] / max(1, r["toplam"]) < kapsama.VARSAYILAN_ESIK:
                kapsama_dusuk = True
            print(f"arastir: kapsama {slug}: {r['kapsanan']}/{r['toplam']} olgu" + (f" · eksik: {'; '.join(e['ad'] for e in r['eksik'])[:200]}" if r["eksik"] else ""))
        ep = kapsama.eksik_plan(res)
        if ep:
            (base / "eksik-PLAN.json").write_text(json.dumps(redact_data(ep), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"arastir: eksik olgular için ek plan: {base / 'eksik-PLAN.json'} → `arastir.py eksik-PLAN.json -d BASKA_DIZIN --hafif`, sonra "
                  f"`uzlas.py <bu>/notlar-temiz BASKA_DIZIN/notlar-temiz --yaz birlesik/` ile birleştir", flush=True)
            if args.bosluk_turu > 0:   # otomatik boşluk turları (durgunlukta/tavanda durur; birleşik kapsama eşiği geçerse 73 nedeni düşer)
                res, kapsama_dusuk = bosluk_turlari(plan, base, args, res, nd)
    if kapsama_dusuk:
        code = max(code, 73)
    if failed or weak:
        code = max(code, 73)   # kısmi başarı: bazı konular eksik ya da zayıf
    return code


if __name__ == "__main__":
    sys.exit(main())
