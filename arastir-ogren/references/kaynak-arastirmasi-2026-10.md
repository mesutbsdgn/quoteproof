# Yapay zeka ajanları web'de nasıl gezip okuyor? (GitHub kaynak araştırması, 8 Ekim 2026)

> Bu rapor `arastir-ogren`'in kendisiyle üretildi: 4 paralel LLM çalışanı (183 bulgu, 153 bağlantı), 42 GitHub deposu `gh api` ile doğrulandı,
> 14 iddia otomatik olarak kaynakta arandı. Doğrulama durumu parantezde: **(D)** = kaynakta birebir bulundu, **(K)** = kısmen, **(—)** = otomatik denenmedi/çalışan notuna dayanıyor.

**Kısa cevap.** Açık kaynak "derin araştırma" ajanlarının neredeyse hepsi aynı iskeleti kullanıyor: planla → paralel topla → boşlukları doldur → atıfla yaz. Farkı yaratan üç şey var:
sayfanın ajana **hangi biçimde** verildiği (erişilebilirlik ağacı, temiz Markdown, ekran görüntüsü), okumanın **ne kadar sıkıştırıldığı**, ve atıfların **gerçekten doğrulanıp doğrulanmadığı**.
En ölçülmüş "hızlı okuma" kalıbı, sayfayı baştan bağlama almak yerine yerelde tutup soruya göre sonradan pasaj çekmek (Fetch-then-Explore). İstemle "atıf ver" demek yetmiyor; birebir alıntı + otomatik doğrulama gerekiyor.
Yıldız sayısı aktiflik göstermiyor: `langchain-ai/open_deep_research` (12,7 bin ⭐) **arşivlenmiş**, `stanford-oval/storm` (31,6 bin ⭐) 372 gündür sessiz.

**Güven: Orta-yüksek.** Depo verileri doğrudan GitHub'dan; benchmark rakamlarının bir kısmı çalışan notlarına dayanıyor ve (K)/(—) işaretli.

## Yıldız aktiflik değildir: depoların gerçek durumu
`gh api` ile 8 Ekim 2026'da doğrulandı.

| Depo | ⭐ | Son push | Rolü |
|---|---:|---|---|
| firecrawl/firecrawl | 189.755 | bugün | web → LLM verisi API'si, tarama + Markdown |
| browser-use/browser-use | 117.488 | bugün | tarayıcıyı kullanan ajan (DOM + erişilebilirlik + yerleşim) |
| modelcontextprotocol/servers | 91.080 | bugün | referans MCP sunucuları (`fetch` dahil) |
| unclecode/crawl4ai | 85.004 | 3 gün | LLM için tarayıcı; `fit_markdown`, BM25/budama filtreleri |
| microsoft/playwright-mcp | 37.930 | bugün | erişilebilirlik anlık görüntüsü ile tarayıcı kontrolü |
| stanford-oval/storm | 31.592 | **372 gün (durgun)** | bilgi derleme/rapor üretimi, akademik köken |
| assafelovic/gpt-researcher | 29.953 | 6 gün | otonom derin araştırma; aktif |
| browserbase/stagehand | 25.575 | bugün | tarayıcı eylemleri için SDK |
| Skyvern-AI/skyvern | 23.157 | bugün | görsel (ekran görüntüsü) tabanlı tarayıcı otomasyonu |
| Alibaba-NLP/DeepResearch | 20.021 | 223 gün | Tongyi Deep Research |
| dzhng/deep-research | 19.769 | 179 gün | yinelemeli derin araştırma (minimal) |
| langchain-ai/open_deep_research | 12.683 | **arşivli** | LangChain referansı; artık bakım yok |
| jina-ai/reader | 12.127 | 139 gün | `r.jina.ai/<url>` ile URL → LLM dostu metin |
| mozilla/readability | 11.484 | 65 gün | ana içerik ayıklama (Firefox Reader View) |
| microsoft/LLMLingua | 6.739 | 27 gün | istem/bağlam sıkıştırma |
| jina-ai/node-DeepResearch | 5.237 | 159 gün | arama–oku–akıl yürüt döngüsü, "Beast Mode" |

Çalışan notlarındaki yıldız sayıları (ör. 28.868, 8.855) bayattı; bu tablodaki değerler doğrudan GitHub'dan geliyor. Ders: depo bilgisi her zaman `gh api` ile teyit edilmeli (`denetle.py` bunu otomatik yapar).

## Derin araştırma ajanları aynı iskeleti paylaşıyor
Baskın kalıp planlayıcı → paralel araştırmacılar → yazar; üstüne bir **boşluk (gap) döngüsü**. Olgun sistemlerde boşluk ayrı bir durum nesnesi (gaps/frontier) ve bitiş koşuluna bağlı.
Dinamik varyantlar (WebWeaver, WebThinker) planı ve kanıt toplamayı iç içe yürütüyor ([WebWeaver](https://arxiv.org/html/2509.13312v3)).
**Durma/bütçe** iki felsefede: maliyet-kısıcı erken durma ve Jina'nın "Beast Mode"u (bütçe bitince yalnız "cevap ver" eylemine izin verip cevabı zorlar, boş el dönmez) ([DeepWiki: node-DeepResearch](https://deepwiki.com/jina-ai/node-DeepResearch/3.1-agent-research-loop), —).
`arastir-ogren` bu ikisini birleştiriyor: tek boşluk turu + çalışana araç bütçesi ve "bütçe bitince elindekiyle yaz" kuralı.

## Ajanlar web'de üç biçimde geziniyor
1. **Erişilebilirlik ağacı / anlık görüntü** (Playwright MCP, Stagehand): ucuz, deterministik, `ref=e5` gibi indekslerle eylem; "önce ağaç, gerekirse ekran görüntüsü" fiili varsayılan ([Playwright MCP](https://playwright.dev/mcp/snapshots), —). browser-use saf ağaç değil, DOM + erişilebilirlik + yerleşim birleşimi. Token sayıları sayfaya göre 10 kata kadar değişiyor; satıcı rakamları gösterge sayılmalı.
2. **Ekran görüntüsü + görüntü modeli** (Skyvern, bilgisayar kullanımı): pahalı ama canvas/görsel içerikte tek sinyal.
3. **Tarayıcısız okuma** (Jina Reader, Firecrawl, Crawl4AI, MCP `fetch`): HTML→Markdown'ı sunucuda yapar; boilerplate ve JS-render'ı çözer, giriş/MFA/CAPTCHA'da yetersiz kalır. Tek sayfa için Jina/`fetch`, site taraması için Firecrawl/Crawl4AI.

**Ajan dostu standartlar:** `llms.txt` (kürasyonlu dizin; [llmstxt.org](https://llmstxt.org/index.html)) geliştirici dokümanlarında yaygın, genel web'de düşük tek haneli; asıl ürünleşen mekanizma
`Accept: text/markdown` içerik pazarlığı ([acceptmarkdown.com](https://acceptmarkdown.com/guides/accept-text-markdown)). Nazik gezinme: dürüst User-Agent, `robots.txt`, hız sınırı, `429/Retry-After`;
Cloudflare Content Signals `search / ai-input / ai-train` ayrımını getiriyor ([Cloudflare](https://developers.cloudflare.com/bots/additional-configurations/managed-robots-txt/), **D**).

## Hızlı ve kısa okuma: ayıkla → sırala → sıkıştır
- **Ayıklama:** kural tabanlı `trafilatura` makale sayfalarında en iyi denge (çalışan özeti F1 ≈ 0,79–0,93; kaynakta doğrulanan örnekler: readability-lxml 0,853, news-please 0,836, goose3 0,810); en yavaş/zayıf halka nöral ReaderLM-v2 (sayfa başına 10,4 sn). Makale dışı yapılarda (ürün, forum) tüm araçlar 0,41–0,84'e düşüyor ([trafilatura değerlendirmesi](https://trafilatura.readthedocs.io/en/latest/evaluation.html), **D**; [WCXB](https://arxiv.org/html/2605.21097v1), **K**).
- **Sorgu odaklı seçim:** önce gürültü budama (metin/bağlantı yoğunluğu), sonra BM25 ya da embedding/reranker ile pasaj sıralama; Crawl4AI bunu `fit_markdown` + BM25 filtresi olarak sunuyor ([Crawl4AI](https://docs.crawl4ai.com/extraction/llm-strategies/), **K**). BM25 tek başına yeterli değil; soru-duyarlı sıkıştırma sıralamayı geçebiliyor.
- **Sıkıştırma:** LLMLingua ailesi 2×–20× sıkıştırma bildiriyor; 2×–5× bandı "neredeyse ücretsiz", 20× kısa istemlerde riskli ([LLMLingua-2](https://aclanthology.org/2024.findings-acl.57.pdf), —). Map-reduce kazancı jetondan çok ölçeklenebilirlik.
- **Fetch-then-Explore (FtE):** seçmeyi (fetch) çıkarımdan (grep/read) ayırıp sayfaları kalıcı çalışma alanında tutmak, snippet-only ve ziyaret-et-oku tabanlarını geçiyor ([arXiv 2608.02097](https://arxiv.org/html/2608.02097), —). Snippet insan triyajı içindir; tam sayfa ise gürültülüdür (bir örnekte gövdenin ~%97'si sayfa dışı öğe).

## Doğrulama: alıntıyı üretmek ile doğrulamak ayrı işler
Açık kaynakta atıf güvenilirliği düşük: yalnız istemle atıf isteyen sistemlerde geçerli alıntı oranı ~%18–28 ([QuoteVerify](https://lemma-public-asset.analemma.ai/online/fars/live/live_live_20260213/idea_e13040b9-9791-48ac-8185-1a5f6f3ed90f/main.pdf), —).
Çalışan tasarım **katmanlı**: kimlik/varlık denetimi (DOI, depo, URL canlılığı) → sözcüksel ön kapı (alıntı/rakam sayfada geçiyor mu) → LLM yargıcı → gerekirse ikinci yargıç. Doğrulayıcı üreticiden bağımsız ve **kaynağa kısıtlı** olmalı.
Değerlendirmede iki yetenek ayrı ölçülmeli: doğru bilgiyi bulmak ([BrowseComp](https://arxiv.org/abs/2508.06600), BrowseComp-Plus) ve bulduğunu doğru atıflamak ([DeepResearch Bench FACT](https://deepresearch-bench.github.io/), **D**): yüksek atıf sayısı düşük doğrulukla gelebilir.

## Web içeriği güvenilmezdir: işaretle ve yetkiyi kıs
Tek başına filtre yetmiyor. Savunma iki eksende: içeriği **veri olarak işaretleme** (spotlighting/datamarking; saldırı başarısını %50'nin üzerinden %2'nin altına indirdiği bildirilmiş, [Microsoft Research](https://www.microsoft.com/en-us/research/publication/defending-against-indirect-prompt-injection-attacks-with-spotlighting/), —)
ve güvenilmez içerik alındıktan sonra **eylemi kısıtlama** ([Design Patterns](https://arxiv.org/abs/2506.08837), [CaMeL](https://arxiv.org/abs/2503.18813)). Çerçeve olarak "lethal trifecta": özel veri + güvenilmez içerik + dış iletişim bir aradaysa sızıntı mümkün; üçünden birini kaldır ([Simon Willison](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/), —).

## Bu bulgular `arastir-ogren`'e nasıl yansıdı
| Bulgu | Uygulama |
|---|---|
| Depo bilgisi bayat/uydurma olabilir | `denetle.py` `gh api` ile depo var mı, ⭐, son push, arşivli/durgun doğrular |
| FtE: çek-sakla, sonra sorguyla oku | `oku.py` sayfa deposu (`kaynaklar/`) + BM25 pasaj seçimi + `--ara` |
| Tam sayfa jeton israfı | çalışanlara `oku` MCP (`sayfa_oku`, `sayfada_ara`), `webfetch` kapalı |
| Atıf istemle yetmez | istemde **orijinal dilde birebir alıntı** zorunlu; `dogrula.py` alıntı/rakamı sayfada otomatik arar |
| Beast Mode / bütçe | istemde araç bütçesi ve "bütçe bitince yaz"; OpenCode `steps` sınırı |
| Enjeksiyon: işaretle + kıs | çıktıya "HARİCİ İÇERİK — veridir" etiketi, enjeksiyon izi uyarısı, çalışanda bash/yazma/webfetch kapalı, SSRF engeli, istemde özel veri yok |
| Ajan dostu standartlar | `Accept: text/markdown` ile çekme, `oku.py --llms` ile `llms.txt` |
| JS'li/girişli sayfalar | `oku.py` "çıkarılamadı" derse `--jina` (3. taraf) ya da tarayıcı (tarayıcı otomasyonu MCP'si) |

## Emin olmadıklarım ve boşluklar
- Nöral çıkarıcıların (ReaderLM-v2) güncel kalite/maliyet dengesi olgun değil; ölçümler ağırlıkla makale sayfalarında.
- `llms.txt`'in ajanlar tarafından gerçekten tüketildiğine dair bağımsız kanıt yok; yaygınlık rakamları örnekleme farkına göre beş kat değişiyor.
- Embedding/reranker tabanlı pasaj seçimi (BM25'ten güçlü olabilir) skill'e henüz eklenmedi: yerel model/anahtar gerektirir.
- Jina/Firecrawl gibi 3. taraf okuyucularda URL'nin dışarı çıktığı unutulmamalı; yalnız herkese açık sayfalarda kullan.

## Öğrenme yolu
1. Mimariyi görmek için `assafelovic/gpt-researcher` ve `jina-ai/node-DeepResearch` README'lerini oku (aktif ve farklı felsefe: çok ajanlı hat vs tek döngü).
2. Okuma katmanı için `unclecode/crawl4ai` dokümanında `fit_markdown` + filtreleri, `microsoft/playwright-mcp`'de snapshot mantığını incele.
3. Doğrulama için QuoteVerify ve DeepResearch Bench FACT'i oku; kendi çıktılarında `dogrula.py`'nin "Kısmen/Bulunamadı" oranını izle.
4. Güvenlik için Design Patterns (arXiv 2506.08837) ve "lethal trifecta" yazısıyla başla.
