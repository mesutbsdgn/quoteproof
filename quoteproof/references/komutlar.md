# Komut satırları (tam liste, özgün açıklamalarla)

SKILL.md yalnız çekirdek komutları tutar; seyrek kullanılanlar (anlam, rapor_olc, guven, robots, llms/anahat/tam/jina) burada. `S=~/.agents/skills/quoteproof/scripts`

```bash
S=~/.agents/skills/quoteproof/scripts
python3 $S/arastir.py PLAN.json -d ARASTIRMA_DIZINI [--arka otomatik|opencode|cli] [--model AD] [-e dusuk|orta] [-j 3] [-t 420] [--hafif] [--bosluk-turu 0..3]
python3 $S/denetle.py ARASTIRMA_DIZINI/notlar [--link-yok] [--github-yok] [--aday 8] [--dosyalar a.md ..]   # denetim: biçim, bağlantı canlılığı (güvenli HTTP katmanı), GitHub depoları (0 token)
python3 $S/dogrula.py ARASTIRMA_DIZINI/notlar [--en-cok N] [--temiz-yaz DIZIN] [--dosyalar a.md ..]   # iddia–kaynak OTOMATİK doğrulama; varsayılan TÜM bulgular (0 jeton). --temiz-yaz: 'Bulunamadı' maddeleri çıkarılmış kopyalar = sentez girdisi
python3 $S/destek.py ARASTIRMA_DIZINI/notlar-temiz [--siki]   # Özet/Çıkarımlar cümlelerindeki sayı/tarih/tanımlayıcı alıntıda ya da atıf sayfalarında var mı (0 jeton; arastir.py kendisi çalıştırır, destek.md yazar)
python3 $S/anlam.py ARASTIRMA_DIZINI [--isaretle] [--kuru]   # İSTEĞE BAĞLI NLI anlam denetimi (ayrı venv; varsayılan kapalı): anlam.md + anlam.json yazar, --isaretle notlar-temiz'i işaretler
python3 $S/rapor_olc.py RAPOR1.md [RAPOR2.md ..] [--ulkeler "A,B"]   # raporları aynı ölçütlerle say (sözcük, başlık uyumu, URL ve kaynak sınıfı, boşluk ifadesi, KESİK çıktı, ülke kapsamı); 0 jeton
python3 $S/rapor_kontrol.py rapor.md --notlar DIZIN/notlar --onbellek DIZIN/kaynaklar --siki   # NİHAİ RAPORU teslimden önce denetle; hata/uyarı varsa düzelt veya denetlenemedi diye açıkça bildir; 0 jeton
python3 $S/oku.py URL --soru "..." [--token 900]        # tek sayfayı KISA oku (ana içerik + BM25 pasajlar; tam sayfadan ~20-40x az jeton)
python3 $S/oku.py URL --ara "rakam/alıntı" [--ara ...]  # ifade sayfada geçiyor mu? (bağlamıyla; doğrulama)
python3 $S/guven.py URL [URL ..] [--plan PLAN.json]     # kaynak güvenilirlik puanı (0-100, alan adı sınıfı + sinyaller; denetle/dogrula otomatik kullanır)
python3 $S/oku.py URL --robots                           # robots.txt bu adrese izin veriyor mu?
python3 $S/ayar.py                                      # yapılandırma durumu (model, anahtar var/yok, cli arka ucu; anahtar DEĞERİ yazılmaz)
python3 $S/oku.py URL --llms | --anahat | --tam | --jina   # llms.txt dizini · başlık anahattı · temiz Markdown · 3. taraf yedek (JS'li sayfa). PDF (`pdftotext`, sayfa başlıklı) ve GitHub depo/blob adresleri (anonim raw README) otomatik işlenir
```

PDF okuyucusu 60 sayfada kesmez; `pdftotext` ile tüm sayfaları çıkarır. İndirme boyutu ve metin çıkarma için 40 saniyelik süre sınırı geçerlidir.

PDF okuyucusu 60 sayfada kesmez; `pdftotext` ile tüm sayfaları çıkarır. İndirme boyutu ve metin çıkarma için 40 saniyelik süre sınırı geçerlidir.
