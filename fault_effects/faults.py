"""Fault flags from Finnish (and some English) listing text.

Two inputs feed the same rule set:
- Huutokaupat: a structured seller checklist (warning light yes/no + which
  light, inspection, body, windshield, interior, ...) plus the free-text
  "Viat ja muut havainnot" section and the title.
- Nettiauto: title + USP + free-text description only.

Text is folded to lowercase ASCII-ish (ä→a, ö→o, å→a) so a pattern written as
"ei kaynnisty" matches "ei käynnisty", "EI KÄYNNISTY" and the ASCII spelling
sellers often type. Rules match within a clause and can be cancelled by a
negator shortly before the match ("ei ruostetta", "ei vikavaloja") or by an
"ei pala / ei ole" right after it.

Rules are deliberately explicit regexes, not a model: each one is checkable,
and `validate.py` measures precision/recall against a hand-checked sample.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

# ─────────────────────────── text normalisation ───────────────────────────

_FOLD = str.maketrans({"ä": "a", "ö": "o", "å": "a", "é": "e", "è": "e", "ü": "u",
                       "\xa0": " ", "’": "'", "´": "'", "–": "-", "—": "-"})


def fold(text: str | None) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).lower().translate(_FOLD)
    return re.sub(r"[ \t]+", " ", t)


# Dealer boilerplate that mentions "faults" generically. Dropped sentence by
# sentence before matching, otherwise "saattaa olla piileviä vikoja" ("may have
# hidden faults") would look like a disclosed fault on thousands of ads.
BOILERPLATE = re.compile(
    r"piilevi|kuntotarkastu|hidden (?:faults|defects)|tutustu|seuraavat havainnot|havaitsimme|"
    r"sovitha|varastointimaksu|ostoaikomus|myynti-ilmoitu|yhteydess. myyj|not undergone|"
    r"test drive|nestepinnat|kerromme kuitenkin|kannattaa tulla|is possible|koeajettu|"
    r"saattaa tarvita noudettaessa|naista toimenpiteista|varusteissa saattaa olla|"
    r"varustetiedoissa voi olla|please arrange|you are welcome|binding bid|"
    r"ennen sitovan|katsomaan tarkemmin|koeajamaan|thank you|kiitos"
)

_SENT_SPLIT = re.compile(r"[.!?;:\n]+|\s/\s|\s-\s|^-|\s-(?=[a-z])")
_CLAUSE_SPLIT = re.compile(r",|\bmutta\b|\bpaitsi\b|\bmuuten\b|\bmuutoin\b|\bkuitenkin\b|\bbut\b|\(|\)")


def sentences(text: str) -> list[str]:
    """Folded sentences with dealer boilerplate removed."""
    out = []
    for s in _SENT_SPLIT.split(fold(text)):
        s = s.strip(" -*•·:")
        if s and not BOILERPLATE.search(s):
            out.append(s)
    return out


def clauses(sentence: str) -> list[str]:
    return [c.strip() for c in _CLAUSE_SPLIT.split(sentence) if c.strip()]


NEG_PRE = re.compile(
    r"(?:^|\W)(?:ei|eika|eivat|ilman|no|not|without|never|nolla|kumpikaan|ei mitaan)(?:\W|$)"
)
NEG_POST = re.compile(
    r"^\W{0,3}(?:\w+\W+){0,3}?(?:(?:ei|eivat)\s+(?:pala|syty|ole|nay|loydy|loytynyt|havaittu|esiinny|ilmene|"
    r"vaikuta)|en\s+(?:loytanyt|loyda|havainnut|huomannut|nahnyt))\b"
)


@dataclass
class Rule:
    """A fault rule. `pos` is searched in each clause (or sentence, if
    scope='sentence'). A hit counts unless cancelled:
      - neg_pre:   a negator within `window` chars before the hit, same clause
      - neg_post:  "ei pala / ei ole ..." right after the hit
      - exclude:   the clause/sentence matches this
      - require:   the *sentence* must also match this (context words)
      - neg_inside: a negator inside a component…problem span ("vaihteisto ei
                   pidä ääntä") — only for rules whose problem words carry no "ei"
    Several Rule objects may share a name; their hits are OR-ed.
    """
    name: str
    pos: re.Pattern
    neg_pre: bool = True
    neg_post: bool = True
    exclude: re.Pattern | None = None
    require: re.Pattern | None = None
    scope: str = "clause"
    window: int = 30
    neg_inside: bool = False

    def hits(self, sents: list[str]) -> list[str]:
        found = []
        for s in sents:
            if self.require is not None and not self.require.search(s):
                continue
            units = [s] if self.scope == "sentence" else clauses(s)
            for u in units:
                if self.exclude is not None and self.exclude.search(u):
                    continue
                for m in self.pos.finditer(u):
                    if self.neg_pre and NEG_PRE.search(u[max(0, m.start() - self.window):m.start()]):
                        continue
                    if self.neg_post and NEG_POST.match(u[m.end():m.end() + 50]):
                        continue
                    if self.neg_inside and NEG_PRE.search(m.group(0)):
                        continue
                    found.append(u[max(0, m.start() - 40):m.end() + 40])
                    break
        return found


def R(p: str) -> re.Pattern:
    return re.compile(p)


def near(a: str, b: str, gap: int = 4) -> str:
    """a … b or b … a with at most `gap` words in between."""
    w = rf"(?:\W+\w+){{0,{gap}}}?\W+"
    a, b = rf"(?<![a-z0-9])(?:{a})", rf"(?<![a-z0-9])(?:{b})"
    return rf"(?:{a}{w}{b}|{b}{w}{a})"


# ─────────────────────────── warning-light types ───────────────────────────
# Applied (a) to the Huutokaupat "Palaako jokin vikavalo: Kyllä, <text>" answer
# with no negation (the seller already said yes), and (b) to free text, where
# the sentence must also talk about a light/warning.

LIGHT_PATTERNS: dict[str, str] = {
    "light_engine": (r"moott?\w*(?:\W+\w+){0,2}?\W*(?:vika|hairio|tarkastus)?(?:valo|lamppu)\w*|moottorivalo\w*|"
                     r"moott?\.? ?hairio\w*|(?<!\w)hairiovalo\w*|check ?engine|service engine|"
                     r"engine (?:warning |malfunction |fault )?light|engine (?:malfunction|soon|fault)|\bmil\b|"
                     r"\bepc\b|moottorin? ?vik(?!\w*valo)\w*|moottorin hairio\w*|moottori(?:systeemi|jarjestelma)\w*|"
                     r"\blambda\w*|\begr\w*|katalysaat\w*|vikakoodi\w* (?:\w+ ){0,2}moottori\w*"),
    "light_abs_esp": (r"\babs\w*|\besp\b|\besc\b|\basr\b|\bdsc\b|\bdstc\b|\bvsc\b|\btrc\b|luistonest\w*|"
                      r"luiston est\w*|luistovalo\w*|ajon ?vakau\w*|ajovakau\w*|alustan vakau\w*|"
                      r"vakaudenhallin\w*|traction|stability|stabilitrak"),
    "light_airbag": r"airbag\w*|turva ?tyyn\w*|\bsrs\w*|turvavyon kiristi\w*|seat ?belt|pyrotek\w*",
    "light_tpms": r"rengaspain\w*|renkaiden pain\w*|rengasvaroi\w*|\btpms\b|tyre pressure|tire pressure|rengaspaineanturi\w*",
    "light_service": (r"huoltovalo\w*|huolto ?muistut\w*|huolto ?ilmoitu\w*|huoltovali\w*|\bservice\b|"
                      r"oil service|\binspection\b|kuittaama\w*|huollon kuittau\w*|\b[a-e]-huolto\w*|"
                      r"huolto (?:on )?ylit\w*|oljynvaihto ?(?:muistutus|ilmoitus|valo)\w*|\bmuistut\w*|"
                      r"maaraaikaishuol\w*"),
    "light_bulb": (r"polttimo\w*|(?<!\w)poltin\w*|\blamppu\w*|\bxenon\w*|\bbulb\w*|"
                   r"(?:ajo|jarru|parkki|seisonta|taka|sivu|sumu|kauko|lahi|peruutus|kilven|kilpi|vilkku|"
                   r"paivaajo)valo\w*\s*(?:on\s*)?(?:palanut|pimea\w*|ei toimi|rikki|vika\w*|viallinen|puuttuu)|"
                   r"valo(?:jen)? ?vika\w*|valo palanut|palanut valo|palaneen"),
    "light_glow_plug": r"hehku\w*|glow",
    "light_dpf": r"\bdpf\w*|hiukkas\w*|partikkeli\w*|\bfap\b|nokisuod\w*|\bgpf\b",
    "light_gearbox": r"vaihteisto\w*|vaihdelaatik\w*|gearbox|transmission|automaattilaatik\w*|\bdsg\b|mekatroniik\w*",
    "light_brake": r"jarru(?!valo)\w*|brake\w*|kasijarru\w*|\bepb\b|seisontajarru\w*",
    "light_battery": r"\bakku\w*|latau\w*|laturi\w*|generaattori\w*|battery|charg\w*|start ?[/-]? ?stop",
    "light_oil": r"oljyvalo\w*|oljyn ?paine\w*|oljynpaine\w*|oljyn ?(?:maara|taso|pinta)\w*|oil (?:pressure|level)|oljy\w*\s*(?:merkki|varoitus)?valo",
    "light_coolant": r"jaahdy\w*|coolant|lampotila\w*|moottorin lampo\w*|ylikuumen\w*",
    "light_steering": r"ohjaustehost\w*|ohjaus\w*|steering|\beps\b",
    "light_suspension": r"ilma-?alust\w*|ilmajous\w*|alusta\w*|jousitu\w*|suspension|airmatic|nivomat|korkeudens\w*",
    "light_emissions": r"adblue\w*|ad-blue|\burea\b|\bnox\w*|\bscr\b|paasto\w*|emission\w*",
}
LIGHT_RX = {k: R(v) for k, v in LIGHT_PATTERNS.items()}
# Inside the seller's "which light is on" answer any engine mention means the
# engine light ("ainakin moottorin", "moottorisysteemi huolla pian") unless it
# is about engine oil / temperature / a heater or fan.
LIGHT_FIELD_RX = dict(LIGHT_RX)
LIGHT_FIELD_RX["light_engine"] = R(LIGHT_PATTERNS["light_engine"] + r"|\bmoott(?!\w*(?:oljy|lampo|lammit|tuulet))\w*"
                                   r"(?!\s+(?:oljy|lampo|lammit|tuulet))|\bengine\b")
LIGHT_CTX = R(r"valo|herja|ilmoitu|ilmoittaa|vikakoodi|light|warning|vilkku|syttyy|syttyi|syttynyt|"
              r"\bpalaa\b|palavat|tauluun|mittaristo|kojelau|naytolla|naytossa")
ANY_LIGHT_TEXT = R(r"vikavalo\w*|merkkivalo\w*|varoitusvalo\w*|warning light\w*|hairiovalo\w*|check engine|"
                   r"vikailmoitu\w*|herja\w*")

# ─────────────────────────── free-text fault rules ───────────────────────────

GB = (r"vaihteist\w*|vaihdelaatik\w*|automaattilaatik\w*|automaattivaihteist\w*|\bdsg\w*|s-?tronic|"
      r"mekatroniik\w*|\bpakki\b|gearbox|transmission|\bvaihteet\b|\bvaihde\b|vaihteiden|vaihteita|"
      r"vaihteelle|synkro\w*|\bykkonen|\bkakkonen|\bkolmonen|\bnelonen|\bvitonen|peruutusvaihte\w*|"
      r"vaihteenvalitsin\w*|vaihtaminen|vaihtaessa|vaihdot")
GB_P = (r"vika\w*|rikki|rikkinai\w*|ongelm\w*|nyki\w*|nykai\w*|nytki\w*|nytka\w*|luista\w*|aanta\w*|aanee|"
        r"aantele\w*|aanekas|ulis\w*|ujel\w*|vonku\w*|kolis\w*|kolah\w*|rahis\w*|raksu\w*|rousk\w*|ratis\w*|"
        r"jumi\w*|potki\w*|viive\w*|viivei\w*|kitke\w*|vuota\w*|vuoto\w*|hajon\w*|tarah\w*|vaikea\w*|"
        r"vaikeas\w*|jayk\w*|hyppi\w*|hyppa\w*|kulunut|vaihdettava|korjattava|huono\w*|raskas\w*|tokk\w*|"
        r"kiukutt\w*|oikutt\w*|herja\w*|vikatila\w*|hatatila\w*|slip\w*|fault\w*|broken|problem\w*|noise|"
        r"nypa\w*|nypy\w*|nahkea\w*|rusah\w*|temppuil\w*|kolkk\w*")
CL = r"kytkin\w*|kytkime\w*|kytkimi\w*|clutch|vauhtipyor\w*|kaksoismassa\w*|\bdmf\b|vapaalaakeri\w*|painelevy\w*"
CL_P = (r"luista\w*|luisto\w*|loppu\w*|lopussa|lopuillaan|kulunut|kulunee\w*|vaihdettava|vaihtokunno\w*|"
        r"vaihto\w* (?:on )?(?:edessa|tulossa|ajankohtai\w*)|ottaa (?:\w+ )?(?:ylhaal\w*|korkea\w*|ylos)|huono\w*|"
        r"rikki|vika\w*|viallinen|aanta\w*|aanee|kolis\w*|kolkot\w*|raks\w*|helis\w*|tarise\w*|tarina\w*|"
        r"jayk\w*|raskas|tarttu\w*|nyki\w*|ongelm\w*|slip\w*|worn|vapise\w*|pomppi\w*|vuota\w*|"
        r"vaatii korjau\w*|korjattava")
SUSP = (r"alusta\w*|iskunvaimen\w*|iskari\w*|\bjous\w*|tukivar\w*|koiranluu\w*|kallistuksenvakaaj\w*|"
        r"vakaaja\w*|pallonivel\w*|raidetan\w*|puslat?\b|puslien|\bhela\w*|tukilaakeri\w*|ilmajous\w*|"
        r"ilma-alust\w*|etupaa\w*|takapaa\w*|keula\w*|etuakseli\w*|taka-akseli\w*|vetonivel\w*|"
        r"vetoakseli\w*|suspension|shock\w*|strut\w*")
SUSP_P = (r"kolis\w*|kolah\w*|kolk\w*|rutin\w*|rutis\w*|natis\w*|natin\w*|nitis\w*|narin\w*|naris\w*|"
          r"vika\w*|rikki|poikki|katken\w*|aanta\w*|aanee|aanekas|loppu\w*|kulunut|kulunee\w*|vuota\w*|"
          r"vaihdettava|vaihtokunno\w*|loys\w*|valys\w*|knock\w*|clunk\w*|broken|worn")
BRK = (r"jarru(?!valo)\w*|etujarru\w*|takajarru\w*|kasijarru\w*|seisontajarru\w*|jarrulev\w*|jarrupal\w*|jarrusatul\w*|"
       r"jarruputk\w*|jarrulet\w*|\blevyt\b|\bpalat\b|satula\w*|brake\w*|jarrutta\w*|jarrutetta\w*")
BRK_P = (r"vinku\w*|kitis\w*|kirsk\w*|kuluneet|kulunut|loppu\w*|lopussa|vaihdettava|vaihtokunno\w*|"
         r"uusittava|ruostee\w*|ruostu\w*|ruosteise\w*|ruosteinen|rahis\w*|kahis\w*|ratis\w*|tarise\w*|"
         r"tarina\w*|vetaa\w*|jumi\w*|kiinni|vuota\w*|katken\w*|poikki|huono\w*|heikko\w*|heikot|"
         r"rikki|laahaa\w*|syopy\w*|vika\w*|aanta\w*|kolis\w*|kaipaa\w*|kaipaisi|"
         r"worn|squeal\w*|grind\w*")
AC = r"ilmastoin\w*|\bac\b|a/c|klimaat\w*|kompressor\w*|kompur\w*|kylmaaine\w*|kylma-aine\w*|air ?con\w*"
AC_P = (r"ei toimi\w*|ei puhalla kylma\w*|puhaltaa (?:vain )?(?:lamm\w*|kuum\w*|haale\w*)|ei kylmaa|"
        r"ei viilenna|rikki|vika\w*|viallinen|tyhja|vahissa|laiska\w*|heikosti|heikko|huono\w*|vuota\w*|"
        r"ei kytkeydy|vaatii (?:huollon|tayton)|kaipaa\w*|kaipaisi|tarvitsee (?:huollon|tayton)|"
        r"ei ole toiminut|not working|broken")
ELEC = (r"ikkunannost\w*|sahkoikkun\w*|\bikkuna\w*|keskuslukitu\w*|keskuslukko\w*|kaukosaadi\w*|"
        r"\bradio\w*|soitin\w*|navigaat\w*|\bnavi\b|\bnaytto\w*|peruutuskamer\w*|pysakointitutk\w*|"
        r"\btutka\w*|penkinlammit\w*|istuinlammit\w*|lohkolammit\w*|moottorin ?lammit\w*|sisapistoke\w*|takalasin lammit\w*|"
        r"tuulilasin lammit\w*|lisalammit\w*|webasto\w*|eberspa\w*|vakionopeudensaadin\w*|vakkari\w*|"
        r"kattoluukku\w*|kattoikkuna\w*|peili\w*|pyyhki\w*|lasinpesi\w*|kaiutin\w*|kaiuttim\w*|"
        r"bluetooth|lammityslait\w*|puhallin\w*|sisavalo\w*|takaluuk\w*|keyless|\bavain\w*|ovenkah\w*|"
        r"lukitus\w*|mittaristo\w*")
ELEC_P = (r"ei toimi\w*|ei toimin\w*|ei aukea|ei avaudu|ei sulkeudu|ei lukitse|ei lukitu|ei nouse|"
          r"ei laske|ei kaynnisty|ei pala|rikki|rikkinai\w*|vika\w*|viallinen|viallise\w*|epakunno\w*|"
          r"toimii (?:vain |ainoastaan )?(?:huonosti|ajoittain|joskus|satunnaisesti|osittain)|"
          r"toimii ainoastaan|reistail\w*|oikutt\w*|not working|broken")
EXH = (r"pakoputk\w*|pakosarj\w*|pakopuo\w*|\bpako\b|pakoaani\w*|aanenvaimen\w*|katalysaat\w*|"
       r"exhaust\w*|muffler")
EXH_P = (r"reik\w*|reiat|puhki|rikki|vuota\w*|vuoto\w*|aanekas|aanta\w*|paukku\w*|kolis\w*|irti|"
         r"poikki|ruost\w*|vika\w*|huutaa|parise\w*|rapise\w*|kalise\w*|kilise\w*|lahon\w*|loppu|"
         r"vaihdettava|uusittava|hole\w*|leak\w*|loud|rattle\w*")
STEER = (r"ohjaus\w*|ohjaustehost\w*|ohjausvaihde\w*|ohjauslaite\w*|\bratti\w*|\brattia\b|steering")
STEER_P = (r"rikki|vika\w*|jayk\w*|raskas\w*|raskaa\w*|vuota\w*|aanta\w*|aanee|ulis\w*|vinku\w*|"
           r"kolis\w*|valys\w*|vaeltaa|vaeltele\w*|hapuile\w*|loys\w*|epatarkka|lepatt\w*|broken|heavy|stiff")
BELT = r"(?:jakohihn\w*|timing belt|hammashihn\w*)"
BELT_DUE = (r"vaihtamat\w*|ei (?:ole )?(?:viela )?(?:vaihdettu|vaihettu|uusittu|tehty)|"
            r"(?:vaihto|vaihdon|vaihtoa)\b (?:on )?(?:edessa|tulossa|ajankohtai\w*|lahestyy|odottaa|suositel\w*|"
            r"tarpeen|myohassa)|ajankohtai\w*|\bedessa\b|\btulossa\b|ylit\w*|myohassa|ajallisesti|"
            r"pitkaksi|vaihdettava|(?:pitaa|pitaisi|tulisi|kannattaa|kannattaisi) vaihtaa|olisi vaihdettava|"
            r"tarvitsee vaihdon|suositel\w* (?:\w+ ){0,2}(?:vaihtoa|vaihtamaan|vaihtamista)|"
            r"(?:ei|eika)\b.{0,40}?(?:tieto|merkinta|kuitti)|tuntematon|epavarma|epaselva|ei varmuutta|"
            r"overdue|\bdue\b|"
            r"not (?:been )?(?:changed|replaced)|unknown|mennyt yli|yli vaihtovalin")
# "vaihtoväli 8v/120tkm, eli 5/2028 vasta ajankohtainen" — due later, not now.
BELT_NOT_YET = (r"vasta ajankohtai|ei (?:ole )?viela ajankohtai|ajankohtainen vasta|vasta \d|vasta vuonna|"
                r"huolettom\w*|viela paljon")
BELT_DONE = r"vaihdettu|vaihettu|uusittu|vaihdettiin|vaihto tehty|tehty|replaced|changed"
# Another component named between the belt and the cue means the cue is about that part.
OTHER_PART = (r"kytkin|kytkime|jarru|rengas|renkaa|akku|iskari|iskunvaim|laakeri|\blasi|ilmastoin|pakoputk|"
              r"\bkori\b|vaihteist|ruost|katsast|leima|kayttohihna|apulaitehihna|nasta|tuulilas|pyyhkij|"
              r"polttimo|lamppu|oljynvaihto|\bhuolto\b|jakoketju")
WS_CRACK = r"halke(?!amato)\w*|\bhalki\b|halkiny\w*|\bsaro\w*|murtum\w*|crack\w*|haljen\w*"
RUSTW = r"ruost\w*|\brust\w*|lahon\w*|lahoa\w*|korroosi\w*"
RUST_SEVERE_CUE = (r"reik\w*|reiat|puhki|lapi|rakenteel\w*|kantav\w*|runko\w*|kynnys\w*|kynnyks\w*|kotelo\w*|"
                   r"pohja\w*|lattia\w*|tukivar\w*|pilari\w*|jousenkiinn\w*|jousitorn\w*|apurung\w*|palk\w*|"
                   r"hitsat\w*|hitsau\w*|paikattava|korjauskeho\w*|hylky|hylat\w*|vaatii korjau\w*|korjattava|"
                   r"paljon|runsaasti|pahasti|reilusti|rajusti|pahoin|vakava\w*|structural|holes?")
BEARING_X = R(r"ilmastoin|kompur|kompress|laturi|hihnapyor|apulaite|vapaalaakeri|tukilaakeri|turbo|vesipumppu|kytkin")

RULES: list[Rule] = [
    # Free-text mentions of a light being on (generic). Huutokaupat also has the
    # structured question; this catches Nettiauto + extra mentions.
    Rule("warning_light_text", ANY_LIGHT_TEXT,
         exclude=R(r"ei (?:\w+ )?(?:pala|ole|nay|syty)|kuittaa|nollat")),
    Rule("timing_belt_due", R(rf"{BELT}(?:(?!{OTHER_PART}).){{0,100}}?(?:{BELT_DUE})|"
                              rf"(?:{BELT_DUE})(?:(?!{OTHER_PART}).){{0,40}}?{BELT}|"
                              rf"\b(?:ei|eika)\b(?:(?!{OTHER_PART}).){{0,30}}?{BELT}(?:(?!{OTHER_PART}).){{0,40}}?"
                              r"(?:tieto|merkinta|kuitti)"),
         neg_pre=False, neg_post=False, scope="sentence", exclude=R(BELT_NOT_YET)),
    Rule("timing_belt_done", R(rf"{BELT}(?:(?!{OTHER_PART}).){{0,60}}?(?:{BELT_DONE})|"
                               rf"(?:{BELT_DONE})(?:(?!{OTHER_PART}).){{0,40}}?{BELT}"),
         neg_pre=False, neg_post=False, scope="sentence"),
    Rule("timing_chain_issue", R(near(r"jakoketju\w*|timing chain|ketjun?kiristi\w*",
                                      r"aanta\w*|aanee|aani\w*|ramis\w*|kolis\w*|kalis\w*|kilis\w*|helis\w*|"
                                      r"raks\w*|venyny\w*|venahta\w*|vaihdettava|vaihto (?:edessa|tulossa)|"
                                      r"rattle\w*|noise|loppu")), neg_inside=True),
    Rule("gearbox_issue", R(near(GB, GB_P) + r"|vaihteisto(?:vika|vaurio|remontti)\w*"),
         exclude=R(r"vikavalo|ongelmitta|ongelmaton|ongelmat?ta\b|moitteet|kampiakse|synkrohav"), neg_inside=True),
    Rule("gearbox_issue", R(r"vaihtee\w* (?:ei|eivat) (?:mene|vaihdu|pysy|kytkeydy)|ei vaihda\w*|"
                            r"ei mene (?:vaihteelle|vaihteisiin|pakille|ykkoselle|peruutusvaihteelle)|"
                            r"ei liiku (?:eteen|taakse)|(?:\b[dr]\b|vaihtee\w*|vaihde)\W+(?:\w+\W+){0,5}?ei liiku|"
                            rf"(?<![a-z])(?:{GB})(?:\W+\w+){{0,2}}?\W+ei toimi (?:niin |kovin |aivan )?"
                            r"(?:sulavasti|kunnolla|normaalisti|oikein|kuten)|"
                            r"vaihtaa (?:\w+ )?(?:myohaan|isoilla kierroksilla|kovilla kierroksilla)"),
         neg_pre=False, neg_post=False, scope="sentence"),
    Rule("clutch_issue", R(near(CL, CL_P)), neg_inside=True,
         exclude=R(r"magneetti|ilmastoin|kompur|kompress")),
    Rule("clutch_issue", R(rf"(?<![a-z])(?:{CL})(?:\W+\w+){{0,3}}?\W+ei (?:kuitenkaan )?toimi|"
                           r"kytkin\w* (?:\w+ ){0,3}?(?:ilmattava|ilmata|ilmaa\b)|"
                           r"kytkin\w* (?:\w+ ){0,2}?elamaa nahnyt"),
         neg_pre=False, neg_post=False, exclude=R(r"magneetti|ilmastoin|kompur|kompress")),
    Rule("engine_major", R(r"moottori ?vik(?!\w*valo)\w*|moottori ?vauri\w*|moottori ?rikko\w*|"
                           r"moottori ?remont\w* (?:\w+ )?(?:edessa|tarpeen|tulossa|ajankohtai\w*)|"
                           r"jakoketju\w* (?:\w+ ){0,2}?(?:hypan\w*|hyppa\w*|katken\w*|poikki)|"
                           r"moottori\w* (?:on |aivan |taysin |ihan |kokonaan |pahasti )?(?:rikki|hajon\w*|leikan\w*|"
                           r"leikkaa\w*|vaurioitu\w*|kuollut|loppu)|\bkone (?:on |aivan |taysin |ihan )?(?:rikki|hajon\w*|"
                           r"leikan\w*|leikkaa\w*|kuollut|loppu)|konerikko|konevauri\w*|kansitiivis\w*|"
                           r"sylinterinkan\w* (?:\w+ ){0,2}(?:halki|vauri\w*|vuota\w*)|"
                           r"kampiakse\w* (?:\w+ ){0,2}?(?:kaula|laakeri|vauri|hioutu|soike|rikki|katken)\w*|"
                           r"kiertokan\w*|kiertokang\w*|laakerivauri\w*|"
                           r"puristu\w* (?:\w+ ){0,2}(?:heikko|huono|alhai\w*|matala\w*|puuttuu)|head gasket|"
                           r"engine (?:damage|failure|knock\w*|blown|broken|seized)|blown engine|rod knock|"
                           r"vetta oljy\w*|oljy\w* (?:seassa )?vett\w*|majoneesi|vaihtomoottori|"
                           r"moottori\w* (?:\w+ ){0,1}vaihdettava|moottorin vaihto|"
                           r"(?:moottori|kone)\w* (?:\w+ ){0,3}?(?:kolkot\w*|kolkut\w*|kalke\w*|nakut\w*)"),
         exclude=R(r"lammitin|tuki|tyyny|kiinnik|suoja|pelti(?!n alla)|tuuletin|vesipumppu|anturi|valo|"
                   r"ohjausyks|letku|startti|puhallin|ilmastoin|ketjukotelo|(?<!kansi)tiivist|hihna|"
                   r"tunnistin|turvavyo|merkkiaan")),
    # A knock counts as engine damage only when it is placed in the engine;
    # "nakuttaa rattia käännettäessä" is a drive-shaft joint.
    Rule("engine_major", R(r"nakutt\w*|nakutu\w*|kolkutt\w*|kolkotu\w*|kolkott\w*"),
         require=R(r"moottor|\bkone|konepell|tyhjakay|kylmana|kaynnis|engine"),
         exclude=R(r"ratti|rattia|kaanta|kaanto|kaannett|nivel|murros|alusta|startti|turvavyo|merkkiaan|"
                   r"puhallin|ilmastoin|jousi|iskari|vetoakseli|etupaa|takapaa|keula|pyora")),
    Rule("engine_running_issue", R(r"tyhjakay\w* (?:\w+ ){0,3}?(?:epatasai\w*|heittele\w*|tiputtel\w*|sahaa\w*|"
                                   r"vaihtele\w*|nyki\w*|epavakaa\w*|sammu\w*|huono\w*|levoton)|epatasai\w* (?:kay\w*|tyhjakay\w*)|"
                                   r"kay epatasai\w*|\bkatkoo\b|\bkatkoa\b|katkoil\w*|katkonta|savutt\w*|savuaa|"
                                   r"(?:sinista|mustaa|valkoista) savua|vetaa huonosti|veto (?:on )?heikko|ei (?:jaksa )?veda|"
                                   r"tehoton|vikatila\w*|hatatila\w*|limp ?mode|"
                                   r"turbo\w* (?:\w+ ){0,2}(?:vinku\w*|ulvo\w*|vihel\w*|rikki|vika\w*|vuota\w*|ei toimi|"
                                   r"aanta\w*|valys\w*|loppu|hajon\w*)|ahtopain\w* (?:\w+ ){0,2}(?:vika|matala|liian|"
                                   r"ongelm\w*|herja\w*|alhai\w*)|oljyn ?kulutu\w*|kuluttaa oljy\w*|oljya kuluu|"
                                   r"polttaa oljy\w*|kayntihairi\w*|sytytyskatk\w*|misfire|rough idle|"
                                   r"egr\w* (?:\w+ ){0,2}(?:vika|tukossa|rikki|vaihdettava|jumissa|ongelm\w*)|"
                                   r"suutin\w* (?:\w+ ){0,1}(?:vika\w*|vuota\w*|rikki|vaihdettava)|sammuilee|"
                                   r"sammuu (?:ajossa|kesken|tyhjakay\w*|itsestaan|valilla|ajoittain)|"
                                   r"saattaa sammua|kylmakaynnisty\w* (?:\w+ ){0,2}(?:vaike\w*|huono\w*|ongelm\w*)|"
                                   r"vaikea kaynnist\w*|kaynnistyy (?:huonosti|vaikeasti|heikosti)")),
    Rule("non_runner", R(r"ei kaynnisty\w*|ei kaynnistynyt|ei lahde kayntiin|ei lahtenyt kayntiin|"
                         r"kaynnistymat\w*|ei starttaa|startti ei|ei pysy kaynnissa|"
                         r"(?:auto|ajoneuvo|moottori|kone)\s+(?:\w+\s+){0,2}ei (?:kay|liiku|kulje)\b"
                         r"(?!\s+(?:kunnolla|hyvin|tasaisesti|normaalisti|puhtaasti|kuin|oikein|kaikilla|nain|"
                         r"taysin|tasan|ihan))|"
                         r"ei liiku (?:eteen|taakse|minnekaan|mihinkaan|omin voimin|omin avuin|paikaltaan)|"
                         r"ei kulje (?:eteen|taakse|omin voimin)|liikkumaton|ei (?:ole )?ajokunno\w*|"
                         r"ei ajokuntoinen|ajokelvot\w*|ajokyvyt\w*|hinattava|vaatii hinauksen|lavetilla|"
                         r"lavetti\w*|hinurilla|does not start|doesn'?t start|won'?t start|non[- ]runner|"
                         r"not running|does not run|doesn'?t run|needs towing"),
         neg_pre=False, neg_post=False,
         exclude=R(r"webasto|lammitin|lisalammit|puhallin|ilmastoin|radio|navi|kamera|tuuletin|eberspa|"
                   r"ikkuna|penkki|pyyhkij|kaukosaadin|luukku|lukko|peili|kaiutin|apuvirra|apuvirta|"
                   r"renka|nasta")),
    Rule("not_roadworthy", R(r"ei (?:ole )?(?:tie)?liikennekelpoi\w*|ajokiell\w*|kayttokiel\w*|"
                             r"liikennekiel\w*|not roadworthy"), neg_pre=False, neg_post=False),
    Rule("inspection_invalid", R(r"katsastamat\w*|ei (?:ole )?katsastettu|ei katsastusta|"
                                 r"katsastus\w* (?:\w+ ){0,2}?(?:umpeutu\w*|vanhentu\w*|eraantyny\w*|loppuny\w*|"
                                 r"mennyt umpeen|umpeen|ei voimassa|rauennut|raukea\w*)|"
                                 r"leima\w* (?:\w+ ){0,2}?(?:loppuny\w*|loppu|mennyt umpeen|umpeen|vanhentu\w*|"
                                 r"umpeutu\w*)|ilman (?:voimassa olevaa )?(?:katsastusta|leimaa)|leimaton|"
                                 r"maaraaikaiskatsastus suorittamatta|inspection (?:expired|overdue)|"
                                 r"no (?:valid )?inspection"), neg_pre=False, neg_post=False),
    Rule("inspection_failed", R(r"hylat\w*|hylky ?lapu\w*|hylkylappu\w*|hylkays\w*|hylkaav\w*|\bhylky\b|"
                                r"ajoaika\w* (?:\w+ ){0,2}?(?:mennyt umpeen|umpeutu\w*|paattyny\w*|loppuny\w*)|"
                                r"ei mennyt (?:\w+ ){0,2}?(?:katsastuksesta|leimalta|lapi)|ei paassyt (?:\w+ )?lapi|"
                                r"failed inspection|inspection failed|uusintakatsast\w*|"
                                r"ajo-?oikeu\w* (?:\w+ ){0,4}?saakka|ajoaika\w* (?:\w+ ){0,3}?\d|"
                                r"katsastuksessa (?:ilmen\w*|havait\w*|todet\w*) (?:\w+ ){0,1}vi\w*"),
         neg_pre=True, neg_post=False, exclude=R(r"hylkyyn asti|tarjous|huuto"),
         require=R(r"katsast|leima|inspect|hylky|hylkay|ajo-?oikeu|ajoaika|vakavuus|tarkastuskohde")),
    Rule("rust", R(r"ruost\w*|\brust\w*|kupla\w*|kuplia|kupru\w*|kukki\w*|kukkimi\w*|lahon\w*|lahoa\w*"),
         exclude=R(r"ruosteeto\w*|ruosteetto\w*|ruostesuoj\w*|ruosteenesto\w*|jarru|levyt|levyissa|levyja|"
                   r"pakoputk|pakosarj|vante|ruuvi|pultti|kiinnitys|ruostumato\w*|(?:volkswagen|vw) kupl")),
    # Structural / inspection-relevant rust: a severity cue (holes, sills, floor,
    # subframe, "a lot of", inspection remark, ...) within a few words of a rust
    # word. Rocker-panel ("helmat") or wheel-arch rust on its own is common and
    # counted as cosmetic.
    Rule("rust_severe", R(near(RUSTW, RUST_SEVERE_CUE, 5) +
                          r"|ruostereik\w*|puhkiruost\w*|lapiruost\w*|ruostunut (?:puhki|lapi)|\blahon\w*"),
         scope="sentence", neg_pre=True, neg_post=True,
         exclude=R(r"pintaruost\w*(?!.*(?:reik|puhki|kotelo|pohja))|keskikotelo|konsoli|kivenhakkau|kivenisk|"
                   r"ruosteeto|ruosteetto|ruostesuoj|(?:pohja|kori|runko)\w* (?:\w+ ){0,3}?(?:hyva|kova|fiksu|"
                   r"siisti|ehja|kunnossa|terve|massat|suojat)|\bolisi\b|korjatt(?:u|iin)\b")),
    Rule("crash_damage", R(r"kolar(?!iton|ivapa|oimato)\w*|kolaroi(?!mato)\w*|tormay\w*|tormann\w*|tormas\w*|"
                           r"peltivauri\w*|korivauri\w*|rakennevauri\w*|copart|"
                           r"\bojaan\b|\bojassa\b|ulosajo\w*|kierahta\w*|\bcrash\w*|collision|accident\w*|"
                           r"rakenteelli\w* vauri\w*|(?:hirve|hirvi|peura)\w* (?:\w+ )?(?:osu|tormas|kolar)\w*|"
                           r"osu\w* (?:\w+ )?(?:hirveen|peuraan)|"
                           r"(?:poistettu (?:\w+ ){0,2}?)?vaurioituneena (?:\w+ )?(?:poisto|poistettu|\d)|"
                           r"poistettu (?:\w+ ){0,2}?vaurioituneena|runkoaisa\w* (?:\w+ ){0,2}?(?:ei kohdallaan|"
                           r"vino|vaurio\w*|korjattu)|kolarikorjat\w*"),
         exclude=R(r"tormayksenesto\w*|tormaysvaroit\w*|tormayksen ?varoit\w*|tormaystyyn\w*|"
                   r"collision (?:warning|avoidance|assist|mitigation)|tormaysvaroitin")),
    # Minor knocks ("pieni osuma") count as dents, not as a crash.
    Rule("body_dents", R(r"lommo\w*|kolhu\w*|painaum\w*|kolhiintu\w*|kolhaistu\w*|\bdent\w*|"
                         r"\bosum(?:a|aa|an|ia|ien)\b")),
    Rule("paint_damage", R(r"maalivi\w*|lakkavi\w*|lakka\w* (?:\w+ ){0,1}(?:irto\w*|lahte\w*|kuoriutu\w*|"
                           r"haalistu\w*|loppu)|maali\w* (?:\w+ ){0,1}(?:lahte\w*|irto\w*|kuoriutu\w*|"
                           r"haalistu\w*|loppu)|kuoriutu\w*|haalistu\w*|lakaton|clear ?coat")),
    # Free text must name the windshield next to the crack word, so a cracked
    # bumper / mirror / dashboard is not counted. (The Huutokaupat windshield
    # answer is already about the windshield and uses WS_FIELD_RULE below.)
    Rule("windshield_crack", R(near(r"tuulilas\w*|\blasi\w*|windshield|windscreen", WS_CRACK, 4)),
         exclude=R(r"puskur|peili|kojelau|kojetau|umpio|ajovalo|lokasuoj|sivulasi|takalasi|kattoluuk")),
    Rule("water_ingress", R(r"kosteu\w*|kostea\w*|vesivuot\w*|vetta (?:\w+ ){0,3}?(?:sisalle|sisaan|lattia\w*|"
                            r"matto\w*|tulee|kertyy|keraantyy)|vuotaa sisaan|vuotaa vetta|homee\w*|homeh\w*|"
                            r"\bhome\b|homeen|mark\w* (?:matot|matto|lattia)|water (?:leak|ingress)|"
                            r"huurtu\w*|lattia (?:on )?mark\w*|tulva\w*|vesivahin\w*|flood\w*"),
         exclude=R(r"jaahdytys|kosteuspyyh|valo|lamppu|lyhty|ikkunat huurt")),
    Rule("interior_damage", R(r"repe\w*|reven\w*|ratken\w*|rikki|rikkinai\w*|\breika\w*|reiat|palojal\w*|"
                              r"polttojal\w*|tupakan ?polt\w*|\btorn\b|ripped"),
         require=R(r"penk|istui|verhoil|sisust|sisatil|katto|\bmatto|kojelau|nahka|seat|interior|"
                   r"ovipahvi|ovivera|kattoverhoil|kangas|sisalla")),
    Rule("ac_issue", R(near(AC, AC_P, 3))),
    Rule("oil_leak", R(r"oljyvuo\w*|vuota\w* (?:\w+ ){0,2}?oljy\w*|oljy\w* (?:\w+ ){0,2}?vuota\w*|oljyhiko\w*|"
                       r"hikoile\w* (?:\w+ ){0,1}oljy\w*|oljy\w* (?:\w+ ){0,1}hikoil\w*|oil leak\w*|leaks oil|"
                       r"oljytahr\w*|oljyinen|tiputtaa oljy\w*|oljylammiko\w*|hikoil\w*")),
    Rule("coolant_issue", R(r"jaahdytysnest\w* (?:\w+ ){0,3}?(?:vuota\w*|vuoto\w*|haviaa|katoaa|kuluu|haihtuu|"
                            r"loppuu|vahene\w*|lisatta\w*|tippuu|vajaa)|vuota\w* (?:\w+ ){0,2}?jaahdytysnest\w*|"
                            r"jaahdytysnestevuo\w*|nestevuo\w*|vesipumppu (?:\w+ ){0,2}?(?:vuota\w*|rikki|vika\w*|"
                            r"aanta\w*)|jaahdytin (?:\w+ ){0,2}?(?:vuota\w*|rikki|puhki)|coolant (?:leak|loss)|"
                            r"ylikuumen\w*|kiehu\w*|keittaa|kuumenee")),
    Rule("brakes_issue", R(near(BRK, BRK_P, 3)), neg_inside=True),
    Rule("brakes_issue", R(r"(?:kasijarru|seisontajarru|jarru(?!valo))\w* (?:\w+ ){0,1}ei (?:pida|toimi)"),
         neg_pre=False, neg_post=False),
    Rule("suspension_issue", R(near(SUSP, SUSP_P, 4) + r"|kolisee (?:\w+ ){0,2}(?:etupaa\w*|takapaa\w*|"
                               r"alustasta|toyssy\w*|keula\w*)"),
         exclude=R(r"kolhu|lommo|naarmu|puskuri|maali|lakka"), neg_inside=True),
    Rule("wheel_bearing", R(near(r"laakeri\w*|pyoranlaakeri\w*|napalaakeri\w*|bearing",
                                 r"aanta\w*|aanee|aani\w*|humis\w*|humina\w*|ulis\w*|jyris\w*|jyrin\w*|kolis\w*|"
                                 r"rousk\w*|ujel\w*|vaihdettava|vaihtokunno\w*|loppu\w*|kulunut|vika\w*|rikki|"
                                 r"noise|hum\w*", 4)),
         exclude=BEARING_X, neg_inside=True),
    Rule("exhaust_issue", R(near(EXH, EXH_P, 3)), neg_inside=True),
    Rule("steering_issue", R(near(STEER, STEER_P, 3) + r"|vet\w* (?:hieman |selvasti |vahan |hiukan )?"
                             r"(?:oikealle|vasemmalle|sivulle)|vaeltaa|vaeltele\w*"), neg_inside=True),
    Rule("electrical_minor", R(near(ELEC, ELEC_P, 3))),
    Rule("dpf_issue", R(near(r"\bdpf\w*|hiukkassuod\w*|hiukkasloukk\w*|partikkelisuod\w*|nokisuod\w*|\bfap\b|\bgpf\b",
                             r"tukos\w*|tukkeu\w*|tukossa|vika\w*|viallinen|vaihdettava|ongelm\w*|"
                             r"regenero\w*|poistettu|tyhjennet\w*|tyhjennys|herja\w*|valo\w*|rikki|taynna|"
                             r"clog\w*|blocked|removed|full|puhdist\w*|vikakoodi\w*", 4)), neg_inside=True),
    Rule("emissions_issue", R(near(r"adblue\w*|ad-blue|\bscr\b|\bnox\w*|\burea\b|paastojarjest\w*|"
                                   r"pakokaasujarjest\w*|moottorin ohjelmoin\w*",
                                   r"vika\w*|rikki|herja\w*|poistettu|vaihdettava|ongelm\w*|valo\w*|"
                                   r"varoitu\w*|pumppu\w*|kitey\w*|kiteet|muutoks\w*|muokat\w*|ohjelmoitu|"
                                   r"tankki\w*", 4)), neg_inside=True),
    Rule("battery_weak", R(r"akku\w* (?:\w+ ){0,2}?(?:heikko|heikk\w*|tyhja\w*|loppu\w*|vaihdettava|"
                           r"vaihtokunno\w*|kuollut|ei pida|huono\w*)|apuvirra\w*|apuvirta\w*|starttikaapel\w*|"
                           r"laturi\w* (?:\w+ ){0,2}?(?:vika|rikki|ei lataa|ei toimi)|ei lataa akkua|"
                           r"battery (?:weak|dead|flat)|jump ?start\w*")),
    Rule("odometer_uncertain", R(r"mittari\w* (?:\w+ ){0,3}?(?:ei (?:ole )?(?:tarkkaa |varmaa |tarkempaa )?"
                                 r"tieto\w*|ei pida paikkaansa|epavarma\w*|vaihdettu|ei toimi|vaarin|kiertany\w*|"
                                 r"nollat\w*|epaluotettav\w*|ei tiedossa|ei vastaa)|kilometr\w* (?:\w+ ){0,3}?"
                                 r"(?:ei (?:ole )?(?:tarkkaa |varmaa )?tieto\w*|epavarm\w*|tuntemat\w*|ei pida paikkaansa)|"
                                 r"todellinen ajomaar\w* (?:\w+ ){0,2}?(?:tuntematon|ei tiedossa)|"
                                 r"odometer\w* (?:\w+ ){0,2}?(?:replaced|broken|incorrect|unknown)|"
                                 r"mileage (?:unknown|not (?:known|verified|accurate))"),
         neg_pre=False, neg_post=False),
    Rule("project_for_parts", R(r"projekti\w*|varaosiksi|varaosa-?auto\w*|\bosiksi|korjattavaksi|"
                                r"korjausprojekt\w*|purettavaksi|romutettava\w*|for parts|project car|parts car|"
                                r"kunnostettava\w*|kunnostuskoh\w*|korjattava auto")),
    Rule("tyres_worn", R(r"renka\w* (?:\w+ ){0,2}?(?:loppu\w*|kulunee\w*|kulunut|huono\w*|vaihdettava|"
                         r"vaihtokunno\w*|lopussa|laittom\w*|sileat|puhki|rikki|halki)|nasto\w* (?:\w+ ){0,2}?"
                         r"(?:poikki|kulunu\w*|puuttu\w*|loppu)|nypit\w* nast\w*|kulutuspinn\w* (?:\w+ ){0,1}?"
                         r"(?:loppu\w*|vahissa|laittom\w*)")),
]
RULES_BY_NAME: dict[str, list[Rule]] = {}
for _r in RULES:
    RULES_BY_NAME.setdefault(_r.name, []).append(_r)


WS_FIELD_RULE = Rule("windshield_crack", R(WS_CRACK))   # for the checklist's windshield answer only


def rule_hits(name: str, sents: list[str]) -> list[str]:
    return [h for r in RULES_BY_NAME[name] for h in r.hits(sents)]


LIGHT_FLAGS = list(LIGHT_PATTERNS) + ["light_unspecified"]
TEXT_FLAGS = list(RULES_BY_NAME)

# ─────────────────────────── Huutokaupat structured fields ───────────────────────────

HK_FIELDS = {
    "light": "Palaako jokin vikavalo",
    "inspection": "Katsastettu",
    "roadworthy": "Tieliikennekelpoisuus",
    "deregistered": "Poistettu liikenteestä",
    "insurance": "Liikennevakuutus",
    "service_book": "Huoltokirja",
    "import": "Tuontiauto",
    "reregistered": "Rekisteröity uudelleen",
    "unpaid_tax": "Veroja maksamatta",
    "keys": "Avainten lukumäärä",
    "summer_tyres": "Kesärenkaat",
    "winter_tyres": "Talvirenkaat",
    "windshield": "Tuulilasissa halkeamia tai kiveniskemiä",
    "body": "Korissa kulumia, ruostetta tai kolhuja",
    "interior": "Sisätiloissa kulumia tai jotain rikki",
}


def _yes(v: str | None) -> bool:
    return bool(v) and fold(v).startswith("kyll")


def _after_answer(v: str | None) -> str:
    """'Kyllä, moottorin vikavalo palaa' -> 'moottorin vikavalo palaa'."""
    if not v:
        return ""
    return re.sub(r"^\s*(?:kyll[äa]|ei(?: ole)?)\s*,?\s*", "", v, flags=re.IGNORECASE)


def classify_light_text(text: str) -> dict[str, int]:
    t = fold(text)
    return {k: int(bool(rx.search(t))) for k, rx in LIGHT_FIELD_RX.items()}


def inspection_expired(answer: str | None, end: date | None) -> int | None:
    """Huutokaupat 'Katsastettu': 'Kyllä, seuraava katsastus 4/2027' or 'Ei, ...'."""
    if not answer:
        return None
    f = fold(answer)
    if f.startswith("ei"):
        return 1
    m = re.search(r"seuraava katsastus\s*(\d{1,2})\s*/\s*(\d{4})", f)
    if m and end is not None:
        mo, yr = int(m.group(1)), int(m.group(2))
        return int((yr, mo) < (end.year, end.month))
    return 0


@dataclass
class FlagResult:
    flags: dict[str, int] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)


def flags_from_text(text: str, result: FlagResult | None = None, *, source_tag: str = "text") -> FlagResult:
    """Run every free-text rule (and light-type detection with light context)."""
    res = result or FlagResult()
    sents = sentences(text)
    for rule in RULES:
        h = rule.hits(sents)
        if h:
            res.flags[rule.name] = 1
            res.evidence.setdefault(rule.name, f"[{source_tag}] {h[0]}")
    # Light types mentioned in free text. The clause must say a light is on or a
    # warning is shown ("xenon-ajovalot" is equipment, not a fault) — or be a
    # short list item ("abs, esp ja moottorin vikavalot palavat") inside a
    # sentence that explicitly says warning lights are on.
    for s in sents:
        if not LIGHT_CTX.search(s):
            continue
        sentence_negated = bool(_LIGHT_OFF.search(s))
        listed = bool(_LIGHTS_ON_SENTENCE.search(s)) and not sentence_negated
        for c in clauses(s):
            if not (_LIGHT_ON.search(c) or (len(c) < 30 and listed)):
                continue
            if _LIGHT_OFF.search(c):
                continue
            for k, rx in LIGHT_RX.items():
                m = rx.search(c)
                if not m:
                    continue
                if NEG_PRE.search(c[max(0, m.start() - 30):m.start()]) or NEG_POST.match(c[m.end():m.end() + 50]):
                    continue
                res.flags[k] = 1
                res.evidence.setdefault(k, f"[{source_tag}] {c[:120]}")
    return res


_LIGHT_ON = R(r"\bpalaa\b|palavat|paloi|syttyy|syttyi|syttynyt|sytytt\w*|vilkku\w*|vilkutt\w*|herja\w*|"
              r"ilmoitta\w*|ilmoitus|vikavalo\w*|varoitusvalo\w*|merkkivalo\w*|hairiovalo\w*|vikakoodi\w*|"
              r"warning|light (?:is )?on|pimea\w*|palanut|palaneen|ei toimi|rikki|vika\b|vikaa\b|tauluun|"
              r"mittaristo\w*")
_LIGHTS_ON_SENTENCE = R(r"(?:vika|varoitus|merkki|hairio)valo\w* (?:\w+ )?(?:palaa|palavat|paloi|syttyy|syttyi)|"
                        r"(?:palaa|palavat|paloi|syttyy|syttyi) (?:\w+ )?(?:vika|varoitus|merkki|hairio)?valo|"
                        r"vikavalo\w*|varoitusvalo\w*|herjaa")
# A light that is off, was reset, or whose fault was fixed.
_LIGHT_OFF = R(r"ei (?:\w+ )?(?:pala|syty|ole|nay)\b|kuitat\w*|nollat\w*|korjattu|vaihdettu|uusittu|"
               r"poistettu|sammunut|sammui|\b(?:ei|eika|ilman)\b[^,]{0,25}valo")


def huutokaupat_flags(condition: dict, faults_text: str | None, title: str | None,
                      raw_huuto: dict | None, end: date | None) -> FlagResult:
    """All fault flags for one Huutokaupat auction."""
    res = FlagResult()
    g = lambda key: condition.get(HK_FIELDS[key])  # noqa: E731

    # Structured warning light, and which light from the seller's own words.
    light_ans = g("light")
    res.flags["warning_light_any"] = int(_yes(light_ans))
    if res.flags["warning_light_any"]:
        lt = classify_light_text(_after_answer(light_ans))
        for k, v in lt.items():
            if v:
                res.flags[k] = 1
                res.evidence.setdefault(k, f"[light] {_after_answer(light_ans)[:120]}")

    exp = inspection_expired(g("inspection"), end)
    if exp:
        res.flags["inspection_invalid"] = 1
        res.evidence["inspection_invalid"] = f"[field] {g('inspection')[:80]}"
    if g("inspection") and re.search(r"hyl[aä]t|hylky|ei mennyt", fold(g("inspection"))):
        res.flags["inspection_failed"] = 1
        res.evidence["inspection_failed"] = f"[field] {g('inspection')[:80]}"
    if g("roadworthy") and "ei ole tieliikennekelpoinen" in fold(g("roadworthy")):
        res.flags["not_roadworthy"] = 1
        res.evidence["not_roadworthy"] = "[field] Ajoneuvo ei ole tieliikennekelpoinen"

    # Admin / paperwork attributes (kept as controls, reported separately).
    res.flags["deregistered"] = int(_yes(g("deregistered")))
    res.flags["no_insurance"] = int(bool(g("insurance")) and fold(g("insurance")).startswith("ei"))
    res.flags["no_service_book"] = int(bool(g("service_book")) and fold(g("service_book")).startswith("ei"))
    res.flags["import_car"] = int(_yes(g("import")))
    res.flags["reregistered"] = int(_yes(g("reregistered")))
    res.flags["unpaid_tax"] = int(_yes(g("unpaid_tax")))
    k = re.search(r"(\d+)\s*kpl", fold(g("keys") or ""))
    res.flags["one_key"] = int(bool(k) and int(k.group(1)) <= 1)
    res.flags["no_summer_tyres"] = int(bool(g("summer_tyres")) and fold(g("summer_tyres")).startswith("ei"))
    res.flags["no_winter_tyres"] = int(bool(g("winter_tyres")) and fold(g("winter_tyres")).startswith("ei"))
    pm = (raw_huuto or {}).get("päästömuunneltu")
    res.flags["emissions_modified"] = int(_yes(pm))

    # Field texts are scoped: windshield text can only produce windshield flags, etc.
    ws = _after_answer(g("windshield")) if _yes(g("windshield")) else ""
    if ws:
        h = WS_FIELD_RULE.hits(sentences(ws))
        if h:
            res.flags["windshield_crack"] = 1
            res.evidence["windshield_crack"] = f"[windshield] {h[0]}"
    body = _after_answer(g("body")) if _yes(g("body")) else ""
    interior = _after_answer(g("interior")) if _yes(g("interior")) else ""
    for name in ("rust", "rust_severe", "crash_damage", "body_dents", "paint_damage"):
        h = rule_hits(name, sentences(body))
        if h:
            res.flags[name] = 1
            res.evidence.setdefault(name, f"[body] {h[0]}")
    if interior:
        h = rule_hits("interior_damage", [s + " sisatilat" for s in sentences(interior)])
        if h:
            res.flags["interior_damage"] = 1
            res.evidence["interior_damage"] = f"[interior] {h[0]}"
        h = rule_hits("water_ingress", sentences(interior))
        if h:
            res.flags["water_ingress"] = 1
            res.evidence["water_ingress"] = f"[interior] {h[0]}"

    # Free text: faults section + title + service-book note (timing belt info
    # often lives there).
    free = "\n".join(filter(None, [title, faults_text, _after_answer(g("service_book"))]))
    flags_from_text(free, res, source_tag="faults")

    if res.flags.get("warning_light_any"):
        typed = any(res.flags.get(k) for k in LIGHT_PATTERNS)
        res.flags["light_unspecified"] = int(not typed)
    return finalize(res)


def nettiauto_flags(title: str | None, usp: str | None, description: str | None,
                    info: dict | None, card_engine: str | None, fetched: date | None) -> FlagResult:
    res = FlagResult()
    flags_from_text("\n".join(filter(None, [title, usp, description])), res, source_tag="desc")
    typed = [k for k in LIGHT_PATTERNS if res.flags.get(k)]
    res.flags["warning_light_any"] = int(bool(typed) or bool(res.flags.get("warning_light_text")))
    res.flags["light_unspecified"] = int(res.flags["warning_light_any"] and not typed)
    if card_engine and "ei tieliikennekelpoinen" in fold(card_engine):
        res.flags["not_roadworthy"] = 1
        res.evidence.setdefault("not_roadworthy", "[card] Ei tieliikennekelpoinen")
    others = (info or {}).get("Muut") or []
    if isinstance(others, list):
        sb = [o for o in others if fold(o).startswith("huoltokirja")]
        if sb and re.search(r"ei\b|puuttuu", fold(sb[0])):
            res.flags["no_service_book"] = 1
    return finalize(res)


def finalize(res: FlagResult) -> FlagResult:
    """Derived columns + make every known flag present (0/1)."""
    f = res.flags
    if f.get("rust_severe"):
        f["rust"] = 1
    f["rust_cosmetic"] = int(bool(f.get("rust")) and not f.get("rust_severe"))
    # "changed in 2016, so by age it's overdue" is due, not done.
    if f.get("timing_belt_due"):
        f["timing_belt_done"] = 0
    for k in ALL_FLAGS:
        f.setdefault(k, 0)
    return res


ADMIN_FLAGS = ["deregistered", "no_insurance", "no_service_book", "import_car", "reregistered",
               "unpaid_tax", "one_key", "no_summer_tyres", "no_winter_tyres", "emissions_modified"]
ALL_FLAGS = (["warning_light_any"] + LIGHT_FLAGS + TEXT_FLAGS + ["rust_cosmetic"] + ADMIN_FLAGS)
ALL_FLAGS = list(dict.fromkeys(ALL_FLAGS))

# Human-readable labels for the report.
LABELS = {
    "warning_light_any": "Any warning light on (seller checklist)",
    "light_engine": "Engine / check-engine light",
    "light_abs_esp": "ABS / ESP / traction-control light",
    "light_airbag": "Airbag (SRS) light",
    "light_tpms": "Tyre-pressure (TPMS) light",
    "light_service": "Service-reminder light",
    "light_bulb": "Bulb-failure light",
    "light_glow_plug": "Glow-plug light",
    "light_dpf": "DPF (particulate filter) light",
    "light_gearbox": "Gearbox warning light",
    "light_brake": "Brake / parking-brake / pad-wear light",
    "light_battery": "Battery / charging / start-stop light",
    "light_oil": "Oil-pressure / oil-level light",
    "light_coolant": "Coolant / temperature light",
    "light_steering": "Power-steering light",
    "light_suspension": "Suspension (air/adaptive) light",
    "light_emissions": "AdBlue / emissions light",
    "light_unspecified": "Warning light, type not stated",
    "warning_light_text": "Warning light mentioned in free text",
    "timing_belt_due": "Timing belt due / unknown",
    "timing_chain_issue": "Timing-chain noise / stretched",
    "gearbox_issue": "Gearbox problem",
    "clutch_issue": "Clutch / flywheel worn",
    "engine_major": "Major engine damage (knock, head gasket, …)",
    "engine_running_issue": "Engine running issue (misfire, smoke, turbo, EGR, …)",
    "non_runner": "Won't start / won't move",
    "not_roadworthy": "Not roadworthy / driving ban",
    "inspection_invalid": "Inspection (katsastus) not valid",
    "inspection_failed": "Inspection failed (hylätty)",
    "rust": "Rust (any)",
    "rust_cosmetic": "Rust, cosmetic only",
    "rust_severe": "Rust, structural / holes / sills",
    "crash_damage": "Crash / collision damage",
    "body_dents": "Dents",
    "paint_damage": "Paint / clear-coat damage",
    "windshield_crack": "Windshield cracked",
    "water_ingress": "Water leak / damp / mould inside",
    "interior_damage": "Interior torn / broken",
    "ac_issue": "A/C not working properly",
    "oil_leak": "Oil leak / sweating",
    "coolant_issue": "Coolant leak / overheating",
    "brakes_issue": "Brakes worn / noisy / sticking",
    "suspension_issue": "Suspension knocks / broken parts",
    "wheel_bearing": "Wheel-bearing noise",
    "exhaust_issue": "Exhaust leak / hole",
    "steering_issue": "Steering problem / pulls",
    "electrical_minor": "Minor electrics broken (windows, locks, radio, …)",
    "dpf_issue": "DPF problem (text)",
    "emissions_issue": "AdBlue / emissions-system problem (text)",
    "battery_weak": "Weak battery / needs jump start",
    "odometer_uncertain": "Odometer reading uncertain",
    "project_for_parts": "Sold as project / for parts / to repair",
    "tyres_worn": "Tyres worn / illegal",
    "deregistered": "Deregistered (off the road)",
    "no_insurance": "No valid traffic insurance",
    "no_service_book": "No service book",
    "import_car": "Imported car",
    "reregistered": "Re-registered",
    "unpaid_tax": "Unpaid vehicle tax",
    "one_key": "Only one key",
    "no_summer_tyres": "No summer tyres",
    "no_winter_tyres": "No winter tyres",
    "emissions_modified": "Emissions system modified (checklist)",
}


def parse_condition(cj: str | None) -> dict:
    try:
        return json.loads(cj) if cj else {}
    except (TypeError, ValueError):
        return {}
