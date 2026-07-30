import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from src.parsers.parser_base import Parser  # L'importazione della tua architettura base

class MyMoviesParser(Parser):

    # --- COSTANTI E REGEX ---
    FILM_DETAIL_RE = re.compile(r"^/film/\d{4}/[^/]+$")
    PERSON_DETAIL_RE = re.compile(r"^/persone/[^/]+/\d+$")
    YEAR_LIST_RE = re.compile(r"^/(?:film|serietv)/\d{4}$")
    NEWS_DETAIL_RE = re.compile(r"^/cinemanews/\d{4}/\d+$")
    FILM_CAST_RE = re.compile(r"^/film/\d{4}/[^/]+/cast$")
    FILM_PUBLIC_RE = re.compile(r"^/film/\d{4}/[^/]+/pubblico$")
    BASE_GLYPHS_RE = r"[]+"
    TABLE_LINE_RE = r"^\|\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$"
    UI_MARKER_RE = r"\b(Condividi|VOTA|SCRIVI|PREFERITI|Recaptcha token|Accedi o registrati)\b"
    FORM_MARKER_RE = (
        r"(Inserisci qui la tua email|La tua preferenza .*registrata|Ti abbiamo .* email|"
        r"Convalida|Attenzione\. L'invio non è andato a buon fine|Chiudi|Riceverai un avviso)"
    )

    FILM_NAV = {
        "Scheda Home", "Scheda", "Cast", "News", "Critica", "Pubblico", "Premi",
        "Cinema", "Trailer", "Poster", "Foto", "Frasi", "Frasi Celebri", "Streaming",
        "PUBBLICO", "NEWS", "STAMPA", "PREMI", "MULTIMEDIA", "SHOWTIME"
    }

    PERSON_NAV = {
        "Scheda", "Biografia", "Filmografia", "Serie TV", "Articoli", "News",
        "Foto", "Video", "Premi", "Commenti", "Frasi", "Cinema", "Streaming"
    }

    SERIES_NAV = {
        "Home", "Serie TV", "News", "Recensioni", "Poster", "Foto", "Video",
        "Streaming", "Premi", "Cast", "Scheda", "Trama"
    }

    FILM_STOP_MARKERS = [
        r"Sei d'accordo con[\s\S]{0,100}?Tutti i film da\s*€?\s*1\s*al mese",
        r"Il tuo commento è stato registrato.",
        r"Tutti i film da\s*€?\s*1\s*al mese",
        r"(?m)^RECENSIONI DALLA PARTE DEL PUBBLICO$",
        r"(?m)^RECENSIONI DELLA CRITICA$",
        r"(?m)^Frasi$",
        r"(?m)^STAMPA$",
        r"(?m)^PUBBLICO$",
        r"(?m)^NEWS$",
        r"(?m)^PREMI$",
        r"(?m)^MULTIMEDIA$",
        r"(?m)^SHOWTIME$",
        r"(?m)^Quanto ti piace MYmovies\.it$",
        r"(?m)^Home \| Cinema \| Database \| Film",
        r"(?m)^Copyright©",
    ]

    PERSON_STOP_MARKERS = [
        r"Ultimi film",
        r"Prossimi film",
        r"Focus",
        r"News",
        r"I film più famosi",
    ]

    SERIES_STOP_MARKERS = [
        r"\* Film\b",
        r"\* Serie TV\b",
        r"\* Generi\b",
        r"\* Cinema\b",
        r"\* Film in\b",
        r"\* Questa settimana al cinema\b",
        r"\* Dalla scorsa settimana",
        r"\* Attesissimi\b",
        r"\* Appena aggiunti\b",
        r"\* Prossimamente\b",
        r"\* Box Office\b",
        r"\* Stasera in Tv\b",
        r"\* Ultime news\b",
        r"\* Argomenti\b",
        r"Home \| Cinema \| Database \| Film",
        r"Copyright©",
        r"chevron_left"
    ]   
    
    NEWS_STOP_MARKERS = [
        r"Tutti i film da\s*€?\s*1\s*al mese",
    ]
    
    FILM_CAST_STOP_MARKERS = [
        r"\n[^\n]*\|\s*Indice",
    ]
    
    FILM_PUBLIC_STOP_MARKERS = [
        r"pagina:\s*(?:\d+\s*)+»?"
    ]

    def __init__(self):
        super().__init__()
        # 1. Configurazione richiesta dalla tua architettura base
        self.use_magic: bool = True
        self.wait_until_type: str = "domcontentloaded" 
        self.delay_time: float = 1.0
        
        # 2. Configurazione derivata dal BaseParser dell'altro gruppo
        self.browser_cfg = BrowserConfig(headless=True)
        self._page_type = "generic"

    @property
    def domain(self) -> str:
        return "www.mymovies.it"


    # =========================================================================
    # METODI ASINCRONI (Riadattati per la mia architettura)
    # =========================================================================

    async def parser_url2(self, url: str, html_text: str) -> dict:
        """
        IL TUO ENTRY POINT PRINCIPALE.
        Sostituisce le vecchie chiamate, integrando il rilevamento del tipo di pagina 
        e l'estrazione statica del contenuto senza far ripartire Crawl4Ai.
        """
        self._page_type = self.detect_page_type(url)
        return self.extract_from_static_html(url, html_text)


    async def parse_html(self, url: str, html_text: str) -> dict:
        """
        Mantenuto per retrocompatibilità con l'altro gruppo.
        Redireziona la chiamata a extract_from_static_html, esattamente come parser_url2.
        """
        self._page_type = self.detect_page_type(url)
        return self.extract_from_static_html(url, html_text)


    async def parse(self, url: str) -> dict:
        """
        Mantenuto integro dall'originale BaseParser.
        Gestisce il parsing scaricando i dati attivamente con Crawl4Ai nel caso venga chiamato.
        """
        self._page_type = self.detect_page_type(url)
        domain = urlparse(url).netloc
        
        specific_cfg = self.get_crawler_config()
        full_html_cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
        
        async with AsyncWebCrawler(config=self.browser_cfg) as crawler:
            full_result = await crawler.arun(url=url, config=full_html_cfg)
            parsed_result = await crawler.arun(url=url, config=specific_cfg)
        
        if not parsed_result.success:
            raise RuntimeError(f"Parsing fallito per {url}: {parsed_result.error_message}")

        title = ""
        if hasattr(full_result, "metadata") and full_result.metadata:
            title = full_result.metadata.get("title", "") or ""
            
        if not title and hasattr(full_result, "html") and full_result.html:
            match = re.search(r'<title[^>]*>(.*?)</title>', full_result.html, re.IGNORECASE | re.DOTALL)
            if match:
                title = match.group(1).strip()
                
        if not title:
            last_segment = urlparse(url).path.split('/')[-1]
            title = last_segment.replace('_', ' ').replace('.html', '').replace('.php', '')

        title = self.clean_title(title)
        full_html_text = full_result.html if hasattr(full_result, "html") and full_result.html else ""
        raw_markdown = parsed_result.markdown if hasattr(parsed_result, "markdown") and parsed_result.markdown else ""
        parsed_html = parsed_result.html if hasattr(parsed_result, "html") and parsed_result.html else ""

        raw_source = parsed_html if getattr(self, "_page_type", "") == "news_detail" else (
            full_html_text if getattr(self, "_page_type", "") in {"series_year","film_public", "film_cast"} else raw_markdown
        )
        parsed_text = self.clean_text(raw_source)
        
        return {
            "url": url,
            "domain": domain,
            "title": title,
            "html_text": full_html_text,
            "parsed_text": parsed_text
        }


    # =========================================================================
    # METODI DI GESTIONE HTML E LOGICA CENTRALE 
    # =========================================================================

    def extract_from_static_html(self, url: str, html_text: str) -> dict:
        """
        Estrae testo da HTML usando configurazione del parser specifico
        e clean_text() del parser specifico.
        """
        domain = urlparse(url).netloc
        title = self._extract_title_from_html(url, html_text)
        page_type = getattr(self, "_page_type", "generic")

        if page_type in {"series_year", "news_detail", "film_cast", "film_public"}:
            raw_source = html_text
        else:
            soup = self._build_static_soup_from_config(html_text)
            raw_source = self._html_to_markdown_like_text(soup)
        
        parsed_text = self.clean_text(raw_source)

        return {
            "url": url,
            "domain": domain,
            "title": title,
            "html_text": html_text,
            "parsed_text": parsed_text
        }

    def _extract_title_from_html(self, url: str, html_text: str) -> str:
        title = ""
        match = re.search(r'<title[^>]*>(.*?)</title>', html_text, re.IGNORECASE | re.DOTALL)
        if match:
            title = match.group(1).strip()
        if not title:
            last_segment = urlparse(url).path.split("/")[-1]
            title = last_segment.replace("_", " ").replace(".html", "").replace(".php", "")
        return self.clean_title(title)

    def _build_static_soup_from_config(self, html_text: str) -> BeautifulSoup:
        cfg = self.get_crawler_config()
        css_selector = self._get_static_config_value(cfg, "css_selector", None)
        excluded_selector = self._get_static_config_value(cfg, "excluded_selector", None)
        excluded_tags = self._get_static_config_value(cfg, "excluded_tags", None)

        soup = BeautifulSoup(html_text, "html.parser")

        if excluded_tags:
            for tag in soup(excluded_tags):
                tag.decompose()
        if excluded_selector:
            try:
                for el in soup.select(excluded_selector):
                    el.decompose()
            except Exception:
                pass
        if css_selector:
            try:
                selected = soup.select(css_selector)
                if selected:
                    selected_html = "\n".join(str(el) for el in selected)
                    soup = BeautifulSoup(selected_html, "html.parser")
            except Exception:
                pass
        return soup

    def _html_to_markdown_like_text(self, soup: BeautifulSoup) -> str:
        for tag in soup(["script", "style", "noscript", "svg", "iframe", "form", "button", "input", "textarea", "select"]):
            tag.decompose()
        for img in soup.find_all("img"):
            img.decompose()
        for a in soup.find_all("a"):
            a.replace_with(a.get_text(" ", strip=True))
        for level in range(1, 7):
            for h in soup.find_all(f"h{level}"):
                heading_text = h.get_text(" ", strip=True)
                if heading_text:
                    h.string = "\n" + ("#" * level) + " " + heading_text + "\n"
        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        return text.strip()

    def _get_static_config_value(self, cfg, name: str, default=None):
        return getattr(cfg, name, default)

    def clean_title(self, title: str) -> str:
        return title.strip()


    # =========================================================================
    # LOGICA DI ROUTING, SELETTORI E PULIZIA 
    # =========================================================================

    def get_crawler_config(self) -> CrawlerRunConfig:
        return CrawlerRunConfig(
            excluded_tags=["table", "svg", "form", "button", "input", "textarea", "iframe", "noscript","select" ],
            cache_mode=CacheMode.BYPASS,
            excluded_selector="div.mm-hide-xs, .pulsante-span-bgfree, .mm-wide-lista-colonne, .mm-white.mm-padding-ver-16.mm-padding-hor-8.stonda6.mm-center, .mm-padding-8.mm-col.md-4.sm-12, .col-mm.xs-12.mm-white.mm-padding-8, .mm-white.mm-hover-pink.stonda3, .mm-white.stonda6.mm-btn.mm-btn-head.mm-aqua, .btn-group, .dropdown-menu ,.io-article-footer, .mm-col.xs-12.mm-white.mm-left.mm-padding-12"
        )

    def detect_page_type(self, url: str) -> str:
        path = urlparse(url).path.lower().rstrip("/")
        if self.FILM_DETAIL_RE.match(path):
            return "film_detail"
        if self.PERSON_DETAIL_RE.match(path):
            return "person_detail"
        if self.YEAR_LIST_RE.match(path):
            return "series_year"
        if self.FILM_CAST_RE.match(path):
            return "film_cast"
        if self.NEWS_DETAIL_RE.match(path):
            return "news_detail"
        if self.FILM_PUBLIC_RE.match(path):
            return "film_public"
        return "generic"

    def clean_text(self, text: str) -> str:
        page_type = getattr(self, "_page_type", "generic")
        if page_type == "film_detail":
            return self.clean_film_text(text)
        if page_type == "person_detail":
            return self.clean_person_text(text)
        if page_type == "series_year":
            return self.clean_series_text(text)
        if page_type == "news_detail":
            return self.clean_news_text(text)
        if page_type == "film_cast":
            return self.clean_film_cast_text(text)
        if page_type == "film_public":
            return self.clean_film_public_text(text)
        return self.clean_generic_text(text)

    def _normalize_base(self, text: str) -> str:
        text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"\{\{[^}]+\}\}", "", text)
        text = re.sub(self.BASE_GLYPHS_RE, "", text)
        text = re.sub(r"[ \t\f\v]+", " ", text)
        m = re.search(r"(?m)^#\s+.+$", text)
        return text[m.start():] if m else text

    def _filter_lines(self, text: str, nav: set[str], meta_max_len: int) -> str:
        out, title_seen, removed_meta = [], False, False
        for line in text.split("\n"):
            s = line.strip()
            if (s.startswith("|") and s.endswith("|")) or re.match(self.TABLE_LINE_RE, s): continue
            if s in nav: continue
            if re.search(self.UI_MARKER_RE, s, re.I): continue
            if re.search(self.FORM_MARKER_RE, s, re.I): continue
            if re.fullmatch(r"\d{1,4}", s) or re.fullmatch(r"[\|\s_]+", s): continue
            if re.fullmatch(r"[]+", s): continue
            if s.startswith("# "):
                title_seen = True
                out.append(line)
                continue
            if title_seen and not removed_meta:
                removed_meta = True
                if "|" in s and len(s) <= meta_max_len:
                    continue
            out.append(line)
        return "\n".join(out)

    def _apply_stop_markers(self, text: str, stop_markers: list[str], flags: int) -> str:
        cuts = [m.start() for p in stop_markers if (m := re.search(p, text, flags))]
        return text[:min(cuts)] if cuts else text

    def _strip_markdown_emphasis(self, text: str) -> str:
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"__(.*?)__", r"\1", text)
        text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", text)
        return re.sub(r"(?<!\w)(?:__|\*\*)(?!\w)", "", text)

    def _final_cleanup(self, text: str) -> str:
        text = re.sub(r"(?m)^[\s\-\|_.,:;!]+$", "", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        return text.strip() 

    def clean_film_text(self, text: str) -> str:
        text = self._normalize_base(text)
        text = self._filter_lines(text, self.FILM_NAV, meta_max_len=80)
        text = re.sub(r"\bDa vedere\s+\d{4}\b", "", text, flags=re.I)
        text = re.sub(r"\bCast completo\b", "", text, flags=re.I)
        text = re.sub(r"\bMYmo\s+netro\b", "MYmonetro", text, flags=re.I)
        text = re.sub(r"(?im)^Ultimo aggiornamento .+\n?", "", text)
        text = self._apply_stop_markers(text, self.FILM_STOP_MARKERS, re.S)
        text = self._strip_markdown_emphasis(text)
        return self._final_cleanup(text)

    def clean_person_text(self, text: str) -> str:
        text = self._normalize_base(text)
        text = self._filter_lines(text, self.PERSON_NAV, meta_max_len=100)
        text = self._apply_stop_markers(text, self.PERSON_STOP_MARKERS, re.I | re.M)
        text = self._strip_markdown_emphasis(text)
        return self._final_cleanup(text)
    
    def clean_series_text(self, text: str) -> str:
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "svg", "noscript", "iframe", "form", "button", "input", "textarea"]):
            tag.decompose()
        for h1 in soup.find_all("h1"):
            h1.string = "# " + h1.get_text(strip=True)
        selectors = [
            "div.mm-hide-xs", ".pulsante-span-bgfree", ".mm-wide-lista-colonne",
            ".mm-white.mm-padding-ver-16.mm-padding-hor-8.stonda6.mm-center",
            ".mm-padding-8.mm-col.md-4.sm-12", ".col-mm.xs-12.mm-white.mm-padding-8",
            ".mm-white.mm-hover-pink.stonda3", ".mm-white.stonda6.mm-btn.mm-btn-head.mm-aqua",
            ".mm-padding-8.mm-col.md-12", ".mm-col.xs-12.mm-white.mm-left.mm-padding-12",
            ".mm-padding-8.mm-col.md-4.sm-6", ".stonda6.mm-btn.mm-btn-head.mm-aqua",
            ".menu-link-rapidi", ".accordion", ".mm-padding-4.mm-pointer.mm-pink.stonda3",
            ".mm-red.mm-padding-4.stonda6.mm-small", ".mm-show-sm.mm-show-md.link-bianco",
            ".mmo-slider", ".search-container",
        ]
        for sel in selectors:
            for el in soup.select(sel):
                el.decompose()
        for el in soup.select('div[id^="trama"]'):
            classes = el.get("class", [])
            el["class"] = [c for c in classes if c != "hidden"]
        if soup.title:
            soup.title.decompose()
        
        text = soup.get_text(" ", strip=False)
        text = self._normalize_base(text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = re.sub(r"ordina per:\s*Filtri attivi:\s*", "", text, flags=re.I)
        text = re.sub(r"Recensione\s*❯", "", text, flags=re.I)
        text = re.sub(r"(Recensione|Cast)(\s*\|\s*(Recensione|Cast|Rassegna stampa|Pubblico|Forum))*","",text,flags=re.I)
        text = re.sub(r"Rassegna stampa\s*\|?", "", text, flags=re.I)
        text = re.sub(r"[▽❯]+", "", text)
        text = re.sub(r"Espandi", "", text)
        text = re.sub(r"Parte del gruppo\s*e", "", text)
        text = re.sub(r"Powered by\s*JustWatch", "", text, flags=re.IGNORECASE)
        text = self._apply_stop_markers(text, self.SERIES_STOP_MARKERS, re.I)
        text = self._strip_markdown_emphasis(text)
        return self._final_cleanup(text)    

    def clean_news_text(self, text: str) -> str:
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "svg", "noscript", "iframe", "form", "button", "input", "textarea" ,"select"]):
            tag.decompose()
        if soup.title:
            soup.title.decompose()
        for h1 in soup.find_all("h1"):
            h1.string = "# " + h1.get_text(strip=True)
        selectors = [
            ".btn.main_menu", ".dropdown-menu", ".hidden-sm",
            ".hidden-lg.visible-xs", ".btn.btn-info.btn-sm", ".search-container",
        ]
        for sel in selectors:
            for el in soup.select(sel):
                el.decompose()
        text = soup.get_text(" ", strip=False)
        text = self._normalize_base(text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = re.sub(r"Parte del gruppo\s*e", "", text, flags=re.IGNORECASE)
        text = self._apply_stop_markers(text, self.NEWS_STOP_MARKERS, re.I | re.S)
        text = self._strip_markdown_emphasis(text)
        return self._final_cleanup(text)
    
    def clean_film_cast_text(self , text: str) -> str:
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "svg", "noscript", "iframe", "form", "button", "input", "textarea" ,"select"]):
            tag.decompose()
        if soup.title:
            soup.title.decompose()
        for h1 in soup.find_all("h1"):
            h1.string = "# " + h1.get_text(strip=True)
        selectors = [
            ".menu_head_link", ".menu_head_tit", ".linknolinkrosa",
            ".rec_link_disattivo", ".navigazione",
        ]
        for sel in selectors:
            for el in soup.select(sel):
                el.decompose()
        text = soup.get_text(" ", strip=False)
        text = self._normalize_base(text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = re.sub(r"M\s*Y\s*M\s*O\s*N\s*E\s*T\s*R\s*O", "MYMONETRO", text, flags=re.I)
        text = re.sub(r"Parte del gruppo\s*e", "", text)
        text = re.sub(r"\s*dizionari\s+critica\s+pubblico\b", "", text, flags=re.I)
        text = re.sub(r"(?im)^.*ricerca(?:&nbsp;|\s)+avanzata.*\n?", "", text)
        text = self._apply_stop_markers(text, self.FILM_CAST_STOP_MARKERS, re.I | re.S)
        text = self._strip_markdown_emphasis(text)
        return self._final_cleanup(text) 

    def clean_film_public_text(self, text: str) -> str:
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style", "svg", "noscript", "iframe", "form", "button", "input", "textarea" ,"select"]):
            tag.decompose()
        if soup.title:
            soup.title.decompose()
        selectors = [
            ".menu_head_link", ".menu_head_tit",
            ".rec_link_disattivo", ".rec_link_attivo",
        ]
        for sel in selectors:
            for el in soup.select(sel):
                el.decompose()
        for h1 in soup.find_all("h1"):
            h1.string = "# " + h1.get_text(strip=True)
        for el in soup.find_all(id=re.compile(r"^daccordo(si|no)\d+$")): el.decompose()
        for el in soup.find_all(id=re.compile(r"^apriform\d+$")): el.decompose()
        for el in soup.find_all(id=re.compile(r"^chiudiform\d+$")): el.decompose()
        for el in soup.find_all(id=re.compile(r"^parziale\d+$")):
            if "[+]" in el.get_text(): el.decompose()
        for el in soup.find_all(id=re.compile(r"^apriutente\d+$")): el.decompose()
        for el in soup.select(".linknolinkrosa"): el.decompose()
        
        text = soup.get_text(" ", strip=False)
        text = self._normalize_base(text)
        text = self._apply_stop_markers(text, self.FILM_PUBLIC_STOP_MARKERS, re.I | re.S)
        text = re.sub(r"(?im)^.*ricerca(?:&nbsp;|\s)+avanzata.*\n?", "", text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = text.replace("d'accordo?", " ")
        text = text.replace("[-]", " ")
        text = re.sub(r"Home\s*»\s*film\s*»\s*\d{4}\s*»\s*.*?\s*»\s*pubblico","",text,flags=re.I | re.S)
        text = self._strip_markdown_emphasis(text)
        return self._final_cleanup(text)
    
    def clean_generic_text(self, text: str) -> str:
        text = self._normalize_base(text)
        text = self._strip_markdown_emphasis(text)
        return self._final_cleanup(text)