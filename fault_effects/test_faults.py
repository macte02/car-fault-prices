"""Regression examples for the fault rules: `python -m fault_effects.test_faults`.

Each case is a real phrasing seen in Huutokaupat / Nettiauto text (several
taken from the round-1 hand-check) with the flags it must produce.
"""

from __future__ import annotations

from fault_effects import faults as F

IGNORE = set(F.ADMIN_FLAGS) | {"warning_light_any", "light_unspecified", "warning_light_text"}

CASES = [
    ("Moottorin vikavalo palaa, ABS valo ei pala", {"light_engine"}),
    ("Ei vikavaloja!", set()),
    ("Moottori käy hyvin, ei vikavaloja", set()),
    ("Jakohihna vaihdettu 2016, eli ajallisesti mennyt pitkäksi.", {"timing_belt_due"}),
    ("Jakohihna vaihdettu 2021, kytkin vaihdettava.", {"timing_belt_done", "clutch_issue"}),
    ("Jakohihnan vaihto edessä.", {"timing_belt_due"}),
    ("Huoltokirja ei ole, eikä siis jakohihnan vaihdosta parempaa tietoa.", {"timing_belt_due"}),
    ("Jakohihnan vaihtoväliksi suositellaan ilmeisesti 10 vuotta tai 150 000 km", set()),
    ("jakohihnan vaihtoväli 8v/120tkm, eli 5/2028 vasta ajankohtainen", set()),
    ("sekä jakohihna tulisi vaihtaa", {"timing_belt_due"}),
    ("Vaihteisto toimii hyvin, ei ongelmia.", set()),
    ("kaikki vaihteet menee ongelmitta silmään", set()),
    ("Automaattivaihteisto nykii kylmänä", {"gearbox_issue"}),
    ("vaihteisto ei pidä ääntä", set()),
    ("Vaihteet ei mene ykköselle", {"gearbox_issue"}),
    ("vaihdelaatikko hiukan temppuilee", {"gearbox_issue"}),
    ("vaihdelaatikko ei toimi niin sulavasti kuin pitäisi", {"gearbox_issue"}),
    ("Kytkin luistaa selkeästi", {"clutch_issue"}),
    ("Kytkin toimii normaalisti", set()),
    ("kytkinpohjaiselta ongelmalta ei vaikuta", set()),
    ("kytkin ei kuitenkaan toimi normaalisti ja vaatii korjausta", {"clutch_issue"}),
    ("Ei ruostetta", set()),
    ("Paljon ruostetta kynnyksissä", {"rust", "rust_severe"}),
    ("helmoissa ruosteen alkua", {"rust", "rust_cosmetic"}),
    ("Paikoin hieman pintaruostetta", {"rust", "rust_cosmetic"}),
    ("Jarrulevyt ruosteessa", {"brakes_issue"}),
    ("Ei käynnisty, startti ei edes naksahda", {"non_runner"}),
    ("auto ei käy kunnolla koska yksi sylinteri ei ole pelissä", set()),
    ("nouto trailerilla", set()),
    ("Webasto ei käynnisty", {"electrical_minor"}),
    ("Auto on ostettu Copartista kolarivaurioituneena", {"crash_damage"}),
    ("vasempi sivu pieni osuma", {"body_dents"}),
    ("törmäyksenestojärjestelmästä häiriö", set()),
    ("Ei kolaroitu", set()),
    ("Kolariton auto", set()),
    ("hirveä määrä naarmuja", set()),
    ("Keulassa lakkavikaa", {"paint_damage"}),
    ("Keulassa kolisee joku töyssyissä", {"suspension_issue"}),
    ("Ilmastointi ei toimi", {"ac_issue"}),
    ("Ilmastointi puhaltaa kylmää", set()),
    ("Ilmastointi puhaltaa viileää mutta kylmäaine vähissä", {"ac_issue"}),
    ("Lyhyellä koeajolla havaitsimme: moottorin vikavalo palaa", {"light_engine"}),
    ("Ohjaustehostin rikki, rattia jäykkä kääntää", {"steering_issue"}),
    ("Moottori toimii hyvin mutta kytkin aivan loppu.", {"clutch_issue"}),
    ("Moottorin lämmitin ei toimi", {"electrical_minor"}),
    ("Mootorissa öljyhikoilua", {"oil_leak"}),
    ("Ajokiellossa (jarruputki katkennut)", {"not_roadworthy", "brakes_issue"}),
    ("EGR venttiili vaihdettu, vikavalo ei pala", set()),
    ("abs, esp ja moottorin vikavalot palavat", {"light_abs_esp", "light_engine"}),
    ("Tuulilasi halki", {"windshield_crack"}),
    ("Akku heikko, apuvirralla käyntiin", {"battery_weak"}),
    ("mittarilukemasta ei tarkkaa tietoa", {"odometer_uncertain"}),
    ("Myydään korjattavaksi", {"project_for_parts"}),
    ("Jakoketju ääntää kylmäkäynnistyksessä", {"timing_chain_issue"}),
    ("Jakoketju juuri vaihdettu", set()),
    ("Tyhjäkäynnillä tiputtelee hieman kierroksia", {"engine_running_issue"}),
    ("Moottori nakuttaa", {"engine_major", "engine_knock"}),
    ("startti nakuttaa", set()),
    ("moottorista kuuluu mekaanista kolkotusta", {"engine_major", "engine_knock"}),
    ("DPF tukossa", {"dpf_issue"}),
    # round-2 hand-check errors
    ("kevyttä nakutusta etupäästä rattia käännettäessä", set()),
    ("turvavyön merkkiääni nakuttaa vaikka vyö kiinni", set()),
    ("kampiakselin asentotunnistin", set()),
    ("kone nakuttaa kylmänä", {"engine_major", "engine_knock"}),
    ("moottorin kampiakselin synkrohäviö", set()),
    ("Välillä kun autoon laittaa D tai R vaihteen päälle, niin auto ei liiku mihinkään", {"gearbox_issue", "non_runner"}),
    ("vika on todennäköisesti kompressorin kytkimessä", {"ac_issue"}),
    ("katsastuksesta tullut hylky", {"inspection_failed"}),
    ("jakohihnan vaihdosta ei ole merkintää", {"timing_belt_due"}),
    ("vaurioituneena poisto 13.10.2016", {"crash_damage"}),
    ("autossa moottorivaurio, ei käynnisty", {"engine_major", "engine_failure", "non_runner"}),
    ("keskikotelon muovista puuttuu pala, ruostetta helmoissa", {"rust", "rust_cosmetic"}),
    # Nettiauto ad-language false positives
    ("bi-xenon-ajovalot ja sumuvalot", set()),
    ("myydään Volkswagen Kupla, harrasteauto", set()),
    ("kolaroimaton suomi-auto", set()),
    ("tästä vaikka syksyn hirvimetsälle jahtiauto", set()),
    ("osui hirveen viime syksynä", {"crash_damage"}),
    ("koko moottori remontoitu 227 tkm kohdalla", set()),
    ("moottoriremontti edessä", {"engine_major", "engine_failure"}),
    ("täydellinen sisusta halkeamattomalla kojetaululla", set()),
    ("pieni halkeama puskurissa", set()),
    ("tuulilasissa halkeama matkustajan puolella", {"windshield_crack"}),
    ("pintaruostetta siellä täällä, mutta pohja katsurin mukaan todella hyvä", {"rust", "rust_cosmetic"}),
    ("pohjassa ja helmoissa ruostetta jonka korjaus aloitettu", {"rust", "rust_severe"}),
    ("helmat ruosteessa, vasemmalla puolella reikä ja siitä korjauskehotus", {"rust", "rust_severe"}),
    ("ruostetta tai maalin kukkimista en löytänyt", set()),
    ("jakohihnalla ajettu noin 60tkm, joten vielä huolettomia kilometrejä paljon edessä", set()),
    ("öljyvalo palaa ja kone ääntää", {"light_oil"}),
    ("abs valo palaa välillä", {"light_abs_esp"}),
    ("tuulilasissa pari kiveniskemää ei isompia halkeamia", set()),
    ("taka lasissa oli halkeama joka on korjattu", set()),
    ("helmoissa on alkavaa ruostetta, mutta ruoste ei ole mennyt läpi", {"rust", "rust_cosmetic"}),
    ("takakaarissa pientä ruosteen alkua mutta ei ole vielä puhki", {"rust", "rust_cosmetic"}),
    ("Talvirenkaissa paljon nastoja poikki", {"tyres_worn"}),
]


def flags_for(text: str) -> set[str]:
    r = F.finalize(F.flags_from_text(text))
    return {k for k, v in r.flags.items() if v and k not in IGNORE}


def main() -> int:
    bad = 0
    for text, want in CASES:
        got = flags_for(text)
        if got != want:
            bad += 1
            print(f"FAIL {text!r}\n  want {sorted(want)}\n  got  {sorted(got)}")
    light = F.classify_light_text("ainakin moottorin, sekä luistovalo")
    if not (light["light_engine"] and light["light_abs_esp"]):
        bad += 1
        print("FAIL light-field classification", light)
    print(f"{len(CASES) + 1 - bad}/{len(CASES) + 1} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
