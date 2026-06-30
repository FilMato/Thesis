import string
import re 
from collections import Counter
from nltk.corpus import stopwords
from math import log, sqrt

#classe per valutare l'output del parser, i singoli metodi di valutazione e gli attributi sono privati
class Evaluator:

    def __init__(self):
        self._languages_stopwords = {
            'english' : set(stopwords.words('english')), 
            'italian' : set(stopwords.words('italian')), 
            'spanish' : set(stopwords.words('spanish')), 
            'french' : set(stopwords.words('french'))
            }

    #metodo per creare una lista di token
    @staticmethod
    def _tokenization(text: str) -> list[str]:

        text = text.lower()
        #funzione per rendere il testo pulito
        cleaning_rule = str.maketrans(string.punctuation, ' ' * len(string.punctuation)) #sostituisce la punteggiatura con spazi vuoti
        clean_txt = text.translate(cleaning_rule)
        clean_list = clean_txt.split() 

        return clean_list
    
    #calcola le tre metriche: precision, recall, F1-Score
    @staticmethod
    def _calculation(G: int, E: int, matches: int) -> dict[str, float]: #la funzione è comune per token_level_eval e rouge-2
        
        if not E:
            precision = 0
        else:
            precision = matches / E
        
        if not G:
            recall = 0
        else:
            recall = matches / G 

        if not precision + recall:
            F1 = 0
        else:
            F1 = 2*(precision*recall / (precision+recall))

        return {"precision": precision, 
                "recall": recall,
                "f1": F1}
    
    @staticmethod
    def _extract_ngrams(tokens, n) -> list[tuple[str]]:
        return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]
    
    #nel gold standard sono stati inseriti url di lingue diverse,
    #per il filtro delle stopwords si cerca di stimare in che lingua sia il testo.
    #si è definito un dizionario che mappa le stopwords alla lingua negli attributi della classe.
    def _detect_language(self, tokenized_txt: list) -> str: 
            
            input_txt = Counter(tokenized_txt)
            max_cnt = 0
            detected_language = ''
            for language in self._languages_stopwords: #Costo = O(tokens*lingue) = O(tokens) perché il numero delle lingue è costante
                curr_set = self._languages_stopwords[language]
                curr_intersection = sum((input_txt & Counter(curr_set)).values())
                if curr_intersection > max_cnt:
                    max_cnt = curr_intersection
                    detected_language = language

            return detected_language #non ottimale per testi troppo brevi: il conteggio delle stopwords potrebbe essere pari tra le lingue
    
    
    def _filter_stopwords(self, tokenized_txt: list, language: str) -> list[str]:
        if not language or language not in self._languages_stopwords:
            return tokenized_txt
        return [word for word in tokenized_txt if word not in self._languages_stopwords[language]]
    
    #term frequency (per ogni parola ne calcola il peso rapportandola al total delle parole)
    @staticmethod
    def _tf(tokens: list) -> dict[str, float]:

        cnt = Counter(tokens)
        token_count = len(tokens)
        tf = {}
        for word in cnt:
            tf[word] = cnt[word] / token_count

        return tf
    
    #inverse document frequency -> da meno peso alle parole più comuni e ne aggiunge a quelle più rare. 
    #nonostante i testi siano già stati filtrati a livello di stopwords idf colpisce le parole che non detengono
    #particolare importanza per la semantica del testo (troppo comuni in entrambi)
    @staticmethod
    def _idf(gs_tokens: list, ps_tokens: list) -> dict[str, float]:

        gs_tokens_set = set(gs_tokens)
        ps_tokens_set = set(ps_tokens)
        combined_vocabulary = gs_tokens_set.union(ps_tokens_set)
        idf = {}
        for word in combined_vocabulary:
            docs_containing_word = 0
            if word in gs_tokens_set:
                docs_containing_word += 1
            if word in ps_tokens_set:
                docs_containing_word += 1
            idf[word] = 1 + log(2 + 1 / docs_containing_word + 1)
            #spiegazione della formula : 2 = documenti totali, i +1 nel logaritmo servono a proteggere
            #dall'errore di divisione per 0 (come se ci fosse un documento in più che contiene tutte le parole)
            #il +1 al di fuori dal logaritmo serve a dar peso alle parole contenute in entrambi i documenti, che altrimenti
            #peserebbero 0 (log(2/2) = log(1) = 0)

        return idf

    def _build_tf_idf(self, filtered_tokens_gs: list, filtered_tokens_ps: list) -> tuple[dict[str, float]]:
        tf_gs_dict = self._tf(filtered_tokens_gs)
        tf_ps_dict = self._tf(filtered_tokens_ps)
        idf_dict = self._idf(filtered_tokens_gs, filtered_tokens_ps)

        tfidf_gs =  {}
        tfidf_ps = {}

        for word in idf_dict:
            tfidf_gs[word] = tf_gs_dict.get(word, 0) * idf_dict[word] #il vocabolario combinato contiene parole da entrambi i testi, .get(word, 0) fa in modo che se la parola non esiste il risultato sia 0 invece di avere un KeyError
            tfidf_ps[word] = tf_ps_dict.get(word, 0) * idf_dict[word]
        
        return tfidf_gs, tfidf_ps
    
    #prende i due vettori tf e idf e misura l'angolo tra di essi per poi calcolarne il coseno.
    #misura se i due testi enfatizzano gli stessi concetti (cos~=1)
    def _tfidf_cosine_similarity(self, ps_txt: str, gs_txt: str) -> float:
        
        tokens_gs = self._tokenization(gs_txt)
        filtered_gs = self._filter_stopwords(tokens_gs, self._detect_language(tokens_gs))
        tokens_ps = self._tokenization(ps_txt)
        filtered_ps = self._filter_stopwords(tokens_ps, self._detect_language(tokens_ps))
        
        tfidf_gs, tfidf_ps = self._build_tf_idf(filtered_gs, filtered_ps)
        dot_product = 0

        for word in tfidf_gs:
            dot_product += tfidf_gs[word] * tfidf_ps.get(word, 0)
        
        magnitude_gs = 0
        magnitude_ps = 0
        for word in tfidf_gs:
            magnitude_gs += pow(tfidf_gs[word], 2)
        for word in tfidf_ps:
            magnitude_ps += pow(tfidf_ps[word], 2)
        magnitude_gs = sqrt(magnitude_gs)
        magnitude_ps = sqrt(magnitude_ps)
        
        try:
            return dot_product / (magnitude_gs * magnitude_ps) 
        except ZeroDivisionError: #con un testo reale questa cosa non dovrebbe succedere ma il controllo va messo per sicurezza
            return 0

    #il confronto con il gs non è necessario in quanto la densità testuale del testo è già una metrica di valutazione
    #in questo contesto si fa una differenza alla fine per avere un ulteriore indice di similarità tra i due testi
    def _information_density_score(self, ps_txt: str, gs_txt: str) -> dict[str, float]:

        tokens_gs = self._tokenization(gs_txt)
        filtered_gs = self._filter_stopwords(tokens_gs, self._detect_language(tokens_gs))
        tokens_ps = self._tokenization(ps_txt)
        filtered_ps = self._filter_stopwords(tokens_ps, self._detect_language(tokens_ps))
        try: 
            score_gs = len(filtered_gs) / len(tokens_gs)
        except ZeroDivisionError:
            score_gs = 0
        
        try:
            score_ps = len(filtered_ps) / len(tokens_ps)
        except ZeroDivisionError:
            score_ps = 0
        
        return {
            'Score gold standard' : score_gs,
            'Score parsed text' : score_ps, #viene calcolato quanto il testo è denso di informazioni una volta filtrato da rumore inutile (e.g stopwords che non aggiungono significato)
            'Difference' : abs(score_gs - score_ps)
            }
    
    def _token_level_eval(self, parsed_txt:str, gs_txt:str) -> dict[str, float]: 

        gs_set = Counter(self._tokenization(gs_txt)) #get a Counter of token, goal: be more accurate with token evaluation
        ps_set = Counter(self._tokenization(parsed_txt))
        marks = self._calculation(sum(gs_set.values()), sum(ps_set.values()), sum((gs_set & ps_set).values())) #matches = G intersection E
        
        return marks

    #invece di un singolo token prende coppie di parole consecutive, sensibile all'ordine testuale
    def _rouge_2_eval(self, parsed_txt:str, gs_txt:str) -> dict[float]: #i testi molto corti sono penalizzati: un testo di lunghezza n produce n-1 bigrammi

        gs_tokens = self._tokenization(gs_txt)
        ps_tokens = self._tokenization(parsed_txt)

        if len(gs_tokens) < 2 or len(ps_tokens) < 2:
            return self._token_level_eval(parsed_txt, gs_txt)

        gs_bigram_set = Counter(self._extract_ngrams(gs_tokens, 2)) 
        ps_bigram_set = Counter(self._extract_ngrams(ps_tokens, 2))
        marks = self._calculation(sum(gs_bigram_set.values()), sum(ps_bigram_set.values()), sum((gs_bigram_set & ps_bigram_set).values())) 
        
        return marks
    
    #funzione da usare nel server per POST/evaluate
    def eval_server(self, parsed_txt: str, gs_txt:str) -> dict[dict]: 

        return {
            "token_level_eval": self._token_level_eval(parsed_txt, gs_txt),
            "rouge_2_eval": self._rouge_2_eval(parsed_txt, gs_txt),
            "information_density_evaluation" : self._information_density_score(parsed_txt, gs_txt),
            "TF-IDF_cosine_similarity" : self._tfidf_cosine_similarity(parsed_txt, gs_txt)
        }
    
    
