# README fact-check: claims about external standards and tools

(Notes in the worker format that `dogrula.py` consumes. Internal claims — test counts, measured ratios — are covered by the test suites, not by this file.)

## External facts cited in README.md / README.tr.md

### Özet
Each finding below carries a verbatim quote and a URL; dogrula.py looks the quote up on the live page.

### Alıntılı bulgular
- robots.txt unreachable => complete disallow (README: fail-closed on 5xx / network errors) — "If the robots.txt file is unreachable due to server or network errors, this means the robots.txt file is undefined and the crawler MUST assume complete disallow." — [RFC 9309 §2.3.1.4](https://www.rfc-editor.org/rfc/rfc9309.html) (2022-09, birincil)
- robots.txt 4xx => allowed (README: 4xx means allowed) — "If a server status code indicates that the robots.txt file is unavailable to the crawler, then the crawler MAY access any resources on the server." — [RFC 9309 §2.3.1.3](https://www.rfc-editor.org/rfc/rfc9309.html) (2022-09, birincil)
- longest match wins (README: most specific rule wins) — "The most specific match found MUST be used. The most specific match is the match that has the most octets." — [RFC 9309 §2.2.2](https://www.rfc-editor.org/rfc/rfc9309.html) (2022-09, birincil)
- path matching starts at the first octet (README: prefix matching) — "The matching MUST start with the first octet of the path." — [RFC 9309 §2.2.2](https://www.rfc-editor.org/rfc/rfc9309.html) (2022-09, birincil)
- the shared (carrier-grade NAT) address range is blocked by the reader (README: CGNAT) — "The Shared Address Space address range is 100.64.0.0/10." — [RFC 6598](https://www.rfc-editor.org/rfc/rfc6598.html) (2012-04, birincil)
- BM25 is a ranking function (README: BM25 passage selection) — "In information retrieval, Okapi BM25 (BM is an abbreviation of best matching) is a ranking function used by search engines to estimate the relevance of documents to a given search query." — [Okapi BM25 — Wikipedia](https://en.wikipedia.org/wiki/Okapi_BM25) (2026-10, ikincil)
- DNS rebinding is an attack technique (README: connection pinning prevents it) — "DNS rebinding is a method of manipulating resolution of domain names that is commonly used as a form of computer attack." — [DNS rebinding — Wikipedia](https://en.wikipedia.org/wiki/DNS_rebinding) (2026-10, ikincil)
- llms.txt is a proposal for agent-readable site indexes (README: llms.txt support) — "A proposal to standardise on using an `/llms.txt` file to provide information to help agents use a website." — [llmstxt.org](https://llmstxt.org/) (2026-09, birincil)
- uv advertises a 10-100x speed claim (README: example verification table) — "10-100x faster than pip" — [uv README](https://github.com/astral-sh/uv) (2026-10, birincil)

### Çıkarımlar
- The robots.txt behaviour described in the README matches the cited RFC sections.

### Boşluklar
- —
