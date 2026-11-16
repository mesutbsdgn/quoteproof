# Okuma merdiveni

Bir sayfayı okurken jeton tasarrufu için; SKILL.md'den taşındı.

## Okuma merdiveni (jeton tasarrufu; araştırma kaynak: `references/kaynak-arastirmasi-2026-10.md`)

Sayfayı bağlama TAMAMEN alma. Basamakları sırayla çık, gerekmedikçe bir üst basamağa geçme:

| # | Ne | Araç | Ne zaman |
|---|---|---|---|
| 1 | Arama özeti (snippet) | `websearch` / `web_search` sonucu | aday seçmek için; kanıt değildir |
| 2 | Sorguya göre kısa okuma | `oku.py URL --soru` (çalışanda `oku_sayfa_oku`) | umut verici sayfa; yalnız ilgili pasajlar |
| 3 | Rakam/alıntı doğrulama | `oku.py URL --ara` (çalışanda `oku_sayfada_ara`) | iddiayı sayfada aramak |
| 4 | Ajan dostu kaynak | `Accept: text/markdown` (otomatik), `oku.py --llms` | doküman siteleri |
| 5 | Temiz tam metin | `oku.py URL --tam --token 4000` | gerçekten uzun/derin okuma gerekirse |
| 6 | Harici/tarayıcı | `--jina` (3. taraf), tarayıcı otomasyonu MCP'si | JS ile yüklenen, giriş isteyen sayfa |

Sayfalar `kaynaklar/` altında saklanır (Fetch-then-Explore): aynı sayfa tekrar çekilmez, doğrulama ve yeniden sorgu bedavadır.
GitHub depo URL'si → anonim raw README (bayat HTML yerine). **Depo bilgisi (⭐, aktiflik) için modele güvenme**; `denetle.py` GitHub bölümüne bak:
yıldız ≠ aktiflik (arşivli/durgun depo bayrağı).
