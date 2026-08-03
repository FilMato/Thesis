import os
import re
import logging
from typing import List, Dict, Any, Optional
from neo4j import GraphDatabase, Driver

# Configurazione del logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Neo4jClient")

# Client per la gestione delle operazioni CRUD sul Knowledge Graph di Neo4j.
class Neo4jClient:

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

    #Inizializza la connessione con il cluster Neo4j e verifica la connettività.
    def _connect(self) -> None:
        try:
            self._driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
            self._driver.verify_connectivity()
            logger.info("Connessione a Neo4j stabilita con successo.")
        except Exception as e:
            logger.error(f"Errore critico durante la connessione a Neo4j: {e}")
            raise e
    # Chiude il driver e rilascia le risorse di rete.
    def close(self) -> None:
        if self._driver:
            self._driver.close()
            logger.info("Connessione a Neo4j chiusa correttamente.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # Sanitizza i nomi di Tipi di Nodi e Relazioni per prevenire errori di sintassi Cypher.
    @staticmethod
    def _sanitize_identifier(identifier: str) -> str:
        if not identifier:
            return "ENTITY"
        sanitized = re.sub(r"[^\w]", "_", identifier.strip())
        sanitized = re.sub(r"_+", "_", sanitized).strip("_")
        return sanitized if sanitized else "ENTITY"

    #Aggiunge una singola tripla (Soggetto -[Relazione]-> Oggetto) al grafo.Utilizza MERGE per evitare la duplicazione dei nodi.
    def add_triple(
        self,
        subject: str,
        subject_type: str,
        relation: str,
        obj: str,
        obj_type: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> bool:
        
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

    #Aggiunge un batch di triple al grafo. Restituisce il numero di triple inserite con successo.
    def add_triples_batch(self, triples: List[Dict[str, Any]]) -> int:
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
    
    #Restituisce il numero totale di nodi e relazioni nel Knowledge Graph.
    def get_stats(self) -> Dict[str, int]:
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

    # Svuota il database
    def clear_database(self) -> bool:
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

    # Elimina una relazione specifica e , se rimangono nodi senza relazioni, elimina anch'essi.
    def delete_relation_and_orphans(self, subject: str, relation: str, obj: str):
        query = """
        MATCH (s {name: $subject})-[r]->(o {name: $obj})
        WHERE type(r) = $relation
        DELETE r
        WITH s, o
        // Controlla se il Soggetto è rimasto orfano e distruggilo
        OPTIONAL MATCH (s)-[rs]-()
        WITH s, o, count(rs) as deg_s
        FOREACH (ignore IN CASE WHEN deg_s = 0 THEN [1] ELSE [] END | DELETE s)
        // Controlla se l'Oggetto è rimasto orfano e distruggilo
        WITH o
        OPTIONAL MATCH (o)-[ro]-()
        WITH o, count(ro) as deg_o
        FOREACH (ignore IN CASE WHEN deg_o = 0 THEN [1] ELSE [] END | DELETE o)
        """
        with self._driver.session() as session:
            session.run(query, subject=subject, relation=relation, obj=obj)

    # Elimina un nodo e tutte le sue relazioni. Se a causa di questa eliminazione altri nodi rimangono scollegati da tutto il resto del grafo, elimina anche questi.
    def delete_node_and_orphans(self, node_name: str):
        query = """
        MATCH (n {name: $node_name})
        // 1. Memorizza tutti i vicini prima di distruggere il nodo
        OPTIONAL MATCH (n)-[]-(neighbor)
        WITH n, collect(neighbor) AS neighbors
        // 2. Elimina il nodo bersaglio e taglia tutte le frecce (relazioni)
        DETACH DELETE n
        // 3. Passa in rassegna i vicini sopravvissuti
        WITH [x IN neighbors WHERE x IS NOT NULL] AS valid_neighbors
        UNWIND valid_neighbors AS neighbor
        // 4. Se un vicino ha 0 relazioni rimanenti, cancellalo
        OPTIONAL MATCH (neighbor)-[r]-()
        WITH neighbor, count(r) AS deg
        FOREACH (ignore IN CASE WHEN deg = 0 THEN [1] ELSE [] END | DELETE neighbor)
        """
        with self._driver.session() as session:
            session.run(query, node_name=node_name)

    # Legge i risultati di una query Cypher e li restituisce come lista di dizionari.
    def execute_read_query(self, query: str) -> list:
        try:
            with self._driver.session() as session:
                result = session.run(query)
                # Converte i record Neo4j in normali dizionari Python
                return [record.data() for record in result]
        except Exception as e:
            logger.error(f"Errore durante l'esecuzione della query Cypher : {e}")
            return [{"error": str(e)}]