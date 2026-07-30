from src.parsers.parser_imdb import ImdbParser
from src.parsers.parser_mymovies import MyMoviesParser
from src.parsers.parser_mypersonaltrainer import MyPersonalTrainerParser
from src.parsers.parser_premier import PremierLeagueParser
from src.parsers.parser_wikipedia import WikipediaParser
from src.parsers.parser_un import Parser_UN
from src.parsers.parser_base import Parser


_AVAILABLE_PARSERS = { #in questo modo il dizionario non è creato ogni volta che creiamo una istanza di parse
            "www.my-personaltrainer.it" : MyPersonalTrainerParser,
            "it.wikipedia.org" : WikipediaParser,
            "www.premierleague.com" : PremierLeagueParser,
            "www.un.org" : Parser_UN,
            "www.mymovies.it": MyMoviesParser,
            "www.imdb.com": ImdbParser
        }

class ParserFactory():

    def __init__(self):
        pass
    
    @staticmethod
    def create(domain: str) -> Parser:
        if domain not in _AVAILABLE_PARSERS:
            raise ValueError("Domain currently not available for parsing")
        return _AVAILABLE_PARSERS[domain]()