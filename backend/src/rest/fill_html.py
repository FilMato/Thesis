
#FILE DA CANCELLARE A FINE PROGETTO

import json
import os
import asyncio
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

async def main():
    # Assicurati che il nome sia quello corretto per il seeder
    file_path = os.path.join("..", "..", "..", "gs_data", "dominio_www.imdb.com_gs.json")
    
    print(f"Leggo il file: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("Avvio Crawl4AI con difese anti-WAF...")
    
    # 1. Configurazione Browser "Stealth"
    browser_cfg = BrowserConfig(
        headless=True, 
        java_script_enabled=True,
        ignore_https_errors=True
    )
    
    # 2. Configurazione Crawler anti-bot
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        magic=True, # Attiva le protezioni avanzate di Crawl4AI
        wait_for="body", 
        delay_before_return_html=6.0, # Diamo ad Amazon 6 secondi per eseguire e superare la challenge JS
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        for item in data:
            current_html = item.get("html_text", "")
            
            # Se l'HTML è assente o è incastrato nella pagina di blocco di Amazon (challenge)
            if not current_html or "challenge-container" in current_html:
                print(f"\nTentativo di estrazione per: {item['title']}...")
                
                max_retries = 3
                for attempt in range(max_retries):
                    result = await crawler.arun(url=item["url"], config=run_cfg)
                    
                    # Controllo qualità: verifichiamo che Amazon non ci abbia rifilato il WAF
                    if result.html and "challenge-container" not in result.html:
                        item["html_text"] = result.html
                        print(f"  -> [{attempt+1}/{max_retries}] SUCCESSO! Scaricati {len(result.html)} byte.")
                        break # Usciamo dal ciclo dei tentativi
                    else:
                        print(f"  -> [{attempt+1}/{max_retries}] BLOCCATO DAL WAF. La sessione si sta scaldando, riprovo tra 5 sec...")
                        await asyncio.sleep(5) # Pausa prima di riprovare lo stesso link
                
                # Pausa di cortesia tra URL DIVERSI per non triggerare limiti di frequenza
                await asyncio.sleep(4)
            else:
                print(f"HTML già valido per: {item['title']} (Salto)")

    # Salviamo il file aggiornato
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("\nFatto! Il file JSON è stato aggiornato ed epurato dai blocchi Amazon.")

if __name__ == "__main__":
    asyncio.run(main())