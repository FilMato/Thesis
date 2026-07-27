import os
import re
import logging
from typing import List, Dict, Any, Optional
from neo4j import GraphDatabase, Driver

# Configurazione del logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Neo4jClient")


class Neo4jClient:
    """Client per la gestione delle operazioni CRUD sul Knowledge Graph di Neo4j."""

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        # Recupera le credenziali dalle variabili d'ambiente o usa i fallback predefiniti
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "minerva_graph_pass")
        self._driver: Optional[Driver] = None

        self._connect()

    def _connect(self) -> None:
        """Inizializza la connessione con il cluster Neo4j e verifica la connettività."""
        try:
            self._driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
            self._driver.verify_connectivity()
            logger.info("Connessione a Neo4j stabilita con successo.")
        except Exception as e:
            logger.error(f"Errore critico durante la connessione a Neo4j: {e}")
            raise e

    def close(self) -> None:
        """Chiude il driver e rilascia le risorse di rete."""
        if self._driver:
            self._driver.close()
            logger.info("Connessione a Neo4j chiusa correttamente.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def _sanitize_identifier(identifier: str) -> str:
        """
        Sanifica i nomi di Tipi di Nodi e Relazioni per prevenire errori di sintassi Cypher.
        Converte spazi in underscore, rimuove caratteri speciali e trasforma in maiuscolo se relazione.
        """
        if not identifier:
            return "ENTITY"
        # Mantiene solo caratteri alfanumerici e underscore
        sanitized = re.sub(r"[^\w]", "_", identifier.strip())
        # Rimuove underscore duplicati o in testa/coda
        sanitized = re.sub(r"_+", "_", sanitized).strip("_")
        return sanitized if sanitized else "ENTITY"

    def add_triple(
        self,
        subject: str,
        subject_type: str,
        relation: str,
        obj: str,
        obj_type: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Aggiunge una singola tripla (Soggetto -[Relazione]-> Oggetto) al grafo.
        Utilizza MERGE per evitare la duplicazione dei nodi.
        """
        if not subject or not obj or not relation:
            logger.warning("Impossibile inserire tripla: dati mancanti.")
            return False

        sub_label = self._sanitize_identifier(subject_type).capitalize()
        obj_label = self._sanitize_identifier(obj_type).capitalize()
        rel_type = self._sanitize_identifier(relation).upper()
        props = properties or {}

        # Query Cypher parametrizzata per prevenire la Injection
        query = f"""
        MERGE (s:`{sub_label}` {{name: $subject}})
        MERGE (o:`{obj_label}` {{name: $obj}})
        MERGE (s)-[r:`{rel_type}`]->(o)
        SET r += $properties
        RETURN type(r)
        """

        try:
            with self._driver.session() as session:
                session.execute_write(
                    lambda tx: tx.run(
                        query,
                        subject=subject.strip(),
                        obj=obj.strip(),
                        properties=props,
                    ).consume()
                )
                logger.debug(
                    f"Tripla inserita: ({subject}: {sub_label}) -[{rel_type}]-> ({obj}: {obj_label})"
                )
                return True
        except Exception as e:
            logger.error(f"Errore durante l'inserimento della tripla: {e}")
            return False

    def add_triples_batch(self, triples: List[Dict[str, Any]]) -> int:
        """
        Inserisce un elenco di triple in batch (es. quelle estratte dal JSON di Ollama).
        Ogni elemento del dizionario deve contenere:
        'subject', 'subject_type', 'relation', 'object', 'object_type'
        """
        count = 0
        for item in triples:
            success = self.add_triple(
                subject=item.get("subject") or item.get("soggetto"),
                subject_type=item.get("subject_type")
                or item.get("tipo_soggetto", "Entity"),
                relation=item.get("relation") or item.get("relazione"),
                obj=item.get("object") or item.get("oggetto"),
                obj_type=item.get("object_type")
                or item.get("tipo_oggetto", "Entity"),
                properties=item.get("properties", {}),
            )
            if success:
                count += 1

        logger.info(f"Batch completato: {count}/{len(triples)} triple inserite.")
        return count

    def get_stats(self) -> Dict[str, int]:
        """Restituisce il numero totale di nodi e relazioni nel Knowledge Graph."""
        query = """
        MATCH (n)
        OPTIONAL MATCH (n)-[r]->()
        RETURN count(DISTINCT n) AS nodes_count, count(DISTINCT r) AS rels_count
        """
        try:
            with self._driver.session() as session:
                result = session.run(query).single()
                if result:
                    return {
                        "nodes": result["nodes_count"],
                        "relationships": result["rels_count"],
                    }
        except Exception as e:
            logger.error(f"Errore durante il recupero delle statistiche: {e}")

        return {"nodes": 0, "relationships": 0}

    def clear_database(self) -> bool:
        """
        Svuota completamente il database Neo4j.
        UTILE PER TEST E RESET AMBIENTE. USARE CON CAUTELA!
        """
        query = "MATCH (n) DETACH DELETE n"
        try:
            with self._driver.session() as session:
                session.execute_write(lambda tx: tx.run(query).consume())
                logger.warning(
                    "Database Neo4j svuotato con successo (tutti i nodi e gli archi sono stati eliminati)."
                )
                return True
        except Exception as e:
            logger.error(f"Errore durante la pulizia del database: {e}")
            return False


# --- Esempio di utilizzo / Testing diretto ---
if __name__ == "__main__":
    # Test del client fuori da Docker (se eseguito direttamente in locale)
    with Neo4jClient() as client:
        print("Statistiche iniziali:", client.get_stats())

        # Test inserimento batch (simulando l'output di Ollama)
        ollama_extracted_json = [
            {
                "subject": "Christopher Nolan",
                "subject_type": "Person",
                "relation": "DIRECTED",
                "object": "Inception",
                "object_type": "Movie",
            },
            {
                "subject": "Leonardo DiCaprio",
                "subject_type": "Person",
                "relation": "ACTED_IN",
                "object": "Inception",
                "object_type": "Movie",
            },
        ]

        inserted = client.add_triples_batch(ollama_extracted_json)
        print(f"Inserite {inserted} triple di prova.")
        print("Statistiche aggiornate:", client.get_stats())