import re
from urllib.parse import urlparse
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from src.parsers.parser_base import Parser  # L'importazione della tua architettura base

class ImdbParser(Parser):
    """
    Parser specializzato per il dominio www.imdb.com compatibile con la ParserFactory.
    Unisce la logica di ParserBase e ImdbParser dell'altro gruppo, 
    adattando l'estrazione statica al metodo asincrono parser_url2 richiesto dalla tua architettura.
    """

    def __init__(self) -> None:
        super().__init__()
        # Configurazione richiesta dalla tua architettura base
        self.use_magic = True
        self.wait_until_type = "domcontentloaded"
        self.delay_time = 12.0  # Mantenuto in coerenza con il delay_before_return_html originale

        # --- Configurazioni originali dell'altro gruppo ---
        # Abilitiamo JS per garantire il rendering di pagine dinamiche
        self.browser_cfg = BrowserConfig(headless=True, java_script_enabled=True)

        self.crawler_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            stream=False,
            exclude_external_images=True,
            exclude_social_media_links=True,
            exclude_internal_links=True,
            exclude_external_links=True,
            process_iframes=False,
            remove_overlay_elements=True,
            word_count_threshold=5,
            magic=True,
            wait_for="main.ipc-page-wrapper, [data-testid='Storyline']",
            delay_before_return_html=12.0,
        )

        # Script JS personalizzato per scorrere progressivamente la pagina
        scroll_and_click_js = """
            const scrollInterval = setInterval(() => {
                window.scrollBy(0, 500);
            }, 200);
            const loadMoreInterval = setInterval(() => {
                let loadMoreBtn = document.querySelector('.ipc-see-more__button');
                if (loadMoreBtn) {
                    loadMoreBtn.click();
                }
            }, 1000);
            setTimeout(() => {
                clearInterval(scrollInterval);
                clearInterval(loadMoreInterval);
            }, 10000);
            """
        self.crawler_cfg.js_code = [scroll_and_click_js]

        self.crawler_cfg.excluded_selector = (
            "button, .ipc-btn, .ipc-icon, img, alt, svg, [data-testid^='hero-rating-bar'], "
            ".ipc-lockup-overlay, [data-testid='hero-subnav-bar-left-drawer'], "
            "[data-testid*='shoveler']:not([data-testid*='cast']), #morelikethis, #relatedinterests, "
            ".ipc-ad, figcaption, [class*='icon-link'], [class^='ipc-responsive'], "
            "[data-testid='videos-section'], [data-testid='tm-box-woc-text'], "
            "[data-testid^='Photos'], [data-testid='rating-histogram'], "
            "[data-testid='UserReviews'], [data-testid='MoreLikeThis'], "
            "[data-testid='RelatedInterests'], "
            "[data-test-id*='right-rail'], [data-testid='contribution'], "
            "[class*='recently-viewed-items'], [class^='imdb-footer'], "
            "[data-testid^='top-picks'], .ipc-simple-select__container, "
            "[data-testid='more-from-section'], [class*='pro-upsell__link'], "
            "[class='ipc-image'], [class^='ipc-boolean'], .ipc-voting, "
            "[data-testid='reviews-author'], [data-testid='plot-xs_to_m'], "
            "[class*='ipc-html-content-button'], [data-testid*='read-all'], "
            "[class='ipc-chip-list__scroller'], [data-testid='hero-subnav-bar'], "
            ".sponsored_label, .nas-slot, [data-testid^='adv-slot'], "
            "#imdbHeader, .imdb-header, [data-testid='consent-banner'], #consent-banner"
        )

        # Configurazione lite per il parse da HTML statico
        self.crawler_cfg_local = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            stream=False,
            exclude_external_images=True,
            exclude_social_media_links=True,
            exclude_internal_links=True,
            exclude_external_links=True,
            process_iframes=False,
            remove_overlay_elements=True,
            word_count_threshold=5,
        )
        self.crawler_cfg_local.excluded_selector = self.crawler_cfg.excluded_selector


    @property
    def domain(self) -> str:
        return "www.imdb.com"


    # =========================================================================
    # ENTRYPOINT ASYNC RISCRITTI PER LA MIA ARCHITETTURA
    # =========================================================================

    async def parser_url2(self, url: str, html_text: str) -> dict:
        """
        Metodo principale richiesto dalla tua interfaccia Parser.
        Utilizza il prefisso 'raw:' per far generare il markdown a Crawl4AI 
        direttamente a partire dall'HTML statico iniettando i selettori di esclusione.
        """
        if not self.is_valid(url):
            return {
                "url": url,
                "domain": self.domain,
                "title": "URL Non Valido",
                "html_text": html_text,
                "parsed_text": ""
            }

        dominio = urlparse(url).netloc or self.domain

        # Esecuzione statica locale con Crawl4AI
        async with AsyncWebCrawler(config=self.browser_cfg) as crawler:
            raw_url = f"raw:{html_text}"
            result = await crawler.arun(url=raw_url, config=self.crawler_cfg_local)

        if not result.success:
            raise RuntimeError(
                f"Errore nel parsing statico dell'URL {url}: {result.error_message}"
            )

        markdown_text = result.markdown or ""
        testo_pulito = self.clean_text(markdown_text)
        titolo = self.trova_titolo(markdown_text)

        return {
            "url": url,
            "domain": dominio,
            "title": titolo,
            "html_text": html_text,
            "parsed_text": testo_pulito
        }


    async def parse(self, url: str) -> dict:
        """
        Mantengo la logica di estrazione "live" (con download dalla rete) nel caso
        la tua pipeline la richiami in assenza di HTML statico pre-scaricato.
        """
        if not self.is_valid(url):
            raise ValueError(f"URL non processabile (es. home page): {url}")

        dominio = urlparse(url).netloc
        async with AsyncWebCrawler(config=self.browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=self.crawler_cfg)

        if not result.success:
            raise RuntimeError(
                f"Errore nel parsing dell'URL {url}: {result.error_message}"
            )

        testo_pulito = self.clean_text(result.markdown)
        titolo = self.trova_titolo(result.markdown)

        return {
            "url": url,
            "domain": dominio,
            "title": titolo,
            "html_text": result.html,
            "parsed_text": testo_pulito,
        }


    # =========================================================================
    # LOGICA ORIGINALE DI PULIZIA MANTENUTA INTONSA
    # =========================================================================

    def trova_titolo(self, text: str) -> str:
        """
        Estrae il titolo o costruisce un titolo composito.
        """
        righe = text.split("\n")
        titoli = [riga.strip("# ").strip() for riga in righe if riga.startswith("#")]

        if not titoli:
            return "Senza Titolo"

        parole_generiche = [
            "biografia", "biography", "filmografia", "storia",
            "interpreti e troupe", "full cast & crew", "cast",
            "trama", "plot", "curiosità", "trivia",
            "domande frequenti", "recensioni degli utenti",
            "goofs", "gaffe", "parents guide",
            "guida ai genitori", "quotes", "citazioni",
            "premi", "awards",
        ]

        # Se il primo titolo è un titolo generico di sezione, lo combina.
        primo_titolo = titoli[0].lower()
        if any(p in primo_titolo for p in parole_generiche) and len(titoli) > 1:
            return f"{titoli[1]} - {titoli[0]}"

        return titoli[0]

    def clean_text(self, text: str) -> str:
        """
        Pulisce il testo markdown estratto dalle pagine IMDb.
        """
        if not text:
            return ""

        # AGGIUNTA: Rimuove la sintassi dei link Markdown mantenendo solo il testo visibile
        # Trasforma "[Paul Thomas Anderson](/name/nm0000759...)" in "Paul Thomas Anderson"
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

        righe = text.split("\n")
        righe_pulite = []

        stop_sections = [
            "### foto", "### photos", "### video", "### videos",
            "### altre pagine da esplorare", "### more to explore",
            "### visti di recente", "### recently viewed",
            "### i più visti", "### most popular",
            "select your preferences",
        ]

        skip_exact_lines = ["SPONSORED", "IMDbPro"]

        for riga in righe:
            r = riga.strip()
            if not r:
                continue

            if r in skip_exact_lines:
                continue

            if any(r.lower().startswith(s) for s in stop_sections):
                break

            # De-duplicazione
            r_confronto = r.replace("*", "").strip().lower()
            if righe_pulite:
                ultima_confronto = righe_pulite[-1].replace("*", "").strip().lower()
                if r_confronto == ultima_confronto:
                    continue

            righe_pulite.append(r)

        return "\n".join(righe_pulite).strip()

    def is_valid(self, url: str) -> bool:
        """
        Verifica che l'URL sia processabile.
        """
        if "tt_nv_home" in url.lower():
            return False
        return True