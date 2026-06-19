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
                ".main-container container",     
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

_EXCLUDED_SELECTOR = ".img, .breadcrumb, #sidebar, .skip-link screen-reader-text, .home-footer, .node-sidebar, .views-field-field-news-tags, .block-content-footer, .type-entermedia_image, #player-gui, #addtoany, #sharing_widget, #skip-link, .image-caption, #sharing-widget, #breadcrumbs, #more_button, .photo-credit, .page-header, .fusion-video, #player-controls, .wp-caption-text"

def _clean_output(text: str) -> str:
        text = re.sub(r'\[\]\([^)]+\)', '', text) #pulizia dei link vuoti
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
        
    async def parser_url2(self, url: str, html_text: str) -> dict[str, str]: #input url, output json obj
        print("RUNNING UN PARSER\n")
        browser_cfg = BrowserConfig(headless = True)
        soup = BeautifulSoup(html_text, "html.parser")
        title = soup.select_one("title")
        title = title.text.strip() if title else "Errore nel trovare il titolo"
        
        no_selector_cfg = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            exclude_all_images=True,
            exclude_social_media_links=True,
            excluded_tags=_EXCLUDED_TAGS,
            excluded_selector=_EXCLUDED_SELECTOR
        )
        
        async with AsyncWebCrawler(config=browser_cfg) as crawler:

            for selector in _CSS_SELECTORS:
                selector_cfg = CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    css_selector=selector,
                    exclude_all_images=True,
                    exclude_social_media_links=True,
                    excluded_tags=_EXCLUDED_TAGS,
                    excluded_selector=_EXCLUDED_SELECTOR
                )
                result = await crawler.arun(
                    url = f'raw:{html_text}', 
                    config = selector_cfg
                )
                print(result.success, repr(result.markdown), result.error_message)
                result_markdown = _clean_output(repr(result.markdown))
                print("RESULT MARKDOWN" + result_markdown)
                if result.success and result_markdown and len(result_markdown.strip()) > 50:
                    return {
                        "url": url,
                        "domain": self.domain,
                        "title": title,
                        "parsed_text": result_markdown,
                        "html_text": result.html or ""   
                    }
            
            #logica di fallback: (il dominio è molto eterogeneo, si da priorità alla raccolta di informazioni)
            #se non dovesse esistere alcun selector faccio il parsing un'ultima volta senza alcun selector
            # after all selectors and no_selector_cfg have failed on raw HTML, fall back to live URL
            for selector in _CSS_SELECTORS:
                selector_cfg = CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    css_selector=selector,
                    exclude_all_images=True,
                    exclude_social_media_links=True,
                    excluded_tags=_EXCLUDED_TAGS,
                    excluded_selector=_EXCLUDED_SELECTOR,
                    wait_until="domcontentloaded"
                )
                result = await crawler.arun(url=url, config=selector_cfg)
                result_markdown = _clean_output(result.markdown)
                if result.success and result_markdown and len(result_markdown.strip()) > 50:
                    return {
                        "url": url,
                        "domain": self.domain,
                        "title": title,
                        "parsed_text": result_markdown,
                        "html_text": result.html or ""
                    }

            return {
                "url": url,
                "domain": self.domain,
                "title": "Errore di parsing",
                "parsed_text": "",
                "html_text": ""
            }