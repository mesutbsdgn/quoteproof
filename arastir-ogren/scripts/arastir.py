#!/usr/bin/env python3
"""arastir-ogren çalıştırıcısı: PLAN.json → paralel araştırma çalışanları → notlar/ → denetim.

Kullanım:
  arastir.py PLAN.json -d ARASTIRMA_DIZINI [--arka otomatik|opencode|cli] [--model AD]
             [-e dusuk|orta|yuksek] [-j 3] [-t 420] [--kuru] [--link-yok] [--arama-yok] [--devam]

Arka uçlar (model/sağlayıcı/anahtar ayrıntıları koda gömülü değildir: quoteproof.json — bkz. ayar.py, quoteproof.example.json):
  opencode  OpenCode ajan çalışma ortamı (plan modu; araç kilidi kapalı-varsayılan: yalnız yerleşik `websearch` + `oku_*` MCP ya da `webfetch`).
  cli       Yapılandırmada tanımlı komut satırı arka ucu (cli_backend; çıktı "responses-json" ya da düz "text"; istem argümanla ya da stdin'den).
  otomatik  (varsayılan) önce opencode, başarısızsa cli. Kullanılamayan arka uçlar zincirden çıkarılır.

PLAN.json: [{"slug","konu","amac","sorular":[...],"kaynaklar","kisitlar"}, ...]
Çıktı dizini: istemler/<slug>.md · notlar/<slug>.md · calisma.json · denetim.md
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
import kapsama  # noqa: E402

TEMPLATE = HERE.parent / "references" / "arastirmaci-istemi.md"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
MIN_NOTE_BYTES = 300
MAX_PARALLEL = 4
# Araştırma çalışanı yalnız arama/okuma yapar: kabuk ve dosya yazma kapalı.
OPENCODE_PERMISSIONS = {"permission": {"bash": "deny", "edit": "deny", "write": "deny", "external_directory": "deny", "doom_loop": "deny"}}
REQUIRED_SECTION = "Alıntılı bulgular"   # çalışan çıktı sözleşmesi (references/arastirmaci-istemi.md)
# 8 Eki 2026 (İHA araştırma deneyi): bir çalışan araştırma yapmadan "Plan Modu etkin, onayınıza sunuyorum" planı döndürdü; planda
# "Alıntılı bulgular" ifadesi geçtiği için düz alt dize denetimi onu BAŞARILI saydı. Artık: gerçek markdown başlığı + en az MIN_URLS
# benzersiz URL + plan/onay dili yok + (OpenCode'da) en az bir arama/okuma aracı çağrısı.
HEADING_RE = re.compile(r"(?m)^#{2,4}[ \t]*Alıntılı bulgular\b")
URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
PLAN_RE = re.compile(r"(?i)plan modu|onay(?:ına|ınıza|ınızı|ınız)\s+(?:sun|bekle)|yaklaşımı onay|onaylarsanız|onay vermenizi|awaiting (?:your )?approval")
# 8 Eki 2026: arama sağlayıcısı oturum boyunca 429 verdi; çalışan "Araştırma tamamlanamadı, arama altyapısı çöktü" yazıp 3 denemede aynı duvara çarptı.
# Böyle notta (hız sınırı ya da adım bütçesi bitti) aynı arka ucu yeniden denemek boşuna: sıradaki FARKLI arka uca geçilir (rc=10).
RATE_RE = re.compile(r"(?i)\b429\b|rate.?limit|hız sınırı|arama altyapısı çöktü|arama sağlayıcısı çöktü")
STEP_RE = re.compile(r"(?i)maximum number of steps|adım sınırı|step limit|max.?steps")


def sinir_nedeni(text):
    """Notta hız sınırı ve/veya adım bütçesi izi varsa kısa neden (yoksa None). İkisi ayrı raporlanır: çözümleri farklıdır
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
MIN_URLS = 3        # bunun altı: kaynaklı bulgu yok → çıktı sözleşmesi bozuk (rc=9, zincir sürer)
WEAK_URLS = 8       # bunun altı kabul edilir ama "zayıf" işaretlenir (çıkış kodu 73; örn. arama 429'a düştü)
SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|secret|authorization|bearer)([\"'\s:=]+)[A-Za-z0-9._\-]{8,}")
# Araç çağrısı döngüsünü sınırlar: sınıra gelince OpenCode araçsız nihai cevap yazmaya zorlar (aksi halde sonsuza dek arayabilir).
STEPS_BY_EFFORT = {"dusuk": 16, "orta": 24, "yuksek": 32}
HAFIF_ADIM = 12     # --hafif kipinde adım tavanı (araç çağrısı döngüsü; her adım bağlamı yeniden gönderir)
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


def render(item, template, okuma=OKUMA_GENEL, hafif=False):
    sorular = item.get("sorular") or []
    numbered = "\n".join(f"{i}. {s.strip()}" for i, s in enumerate(sorular, 1)) or "1. (belirtilmedi — konuyu kapsamlı ele al)"
    values = {
        "konu": item["konu"].strip(),
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
        try:
            kapsama.olgulari_oku(item)
        except kapsama.OlguHatasi as e:
            errors.append(f"#{i}: {e}")
        if "min_url" in item and not (isinstance(item["min_url"], int) and not isinstance(item["min_url"], bool) and MIN_URLS <= item["min_url"] <= 30):
            errors.append(f"#{i}: 'min_url' {MIN_URLS} ile 30 arasında tam sayı olmalı (bu konu için 'zayıf not' eşiği; varsayılan {WEAK_URLS})")
    return errors


# ----------------------------------------------------------------------------- ayrıştırıcılar (çevrimdışı test edilebilir)
def parse_opencode_events(stdout):
    """OpenCode --format json olaylarından nihai cevabı, araç sayımını, hataları ve jetonu çıkarır.

    Nihai cevap = `step_finish.reason == "stop"` ile biten adımın metni (gerçek akışta ölçüldü: ara adımlar "tool-calls" ile biter).
    Araç çağrısıyla biten (ör. adım sınırına/zaman aşımına takılan) bir akışta ara düşünce metni "cevap" sayılmaz; `tamam` False döner."""
    steps, reasons, step, tools, errors, tokens = {}, {}, 0, {}, [], [0, 0]
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
        elif kind == "text" and part.get("text"):
            steps.setdefault(step, []).append(part["text"])
        elif kind == "tool_use":
            name = part.get("tool") or "?"
            tools[name] = tools.get(name, 0) + 1
        elif kind == "step_finish":
            reasons[step] = part.get("reason")
            t = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
            cache = t.get("cache") if isinstance(t.get("cache"), dict) else {}
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
            "son_neden": reasons[max(reasons)] if reasons else None, "ayrinti": detail}


def redact(text):
    """Hata/günlük metninden anahtar benzeri değerleri siler (sonuç dosyasına ve ekrana sızmasın)."""
    return SECRET_RE.sub(lambda m: m.group(1) + m.group(2) + "[GİZLİ]", text or "")


def hata_ozeti(err, out="", rc=None, ad="", sinir=200):
    """Başarısız bir alt sürecin okunur özeti. Yalnız son satıra bakmak yanıltıcıydı (JSON hata çıktısında son satır "}" olabiliyor):
    harf/rakam içeren son 3 satır alınır, stderr boşsa stdout'a bakılır; komut adı ve çıkış kodu başa yazılır. Anahtar benzeri değerler maskelenir."""
    def anlamli(metin):
        return [l.strip() for l in (metin or "").splitlines() if sum(c.isalnum() for c in l) >= 3]
    satirlar = anlamli(err)[-3:] or anlamli(out)[-3:]
    govde = " | ".join(satirlar) if satirlar else "çıktı yok (komut sessiz bitti)"
    ozet = redact(f"{ad + ' ' if ad else ''}rc={rc}: {govde}")
    return ozet if len(ozet) <= sinir else "…" + ozet[-(sinir - 1):]


def check_contract(text, minimum=MIN_NOTE_BYTES):
    """Çalışan çıktısının sözleşmeye uyup uymadığı: (ok, neden). Boş/kısa/başlıksız/kaynaksız/plan metni çıktı başarı sayılmaz."""
    if len(text.encode("utf-8")) < minimum:
        return False, f"çıktı çok kısa (<{minimum} bayt)"
    if PLAN_RE.search(text[:1200]):   # plan/onay dili notun BAŞINDA olur; konu gereği geçen anmalar (gövdede) reddedilmez
        return False, "plan/onay metni döndürdü (araştırma yapılmadı): 'Plan Modu' bahanesiyle onay istedi"
    if not HEADING_RE.search(text):
        return False, f"'{REQUIRED_SECTION}' başlığı yok (çıktı sözleşmesi bozuk)"
    n_urls = len(set(URL_RE.findall(text)))
    if n_urls < MIN_URLS:
        return False, f"yalnız {n_urls} benzersiz URL (<{MIN_URLS}): kaynaklı bulgu yok"
    return True, ""


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
def opencode_config(effort, reader_cache=None, search=True, hafif=False):
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
        tools["oku_*"] = True
    else:
        tools["webfetch"] = True
    cfg["tools"] = tools
    return cfg


def work_opencode(prompt_text, note, base, model_key, effort, timeout, search, reader=True, hafif=False):
    key = api_key()
    if ayar.needs_key() and not key:
        return {"rc": 5, "hata": f"anahtar bulunamadı ({ayar.api_key_env()}: ortam ya da key_files; bkz. quoteproof.example.json)"}
    workdir = base / ".oc-calisma"
    workdir.mkdir(exist_ok=True)
    extra = {"OPENCODE_CONFIG_CONTENT": json.dumps(opencode_config(effort, base / "kaynaklar" if reader else None, search, hafif))}
    if ayar.needs_key():
        extra[ayar.api_key_env()] = key
    if search:
        extra.update(ayar.load()["runtime_env"])   # çalışma ortamının yerleşik arama aracını açan değişkenler
    env = clean_env(extra)
    cmd = opencode_argv(ayar.model_id(model_key, "opencode"), prompt_text, workdir, effort)
    rc, out, err, timed_out = run_cmd(cmd, env=env, cwd=str(workdir), timeout=timeout + 60)
    parsed = parse_opencode_events(out)
    if timed_out:
        return {"rc": 6, "hata": "OpenCode zaman aşımı", "jeton": parsed["jeton"], "araclar": parsed["araclar"], "ayrinti": parsed["ayrinti"]}
    if rc != 0 or parsed["hatalar"]:
        why = parsed["hatalar"][0] if parsed["hatalar"] else hata_ozeti(err, out, rc or 3, "opencode")
        return {"rc": rc or 3, "hata": redact(why)[:200], "jeton": parsed["jeton"], "araclar": parsed["araclar"], "ayrinti": parsed["ayrinti"]}
    if not parsed["tamam"]:
        return {"rc": 7, "hata": f"akış nihai cevap (reason=stop) olmadan bitti (adım sınırı/kesinti; son adım nedeni: {parsed['son_neden'] or 'yok'})", "jeton": parsed["jeton"],
                "araclar": parsed["araclar"]}
    note.write_text(parsed["metin"] + "\n", encoding="utf-8")
    return {"rc": 0, "jeton": parsed["jeton"], "araclar": parsed["araclar"], "ayrinti": parsed["ayrinti"]}


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
    text_mode = ayar.cli_format() == "text"
    parsed = parse_text_output(out) if text_mode else parse_responses_json(out)
    if rc != 0 or not parsed["metin"]:
        return {"rc": rc or 3, "hata": hata_ozeti(err, out, rc or 3, os.path.basename(cmd[0])) if rc else
                hata_ozeti(err, out, 0, os.path.basename(cmd[0]) + " (boş yanıt)")}
    note.write_text(parsed["metin"] + "\n", encoding="utf-8")
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
              "jeton": [0, 0], "araclar": {}}
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
                r = work_opencode(prompt_text, note, base, args.model, args.efor, args.sure, not args.arama_yok, use_mcp, hafif)
            else:
                r = work_cli(prompt_text, note, args.model, args.sure)
        except Exception as e:   # bir çalışanın beklenmedik çökmesi tüm koşuyu düşürmesin
            r = {"rc": 8, "hata": redact(f"{type(e).__name__}: {e}")[:200]}
        result["rc"], result["hata"] = r["rc"], r.get("hata", "")
        for k in (0, 1):   # jeton/araç sayıları tüm denemeler boyunca birikir (maliyet gerçeği)
            result["jeton"][k] += (r.get("jeton") or [0, 0])[k]
        for name, n in (r.get("araclar") or {}).items():
            result["araclar"][name] = result["araclar"].get(name, 0) + n
        text = note.read_text(encoding="utf-8", errors="replace") if note.exists() else ""
        size = len(text.encode("utf-8"))
        result["bayt"] = size
        ok_contract, why = check_contract(text) if r["rc"] == 0 else (False, "")
        tools_used = r.get("araclar")
        if ok_contract and backend == "opencode" and isinstance(tools_used, dict) and \
                not any(k.startswith(("websearch", "oku_", "webfetch")) for k in tools_used):
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
                                    "jeton": r.get("jeton") or [0, 0], "araclar": r.get("araclar") or {}, "ayrinti": r.get("ayrinti")})   # deneme başına maliyet/teşhis
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
    """Başarılı ama kaynak kapsamı zayıf notlar. Eşik konu başına: varsayılan WEAK_URLS; dar bir konuda plan `min_url` ile değiştirir."""
    thresholds = {item["slug"]: item.get("min_url", WEAK_URLS) for item in plan}
    weak = []
    for slug_ok in [r["slug"] for r in results if r["ok"]]:
        note_path = base / "notlar" / f"{slug_ok}.md"
        if note_path.exists() and url_count(note_path.read_text(encoding="utf-8", errors="replace")) < thresholds.get(slug_ok, WEAK_URLS):
            weak.append(slug_ok)
    return weak


# ----------------------------------------------------------------------------- ana akış
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
    ap.add_argument("--hafif", action="store_true", help="jeton tasarrufu: konuya ölçekli az arama/çağrı bütçesi, aramada en çok 4 sonuç, adım tavanı 12 (alıntı sözleşmesi ve doğrulama aynen)")
    ap.add_argument("--link-yok", action="store_true", help="denetimde bağlantı kontrolünü atla")
    ap.add_argument("--okuyucu", default="mcp", choices=["mcp", "yerlesik"],
                    help="mcp: OpenCode çalışanı sayfayı sıkıştırılmış okur (oku MCP, webfetch kapalı) · yerlesik: OpenCode webfetch (tam sayfa)")
    ap.add_argument("--dogrula-yok", action="store_true", help="otomatik iddia–kaynak doğrulamasını (dogrula.py) atla")
    ap.add_argument("--arama-yok", action="store_true", help="çalışma ortamının yerleşik `websearch` aracını açma (yalnız webfetch/MCP kalır)")
    ap.add_argument("--devam", action="store_true",
                    help="kesilen koşuyu sürdür: aynı istemle (özet) tamamlanmış ve sözleşmeye uyan notlar yeniden üretilmez")
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

    base = (Path(args.dizin) if args.dizin else plan_path.parent).resolve()  # mutlak yol: alt süreçlerin cwd/--dir çözümü PWD'ye bağlı kalmasın
    (base / "istemler").mkdir(parents=True, exist_ok=True)
    (base / "notlar").mkdir(parents=True, exist_ok=True)
    template = load_template()
    primary_mcp = args.arka in ("otomatik", "opencode") and args.okuyucu == "mcp"
    for item in plan:
        (base / "istemler" / f"{item['slug']}.md").write_text(render(item, template, OKUMA_MCP if primary_mcp else OKUMA_GENEL, getattr(args, "hafif", False) is True), encoding="utf-8")
    print(f"arastir: {len(plan)} istem yazıldı → {base}/istemler")
    if args.kuru:
        return 0

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
        if prev and prev.get("ok") and prev.get("hash") == prompt_hash[slug] and note.exists() and \
                check_contract(note.read_text(encoding="utf-8", errors="replace"))[0]:
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
        tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
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
    (base / "calisma.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
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
        print(f"arastir: ⚠ ZAYIF not (eşik altı benzersiz kaynak; varsayılan <{WEAK_URLS}, konuda `min_url` ile değişir): {', '.join(weak)}. Arama hız sınırına (429) takılmış olabilir: "
              f"notlar/<slug>.md'yi silip `-j 2` ile `--devam` koştur ya da konuyu bölüp yeniden çalıştır.", flush=True)
    code = 0
    cmd = [sys.executable, str(HERE / "denetle.py"), str(base / "notlar")]
    cmd += ["--plan", str(plan_path), "--cikti", str(base / "denetim.md"), "--dosyalar", *good]
    if args.link_yok:
        cmd.append("--link-yok")
    print("\n" + "=" * 60)
    rc = subprocess.run(cmd, check=False).returncode
    if rc != 0:
        print(f"arastir: UYARI denetle.py beklenmedik çıkış kodu {rc}; denetim güvenilmez", file=sys.stderr)
        code = max(code, 71)
    if not args.dogrula_yok and not args.link_yok:
        print("\n" + "=" * 60)
        vcmd = [sys.executable, str(HERE / "dogrula.py"), str(base / "notlar")]
        vcmd += ["--plan", str(plan_path), "--cikti", str(base / "dogrulama.md"), "--onbellek", str(base / "kaynaklar"),
                 "--temiz-yaz", str(base / "notlar-temiz"), "--dosyalar", *good]
        rc = subprocess.run(vcmd, check=False).returncode
        if rc != 0:
            print(f"arastir: UYARI dogrula.py çıkış kodu {rc}; otomatik doğrulama YAPILMADI, iddiaları elle doğrulayın", file=sys.stderr)
            code = max(code, 72)
    if any(it.get("olgular") for it in plan):   # beklenen olgulara göre kapsama (0 jeton): eksikler için ek plan yazılır
        nd = base / "notlar-temiz" if (base / "notlar-temiz").is_dir() else base / "notlar"
        res = kapsama.run(plan, [nd], labels=["bu çalıştırma"], files=good)
        (base / "kapsama.md").write_text(kapsama.render(res), encoding="utf-8")
        print("\n" + "=" * 60)
        for slug, r in res.items():
            low = r["kapsanan"] / max(1, r["toplam"]) < kapsama.VARSAYILAN_ESIK
            print(f"arastir: kapsama {slug}: {r['kapsanan']}/{r['toplam']} olgu" + (f" · eksik: {'; '.join(e['ad'] for e in r['eksik'])[:200]}" if r["eksik"] else ""))
            if low:
                code = max(code, 73)
        ep = kapsama.eksik_plan(res)
        if ep:
            (base / "eksik-PLAN.json").write_text(json.dumps(ep, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"arastir: eksik olgular için ek plan: {base / 'eksik-PLAN.json'} → `arastir.py eksik-PLAN.json -d BASKA_DIZIN --hafif`, sonra "
                  f"`uzlas.py <bu>/notlar-temiz BASKA_DIZIN/notlar-temiz --yaz birlesik/` ile birleştir", flush=True)
    if failed or weak:
        code = max(code, 73)   # kısmi başarı: bazı konular eksik ya da zayıf
    return code


if __name__ == "__main__":
    sys.exit(main())
