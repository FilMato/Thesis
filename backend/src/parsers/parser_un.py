from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, CacheMode, BrowserConfig, CrawlerRunConfig
import re
from parsers.parser_base import Parser


#liste definite a priori per evitare che vengano istanziate ogni volta che l'oggetto viene creato
_CSS_SELECTORS = [
    ".body-article",
    ".radix-layouts-content",
    ".post-content",
    ".field-name-body",
    ".main-container.container",
    "#main-content",
    "#content",
    "#main"
]

_EXCLUDED_TAGS = ['title',
                  'nav',
                  'header',
                  'footer',
                  'button',
                  'video']

_EXCLUDED_SELECTOR = (
    ".img, .breadcrumb, #sidebar, .skip-link, .screen-reader-text, .home-footer, "
    ".node-sidebar, .views-field-field-news-tags, .block-content-footer, "
    ".type-entermedia_image, #player-gui, #addtoany, #sharing_widget, #skip-link, "
    ".image-caption, #sharing-widget, #breadcrumbs, #more_button, .photo-credit, "
    ".page-header, .fusion-video, #player-controls, .wp-caption-text, "
    # contenitori di footer/menu/lingua che su molti sotto-siti un.org (Drupal, temi diversi)
    # non sono dentro tag semantici <footer>/<nav> e quindi escluded_tags non li rimuove
    "#footer, .footer, .region-footer, footer, .site-footer, "
    ".language-switcher, .language-switcher-locale-url, #block-locale-language, "
    ".navbar, .region-navigation, .main-menu, .menu--main, "
    "#block-superfish-1, .superfish, .toggle-navigation"
)

_MIN_LENGTH = 50

# Intestazioni markdown che segnalano l'inizio di moduli "cross-promo" tipici
# delle pagine un.org (caroselli "Read more", "Learn more", footer tematici di sezione),
# spesso annidati nello stesso contenitore dell'articolo e quindi non filtrabili
# dai soli CSS selector. Quando il parser ne incontra una in un titolo, tronca
# l'output lì: tutto quello che segue non fa parte dell'articolo vero e proprio.
_BOILERPLATE_HEADING_PATTERNS = [
    r'read more',
    r'learn more\b',
    r'facts and figures',
    r'related content',
    r'related news',
    r'newsletter',
    # mega-menu/footer di sezione, tipici del tema bootstrap_un2 di un.org/en/...
    # (compaiono come heading dentro lo stesso contenitore dell'articolo)
    r'main bodies',
    r'departments\s*/?\s*offices',
    r'resources\s*/?\s*services',
    r'key documents',
    r'news and media',
    r'issues\s*/?\s*campaigns',
    r'donate',
    r'follow us',
    r'social media',
    r'site index',
    r'a-z site index',
    # heading di sezioni "cross-promo" a metà pagina su alcuni template un.org
    # (es. youth-in-action): rubriche di rimando con prosa vera, non un link-dump,
    # quindi non rilevabili dagli altri segnali; il gold standard le esclude comunque
    r'voices and stories',
    r'things you can do',
    r'youth climate action summit',
]
_BOILERPLATE_HEADING_RE = re.compile(
    r'^#{1,6}\s*(' + '|'.join(_BOILERPLATE_HEADING_PATTERNS) + r')',
    re.IGNORECASE,
)

# heading generico (qualsiasi livello #...######), usato per spezzare il markdown in blocchi
_HEADING_RE = re.compile(r'^(#{1,6})\s*(.*)$')
# voce di elenco che e' interamente un link (es. "* [Testo](url)"), tipica dei moduli
# "Documents"/"Useful links" a fondo pagina su un.org
_LINK_BULLET_RE = re.compile(r'^[*\-]\s*\[.+?\]\(.+?\).*$')
# heading il cui intero testo e' un link (card promozionali tipo "### [UN and Outer Space](url)")
_LINK_ONLY_HEADING_RE = re.compile(r'^\[.+?\]\(.+?\)$')


def _normalize_title(page_title: str) -> str:
    # rimuove i suffissi tipici del tag <title> (" | United Nations", " - United Nations", ecc.)
    cleaned = re.split(r'\s*[|\-–]\s*united nations\b', page_title, flags=re.IGNORECASE)[0]
    return cleaned.strip().lower()


def _is_link_dump(body_lines: list[str]) -> bool:
    # vero se il blocco e' fatto quasi solo di righe-elenco che sono interamente un link
    # (caso "### Documents" / "### Useful links": nessun contenuto editoriale, solo riferimenti)
    stripped = [l.strip() for l in body_lines if l.strip()]
    if not stripped:
        return False
    link_lines = sum(1 for l in stripped if _LINK_BULLET_RE.match(l))
    return (link_lines / len(stripped)) >= 0.7


def _split_blocks(lines: list[str]):
    # spezza il markdown in blocchi (heading, testo_heading, corpo) per analizzare la coda del documento
    heading_idxs = [i for i, l in enumerate(lines) if _HEADING_RE.match(l.strip())]
    blocks = []
    for n, hi in enumerate(heading_idxs):
        body_start = hi + 1
        body_end = heading_idxs[n + 1] if n + 1 < len(heading_idxs) else len(lines)
        heading_text = _HEADING_RE.match(lines[hi].strip()).group(2)
        blocks.append((hi, heading_text, body_start, body_end))
    return blocks


def _truncate_boilerplate(text: str, page_title: str = "") -> str:
    lines = text.split('\n')
    normalized_title = _normalize_title(page_title) if page_title else ""

    # --- passata 1 (in avanti): heading con parole chiave fisse + heading che ripete il titolo ---
    idx_forward = len(lines)
    seen_title_heading = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if _BOILERPLATE_HEADING_RE.match(stripped):
            idx_forward = i
            break

        # Su molte pagine un.org (es. UDHR), subito dopo la fine dell'articolo vero
        # compare un blocco "Related/Resources" il cui heading ripete pari pari il
        # titolo della pagina. La prima occorrenza e' l'H1 legittimo, si tronca solo
        # dalla seconda occorrenza in poi.
        if normalized_title:
            heading_match = _HEADING_RE.match(stripped)
            if heading_match:
                heading_text = re.sub(r'[*_]', '', heading_match.group(2)).strip().lower()
                heading_text_clean = re.sub(r'\s*\([^)]*\)\s*$', '', heading_text).strip()
                if heading_text_clean == normalized_title or heading_text == normalized_title:
                    if seen_title_heading:
                        idx_forward = i
                        break
                    seen_title_heading = True

    # --- passata 2 (a ritroso): coda di blocchi "non editoriali" a fondo pagina ---
    # Molte pagine un.org terminano con una sequenza di card di rimando (heading stesso
    # e' un link, es. "### [UN and Outer Space](url)"), liste di soli link ("Documents",
    # "Useful links") ed heading vuoti che le introducono. Si risale dalla fine finche'
    # questi pattern si confermano consecutivamente; al primo blocco con contenuto
    # editoriale vero ci si ferma, lasciando intatto tutto cio' che lo precede.
    blocks = _split_blocks(lines)
    idx_backward = len(lines)
    still_in_trailing_run = True
    for heading_idx, heading_text, body_start, body_end in reversed(blocks):
        body_lines = lines[body_start:body_end]
        has_body = bool([l for l in body_lines if l.strip()])
        cleaned_heading = re.sub(r'[*_]', '', heading_text).strip()

        is_boilerplate_block = (
            _is_link_dump(body_lines)
            or _BOILERPLATE_HEADING_RE.match(lines[heading_idx].strip())
            or bool(_LINK_ONLY_HEADING_RE.match(cleaned_heading))
        )

        if is_boilerplate_block or (not has_body and still_in_trailing_run):
            idx_backward = heading_idx
            still_in_trailing_run = True
        else:
            still_in_trailing_run = False
            break

    final_idx = min(idx_forward, idx_backward)
    return '\n'.join(lines[:final_idx]).strip()


def _clean_output(text: str, page_title: str = "") -> str:
    text = re.sub(r'\[\]\([^)]+\)', '', text)  # pulizia dei link vuoti
    text = _truncate_boilerplate(text, page_title)  # rimozione moduli cross-promo a fine pagina
    return text


class Parser_UN(Parser):

    def __init__(self):
        super().__init__()
        self.use_magic: bool = False
        self.wait_until_type: str = "domcontentloaded"
        self.delay_time: float = 1.0

    @property
    def domain(self):
        return "www.un.org"

    async def parser_url2(self, url: str, html_text: str) -> dict[str, str]:  # input url, output json obj
        print("RUNNING UN PARSER [fix-v4: mid-page-crosspromo-keywords]\n")
        browser_cfg = BrowserConfig(headless=True)
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            title_tag = soup.select_one("title")
            title = title_tag.text.strip() if title_tag else "Errore nel trovare il titolo"
        except Exception as e:
            print(f"Estrazione titolo fallita per {url}: {e}")
            title = "Errore nel trovare il titolo"

        no_selector_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            exclude_all_images=True,
            exclude_social_media_links=True,
            excluded_tags=_EXCLUDED_TAGS,
            excluded_selector=_EXCLUDED_SELECTOR
        )

        async with AsyncWebCrawler(config=browser_cfg) as crawler:

            # --- TENTATIVO 1: selettori CSS sull'HTML grezzo salvato (DB / gold standard) ---
            for selector in _CSS_SELECTORS:
                selector_cfg = CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    css_selector=selector,
                    exclude_all_images=True,
                    exclude_social_media_links=True,
                    excluded_tags=_EXCLUDED_TAGS,
                    excluded_selector=_EXCLUDED_SELECTOR
                )
                try:
                    result = await crawler.arun(url=f'raw:{html_text}', config=selector_cfg)
                except Exception as e:
                    print(f"Selettore '{selector}' fallito: {e}")
                    continue
                print(result.success, repr(result.markdown), result.error_message)
                result_markdown = _clean_output(result.markdown, title) if result.markdown else ""
                if result.success and result_markdown and len(result_markdown.strip()) > _MIN_LENGTH:
                    return {
                        "url": url,
                        "domain": self.domain,
                        "title": title,
                        "parsed_text": result_markdown,
                        "html_text": result.html or ""
                    }

            # --- TENTATIVO 2: nessun selettore, parsing completo dell'HTML grezzo salvato ---
            try:
                result = await crawler.arun(url=f'raw:{html_text}', config=no_selector_cfg)
            except Exception as e:
                print(f"Parsing senza selettore fallito: {e}")
                result = None
            if result is not None:
                print(result.success, repr(result.markdown), result.error_message)
                result_markdown = _clean_output(result.markdown, title) if result.markdown else ""
                if result.success and result_markdown and len(result_markdown.strip()) > _MIN_LENGTH:
                    return {
                        "url": url,
                        "domain": self.domain,
                        "title": title,
                        "parsed_text": result_markdown,
                        "html_text": result.html or ""
                    }

            # --- FALLBACK FINALE: l'HTML salvato non contiene il contenuto reale (es. dominio JS-rendered) ---
            live_cfg = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                exclude_all_images=True,
                exclude_social_media_links=True,
                excluded_tags=_EXCLUDED_TAGS,
                excluded_selector=_EXCLUDED_SELECTOR,
                wait_until="domcontentloaded"
            )
            try:
                live_result = await crawler.arun(url=url, config=live_cfg)
            except Exception as e:
                print(f"Fetch live fallito per {url}: {e}")
                live_result = None

            if live_result is not None and live_result.success and live_result.html:
                rendered_html = live_result.html

                for selector in _CSS_SELECTORS:
                    selector_cfg = CrawlerRunConfig(
                        cache_mode=CacheMode.BYPASS,
                        css_selector=selector,
                        exclude_all_images=True,
                        exclude_social_media_links=True,
                        excluded_tags=_EXCLUDED_TAGS,
                        excluded_selector=_EXCLUDED_SELECTOR
                    )
                    try:
                        result = await crawler.arun(url=f'raw:{rendered_html}', config=selector_cfg)
                    except Exception as e:
                        print(f"Selettore '{selector}' fallito sull'HTML live: {e}")
                        continue
                    result_markdown = _clean_output(result.markdown, title) if result.markdown else ""
                    if result.success and result_markdown and len(result_markdown.strip()) > _MIN_LENGTH:
                        return {
                            "url": url,
                            "domain": self.domain,
                            "title": title,
                            "parsed_text": result_markdown,
                            "html_text": result.html or ""
                        }

                result_markdown = _clean_output(live_result.markdown, title) if live_result.markdown else ""
                if result_markdown and len(result_markdown.strip()) > _MIN_LENGTH:
                    return {
                        "url": url,
                        "domain": self.domain,
                        "title": title,
                        "parsed_text": result_markdown,
                        "html_text": rendered_html
                    }

        return {
            "url": url,
            "domain": self.domain,
            "title": "Errore di parsing",
            "parsed_text": "",
            "html_text": ""
        }