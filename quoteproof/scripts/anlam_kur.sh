#!/usr/bin/env bash
# quoteproof — İSTEĞE BAĞLI anlam (NLI) denetimi kurulumu (ELLE çalıştırılır; otomatik çağrılmaz).
#
# Ne indirir:
#   - torch + transformers + bağımlılıkları (~0,9 GB)
#   - NLI modeli MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7 (~0,55 GB, yalnız safetensors ağırlıkları)
# Toplam yaklaşık 1,5 GB. Lisans: MIT (hem kod hem model).
# Çevrimdışı çalışır: model yereldir, ağ yalnız bu kurulumda kullanılır.
#
# Kur:  bash quoteproof/scripts/anlam_kur.sh
# Sonra ~/.config/quoteproof/config.json içine çıktıdaki nli_backend bloğunu ekleyin ve arastir.py'yi --anlam ile çalıştırın.
set -euo pipefail

VENV="$HOME/.cache/quoteproof/nli-venv"
MODEL_DIR="$HOME/.cache/quoteproof/nli-model"
REPO="MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"

echo "anlam kurulumu: venv → $VENV"
mkdir -p "$HOME/.cache/quoteproof"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install torch transformers sentencepiece protobuf huggingface_hub

echo "anlam kurulumu: model → $MODEL_DIR (yalnız safetensors; pickle .bin İNDİRİLMEZ)"
"$VENV/bin/python" - "$REPO" "$MODEL_DIR" <<'PY'
import sys
from huggingface_hub import snapshot_download
repo, local_dir = sys.argv[1], sys.argv[2]
snapshot_download(
    repo_id=repo,
    local_dir=local_dir,
    allow_patterns=["*.safetensors", "config.json", "tokenizer*", "spm.model",
                    "special_tokens_map.json", "added_tokens.json", "*.txt"],
)
print(f"model indirildi: {local_dir}")
PY

cat <<EOF

Kurulum tamam. ~/.config/quoteproof/config.json dosyasına (var olan yapılandırmayı KORUYARAK) şu bloğu ekleyin:

  "nli_backend": {
    "python": "$VENV/bin/python",
    "model_dir": "$MODEL_DIR",
    "esik": 0.10,
    "pencere": 300,
    "cihaz": "auto"
  }

Bu betik yapılandırma dosyasını DEĞİŞTİRMEZ. Doğrulama: python3 quoteproof/scripts/ayar.py  (→ "anlam: var")
EOF