import asyncio
import sys
import os

# Aggiunge la cartella src al path per importare correttamente il modulo
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from ollama_client import extract_triples

async def main():
    # Testo di prova (puoi cambiarlo con quello che preferisci)
    testo_prova = """
    
Una battaglia dopo l'altra
Regia di Paul Thomas Anderson. Un film Da vedere 2025 con Leonardo DiCaprio, Sean Penn, Benicio Del Toro, Regina Hall, Teyana Taylor. Cast completo Titolo originale: One Battle After Another. Genere Drammatico, Thriller, - USA, 2025, durata 161 minuti. Uscita cinema giovedì 25 settembre 2025 distribuito da Warner Bros Italia. Oggi tra i film al cinema in 4 sale cinematografiche - MYmonetro 4,30 su 33 recensioni tra critica, pubblico e dizionari.


Quando il loro malvagio nemico ricompare dopo 16 anni, un gruppo di ex rivoluzionari si riunisce per salvare la figlia di uno di loro. Il film ha ottenuto 12 candidature e vinto 6 Premi Oscar, ha vinto un premio ai David di Donatello, 8 candidature e vinto 4 Golden Globes, 13 candidature e vinto 6 BAFTA, 1 candidatura a Cesar, Il film è stato premiato a National Board, 13 candidature e vinto 3 Critics Choice Award, ha vinto un premio ai Writers Guild Awards, ha vinto un premio ai Directors Guild, ha vinto un premio ai CDG Awards, ha vinto un premio ai Producers Guild, a AFI Awards, ha vinto un premio ai ADG Awards, 6 candidature a The Actor Awards, Una battaglia dopo l'altra è 59° in classifica al Box Office, ieri ha incassato € 664,00 e registrato 792.831 presenze in totale.


Anderson fa il suo 'grande romanzo americano'. Un film corrosivo sulle rivoluzioni familiari, politiche, sociali.
Recensione di Marzia Gandolfi
giovedì 18 settembre 2025


Bob Ferguson, rivoluzionario in pensione, ha esploso tutti i suoi colpi nella giovinezza, sognando un mondo migliore al confine tra Messico e USA. Appeso al chiodo l'artiglieria e il nome di battaglia, Ghetto Pat, fa il padre a tempo pieno di Willa, adolescente esperta di arti marziali. Tra una canna e un rimorso prova a proteggerla dal suo passato che puntualmente bussa alla porta e chiede il conto. Dall'ombra riemerge un vecchio nemico, il colonnello Lockjaw, che più di ogni altra cosa vuole integrare un movimento suprematista devoto a San Nicola. Ma Bob e Willa sono un ostacolo alla sua ambizione. Lockjaw rapisce Willa e Bob riprende il fucile.

Paul Thomas Anderson è l'immagine del suo Paese: un ego smisurato alimentato da un'immaginazione senza limiti. Un genio che torna tenacemente alla misteriosa fonte che lo distingue dalla maggioranza dei suoi colleghi: l'ispirazione.

E a ispirarlo è di nuovo una delle grandi leggende invisibili della letteratura americana (l'altra è Salinger), il più inadattabile tra gli inadattabili, Thomas Pynchon e il suo romanzo, "Vineland". Adattamento libero perché dopo Vizio di forma, Anderson sa bene che è impossibile restituirlo, restituire un'opera letteraria indefinibile, considerata una delle più importanti del XX secolo e oggetto di una moltitudine di studi che ha imbarcato gli scaffali delle biblioteche americane.

Cercare di analizzare l'opera di Pynchon è come indossare una vestaglia al contrario, è quello che fa uno dei suoi personaggi. Figuriamoci tradurla in immagini, ridurre a dimensione ragionevole le teorie, i riferimenti scientifici, la manipolazione romanzesca della storia, le riflessioni sulla decadenza, le singolarità erotiche, la genealogia, l'erudizione vertiginosa, le invenzioni deliranti, i discorsi anticapitalisti... Ci ha messo almeno quattro anni Anderson per farne il suo 'grande romanzo americano', un film corrosivo che affronta l'utopia libertaria e la rivoluzione conservatrice attraverso il viaggio del suo eroe anti-establishment: un padre paranoico e smarrito che intraprende una ricerca personale cercando la figlia rapita.

Se il materiale originale va e viene tra la rielezione di Ronald Reagan e gli anni Sessanta/Settanta, Una battaglia dopo l'altra avanza fino agli anni Venti, sotto una probabile presidenza Trump anche se il suo nome non viene mai menzionato. In questo senso, Una battaglia dopo l'altra porta bene il suo titolo: non è un film 'moderno' e forse nemmeno 'attuale', è un film sulle rivoluzioni familiari, politiche, sociali. Anderson mette in evidenza un cambiamento di paradigma generazionale e identitario in un mondo sull'orlo del baratro e in un Paese sempre più autoritario, ma dove continuano a rinascere proteste salutari, necessarie e vitali. Inventa una visione poetica della storia degli Stati Uniti, un cortocircuito temporale che mescola passato e presente, La battaglia di Algeri e Black Lives Matter...

In questa commedia poliedrica, che oscilla tra dramma intimista e action movie senza interruzioni, i personaggi sono innumerevoli. Appaiono, scompaiono e ricompaiono, passandosi il testimone, urtandosi lungo il percorso, mescolandosi costantemente, contaminandosi a vicenda, in una storia frammentata e allucinata, posta sotto il segno del tradimento. Un cocktail esplosivo preparato da Anderson, bombarolo come Ferguson, con umorismo terribile per far emergere le componenti più folli di un'umanità che si sta perdendo in tutto lo spazio che lo schermo gli concede (VistaVision). Un formato scelto per contenere tutte le idee dell'autore. Questo fracasso narrativo, questa intelligente decostruzione del linguaggio e della sintassi, non è priva di effetti collaterali: trame e storie si intrecciano, si sovrappongono, si scontrano, lasciando lo spettatore stordito, come dopo un montante di Sonny Liston.

Libertà, fucili e paternità: il ritorno di Paul Thomas Anderson con Di Caprio protagonista. Sognando il trionfo agli Oscar.

Bob Ferguson è uno stravagante padre di mezza età. Capelli lunghi e baffo a manubrio, vive come un reduce di sé stesso, smarrito e in preda alle dipendenze. Sedici anni fa, però, era il faro della French 75, un pugno di rivoluzionari americani uniti da ideali libertari. Quando un vecchio rivale, il colonnello nazionalista Steven J. Lockjaw rapisce la sua unica figlia, è costretto a imbracciare di nuovo il fucile e radunare i vecchi compagni d'armi. Spalleggiato dall'intraprendente Perfidia, farà di tutto per ricongiungersi alla sua creatura.

Quattro anni dopo l'acclamato coming of age Licorice Pizza, Paul Thomas Anderson - come di consueto nella tripla veste di sceneggiatore, regista e co-produttore del film - si lascia ispirare da "Vineland", altro romanzo del decano del postmoderno Thomas Pynchon per Una battaglia dopo l'altra (nel 2014 aveva riletto "Vizio di forma" per trarne il film omonimo).

È il terzo adattamento letterario per il regista californiano: si ricorderà che Il petroliere rielaborava assai liberamente "Petrolio!" di Sinclair.

All star movie tra i più attesi della stagione cinematografica, segna la prima, sospirata collaborazione tra il regista e Di Caprio. L'attore, che ha parlato di un film "incredibilmente epico", dovrà affrontare Sean Penn (al secondo film con Anderson dopo Licorice Pizza) nei panni di un glaciale villain, ma potrà contare sull'apporto di Benicio Del Toro (di nuovo al servizio del cineasta losangelino dopo Vizio di forma) che incarnerà la spalla Sensei Sergio.

Oltre a una Regina Hall ironica come non mai, vedremo in azione anche l'esordiente Chase Infiniti - l'autore di Magnolia conferma il fiuto nel lanciare giovani promesse - e la cantante Teyana Tailor, magnetica in A thousand and one di A. V. Rockwell. Spalleggiano il cast principale Wood Harris, l'emergente rapper Shayna McHayle e la cantante Alana Haim, rivelatasi proprio in Licorice Pizza.

I fantasmi del passato e l'alienazione, le famiglie disfunzionali e gli adulti bambini, il rimpianto e il perdono. Ballando tra black comedy e lisergica satira sociale, tra action movie e focus sulle screpolature emotive dei protagonisti, Anderson rimane fedele a sé stesso e promette un film corale tracimante, ipercinetico, tensivo: fischieranno pallottole, non mancheranno traumi sepolti e riemersi, fughe in auto, intrighi, amori e pedinamenti, bilanciati dai consueti frangenti umoristici e dai noti virtuosismi di regia (piano sequenza e camera a mano, marchio di fabbrica della grammatica stilistica andersoniana).

Una battaglia dopo l'altra conferma, infatti, sin dal trailer un'estetica che occhieggia alla New Hollywood (i numi Scorsese e Altman su tutti), dialoghi sardonici e una scrittura meticolosa per mettere il dito sulle ferite aperte dell'America contemporanea - la questione razziale su tutte - rischiarando, così, "un punto di vista politico e culturale che brucia nella nostra psiche" come ha assicurato Di Caprio.

Benché non sia un blockbuster, secondo Variety il budget del film ha sfiorato i 140 milioni di dollari rispetto ai 100 inizialmente stanziati, diventando, così, il più costoso tra quelli diretti da Anderson.

Come sempre, anche per il film più ambizioso della sua decorata carriera - per la prima volta il regista ricorre al formato IMAX, tipico di spettacoli magniloquenti -, si è contornato di fedelissimi nel cast tecnico: tornano il compositore Greenwood, il compianto assistente alla regia Adam Somner, il direttore della fotografia Bauman, il montatore Jurgensen e il costumista Atwood.

Il film è stato girato in pellicola 35mm VistaVision in più località della California - le contee di Humboldt e Sacramento e il Parco Anza-Borrego - e a El Paso, in Texas. Iniziate a gennaio 2024, le riprese sono terminate in autunno per lungaggini produttive che si sono riverberate anche sul montaggio: dopo le prime disastrose proiezioni campione, Anderson è dovuto tornare in moviola per ridisegnare la trama e consentire al pubblico di trovare maggiore empatia con i protagonisti.

Una battaglia dopo l'altra, per cast stellare, sforzo produttivo, formato cinematografico e appeal del regista, punta a pareggiare i costi realizzativi e soprattutto sparigliare le carte agli Oscar 2026, così da dilatarne lo sfruttamento in sala: si ricorderà che l'ex enfant prodige di Hollywood, dal 1998 ad oggi, ha ricevuto undici candidature dall'Academy tra miglior film, sceneggiatura e regia, senza stringere mai, però, nessuna statuetta.

Annunciato al CinemaCon di Las Vegas ad aprile, Warner Bros lo distribuirà in Italia il 25 settembre, e dal giorno dopo in USA, Canada e UK, posticipando il debutto inizialmente previsto d'estate (8 agosto), la stagione storicamente più remunerativa per il botteghino americano.
    """
    
    print("Invio del testo a Ollama in corso...")
    risultato = await extract_triples(testo_prova)
    
    print("\n--- RISULTATO RESTITUITO DA OLLAMA ---")
    import json
    print(json.dumps(risultato, indent=4, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())