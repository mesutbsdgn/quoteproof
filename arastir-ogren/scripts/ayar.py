#!/usr/bin/env python3
"""Yapılandırma: sağlayıcı / model / anahtar ayrıntıları koda gömülü DEĞİLDİR; kullanıcıya özel bir JSON dosyasından okunur.

Arama sırası (ilk bulunan kazanır):
  1. ortam değişkeni QUOTEPROOF_CONFIG (dosya yolu)
  2. <skill dizini>/quoteproof.json            (git'e girmez; .gitignore'dadır)
  3. ~/.config/quoteproof/config.json

Şema (örnek: quoteproof.example.json):
  models         {ad: {"opencode": "SAĞLAYICI/MODEL", "cli": "MODEL"}}  — çalışan arka uçlarının model kimlikleri
  default_model  models içinden varsayılan ad
  api_key_env    çalışan ortamına verilecek anahtar değişkeninin ADI (null → anahtar gerekmez)
  key_files      `DEĞİŞKEN=değer` biçiminde anahtar dosyaları (ortamda yoksa buralara bakılır)
  runtime_env    çalışma ortamının yerleşik arama aracını açan ek ortam değişkenleri (ör. {"AD": "1"})
  cli_backend    {"command": [... "{model}" "{prompt}" "{timeout}" ...], "format": "responses-json" | "text"}  — isteğe bağlı komut satırı arka ucu
                 responses-json: çıktı output[] (web_search_call / message) taşıyan JSON · text: standart çıktının TAMAMI nottur (ANSI renkleri atılır)
                 prompt_via: "arg" (varsayılan; istem komutta {prompt} yerine konur) | "stdin" (istem komutun standart girdisine yazılır; komutta {prompt} OLMAMALI)

Anahtar değerleri asla yazdırılmaz veya kaydedilmez; yalnız alt sürecin ortamına verilir.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # skill dizininde __pycache__/.pyc üretme

HERE = Path(__file__).resolve().parent
SEARCH_PATHS = (HERE.parent / "quoteproof.json", Path.home() / ".config/quoteproof/config.json")
CLI_FORMATS = ("responses-json", "text")
CLI_PROMPT_VIA = ("arg", "stdin")
DEFAULTS = {"models": {}, "default_model": None, "api_key_env": "LLM_API_KEY", "key_files": [], "runtime_env": {}, "cli_backend": None}
_cache = {}


class ConfigError(Exception):
    pass


def config_path():
    """Kullanılacak yapılandırma dosyası (yoksa None)."""
    env = os.environ.get("QUOTEPROOF_CONFIG")
    if env:
        return Path(env).expanduser()
    for p in SEARCH_PATHS:
        if p.is_file():
            return p
    return None


def _validate(cfg):
    models = cfg.get("models")
    if not isinstance(models, dict):
        raise ConfigError("'models' bir nesne olmalı")
    for name, ids in models.items():
        if not isinstance(ids, dict) or not all(isinstance(v, str) and v for v in ids.values()):
            raise ConfigError(f"models.{name}: {{\"opencode\": \"...\", \"cli\": \"...\"}} biçiminde metin kimlikleri olmalı")
    if cfg.get("default_model") is not None and cfg["default_model"] not in models:
        raise ConfigError(f"default_model '{cfg['default_model']}' models içinde yok")
    if cfg.get("api_key_env") is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(cfg["api_key_env"])):
        raise ConfigError("api_key_env geçerli bir ortam değişkeni adı olmalı")
    if not isinstance(cfg.get("key_files"), list) or not isinstance(cfg.get("runtime_env"), dict):
        raise ConfigError("key_files liste, runtime_env nesne olmalı")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in cfg["runtime_env"].items()):
        raise ConfigError("runtime_env değerleri metin olmalı")
    cli = cfg.get("cli_backend")
    if cli is not None and not (isinstance(cli, dict) and isinstance(cli.get("command"), list) and cli["command"]
                                and all(isinstance(a, str) for a in cli["command"])):
        raise ConfigError("cli_backend.command boş olmayan bir metin listesi olmalı")
    if cli is not None and cli.get("format", "responses-json") not in CLI_FORMATS:
        raise ConfigError(f"cli_backend.format şunlardan biri olmalı: {', '.join(CLI_FORMATS)}")
    if cli is not None:
        via = cli.get("prompt_via", "arg")
        if via not in CLI_PROMPT_VIA:
            raise ConfigError(f"cli_backend.prompt_via şunlardan biri olmalı: {', '.join(CLI_PROMPT_VIA)}")
        has_placeholder = any("{prompt}" in a for a in cli["command"])
        if via == "arg" and not has_placeholder:
            raise ConfigError("cli_backend.prompt_via=\"arg\" iken komutta {prompt} yer tutucusu olmalı (ya da prompt_via=\"stdin\" seçin)")
        if via == "stdin" and has_placeholder:
            raise ConfigError("cli_backend.prompt_via=\"stdin\" iken komutta {prompt} OLMAMALI (istem standart girdiden gider)")


def load(refresh=False):
    """Birleştirilmiş yapılandırma (varsayılanlar + dosya). Dosya yoksa varsayılanlar döner (hiçbir model tanımsız)."""
    if _cache and not refresh:
        return _cache["cfg"]
    cfg = json.loads(json.dumps(DEFAULTS))
    path = config_path()
    if path:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ConfigError(f"{path}: okunamadı ({e})")
        if not isinstance(data, dict):
            raise ConfigError(f"{path}: JSON nesnesi bekleniyordu")
        cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    _validate(cfg)
    _cache["cfg"] = cfg
    return cfg


def reset():
    _cache.clear()


def model_names():
    return sorted(load()["models"])


def default_model():
    cfg = load()
    return cfg["default_model"] or (model_names()[0] if cfg["models"] else None)


def model_id(name, backend):
    """Arka uç için model kimliği; tanımsızsa ConfigError."""
    ids = load()["models"].get(name)
    if ids is None:
        raise ConfigError(f"model '{name}' yapılandırmada yok (tanımlılar: {', '.join(model_names()) or 'hiçbiri'})")
    if backend not in ids:
        raise ConfigError(f"model '{name}' için '{backend}' kimliği tanımlı değil")
    return ids[backend]


def api_key_env():
    return load()["api_key_env"]


def api_key():
    """Anahtar: ortam → key_files (`[export] DEĞİŞKEN=değer`). Yoksa ''. Değer asla yazdırılmaz."""
    name = api_key_env()
    if not name:
        return ""
    if os.environ.get(name):
        return os.environ[name]
    pattern = re.compile(r"^\s*(?:export\s+)?" + re.escape(name) + r"\s*=\s*(.*?)\s*$")
    for raw in load()["key_files"]:
        try:
            for line in Path(raw).expanduser().read_text(encoding="utf-8").splitlines():
                m = pattern.match(line)
                if m and m.group(1).strip("'\""):
                    return m.group(1).strip("'\"")
        except OSError:
            continue
    return ""


def needs_key():
    return bool(api_key_env())


def cli_command(model, prompt, timeout):
    """cli_backend.command şablonunu doldurur ({model} {prompt} {timeout}); yapılandırılmamışsa None. `.format` KULLANILMAZ:
    argümanlardaki JSON süslü parantezleri bozulmasın."""
    cli = load()["cli_backend"]
    if not cli:
        return None
    subs = {"{model}": model, "{prompt}": prompt, "{timeout}": str(timeout)}
    # TEK geçişte yer değiştirme: istem metninde literal "{timeout}" / "{model}" geçse bile sonraki adımlarda bozulmaz.
    token_re = re.compile("|".join(re.escape(t) for t in subs))
    return [token_re.sub(lambda m: subs[m.group(0)], arg) for arg in cli["command"]]


def cli_prompt_via():
    """"arg" (istem komut argümanında) ya da "stdin" (istem standart girdiden)."""
    cli = load()["cli_backend"] or {}
    return cli.get("prompt_via", "arg")


def cli_format():
    cli = load()["cli_backend"] or {}
    return cli.get("format", "responses-json")


def describe():
    """Bir satırlık durum (anahtar değeri YOK)."""
    path = config_path()
    cfg = load()
    return (f"yapılandırma: {path or 'yok (varsayılanlar)'} · modeller: {', '.join(model_names()) or 'tanımsız'} · "
            f"anahtar: {'tamam' if (api_key() or not needs_key()) else 'EKSİK'} · cli arka ucu: {'var' if cfg['cli_backend'] else 'yok'}")


if __name__ == "__main__":
    try:
        print(describe())
    except ConfigError as e:
        print(f"ayar: {e}", file=sys.stderr)
        sys.exit(78)
