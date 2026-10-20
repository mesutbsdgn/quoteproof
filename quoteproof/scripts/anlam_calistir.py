#!/usr/bin/env python3
"""İSTEĞE BAĞLI NLI çalışanı: (öncül, hipotez) çiftlerine çok dilli NLI modeliyle üç olasılık verir. Bu dosya `torch` + `transformers` ister;
hattın kendisi bağımlılıksızdır, `anlam.py` bu dosyayı AYRI bir sanal ortamın Python'uyla alt süreç olarak çalıştırır (bkz. SKILL.md "Anlam denetimi").

Girdi (stdin, JSONL): {"id": ..., "premise": "...", "hypothesis": "..."}
Çıktı (stdout, JSONL): {"id": ..., "entailment": 0..1, "neutral": 0..1, "contradiction": 0..1}  (satır başına bir giriş, aynı sırada)
Model yerelden okunur (ağ YOK: HF_HUB_OFFLINE=1); yalnız `.safetensors` ağırlıkları yüklenir, `trust_remote_code` KAPALI.

Kullanım: <venv>/bin/python anlam_calistir.py --model YEREL_MODEL_DIZINI [--parti 8] [--azami-token 384] [--cihaz auto|cpu|mps]
"""
import argparse
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="yerel model dizini (safetensors)")
    ap.add_argument("--parti", type=int, default=8)
    ap.add_argument("--azami-token", type=int, default=384, help="öncül+hipotez için üst sınır (öncül kırpılır)")
    ap.add_argument("--cihaz", default="auto", choices=("auto", "cpu", "mps"))
    a = ap.parse_args(argv)
    try:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as e:
        print(f"anlam_calistir: torch/transformers yok ({e}); NLI sanal ortamını kurun (SKILL.md)", file=sys.stderr)
        return 3
    cihaz = a.cihaz
    if cihaz == "auto":
        cihaz = "mps" if torch.backends.mps.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=False)
    model = AutoModelForSequenceClassification.from_pretrained(a.model, trust_remote_code=False, use_safetensors=True).to(cihaz).eval()
    etiket = {int(i): str(l).lower() for i, l in model.config.id2label.items()}
    for ad in ("entailment", "neutral", "contradiction"):
        if ad not in etiket.values():
            print(f"anlam_calistir: model etiketlerinde '{ad}' yok: {etiket}", file=sys.stderr)
            return 3
    satirlar = [json.loads(l) for l in sys.stdin if l.strip()]
    for i in range(0, len(satirlar), a.parti):
        parti = satirlar[i:i + a.parti]
        enc = tok([str(s["premise"]) for s in parti], [str(s["hypothesis"]) for s in parti], truncation="only_first",
                  max_length=a.azami_token, padding=True, return_tensors="pt").to(cihaz)
        with torch.no_grad():
            p = torch.softmax(model(**enc).logits.float(), dim=-1).cpu().tolist()
        for s, row in zip(parti, p):
            out = {"id": s.get("id")}
            for idx, ad in etiket.items():
                out[ad] = round(row[idx], 4)
            print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
