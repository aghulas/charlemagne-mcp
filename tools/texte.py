"""Conversion des textes enrichis (RTF) de Charlemagne en texte brut.

Les champs « Observation » des fiches élève et responsable sont stockés en RTF
(police, couleurs, paragraphes). Le modèle n'a besoin que du texte.
"""

import re

# Groupes RTF dont le contenu n'est pas du texte affichable.
_DESTINATIONS = set("""
    aftncn aftnsep aftnsepc annotation atnauthor atndate atnicn atnid atnparent atnref atntime
    author background bkmkend bkmkstart blipuid buptim category colorschememapping colortbl comment
    company creatim datafield datastore defchp defpap do doccomm docvar dptxbxtext factoidname falt
    fchars field file filetbl fldinst fonttbl fontemb fontfile footer footerf footerl footerr footnote
    formfield ftncn ftnsep ftnsepc generator gridtbl header headerf headerl headerr hl hlfr hlinkbase
    hlloc hlsrc info keycode keywords latentstyles levelnumbers leveltext lfolevel linkval list
    listlevel listname listoverride listoverridetable listpicture liststylename listtable listtext
    lsdlockedexcept manager nesttableprops nonesttables objalias objclass objdata object objname
    oldcprops oldpprops oldsprops oldtprops oleclsid operator panose password passwordhash pict pn
    pnseclvl pntext pntxta pntxtb printim private propname protend protstart protusertbl pxe revtbl
    revtim rsidtbl shp shpgrp shpinst shppict shprslt shptxt sn sp stylesheet subject sv tc template
    themedata title txe ud upr userprops wgrffmtfilter windowcaption writereservation xe xform
    xmlnstbl
""".split())
_SPECIAUX = {"par": "\n", "line": "\n", "sect": "\n", "page": "\n", "tab": "\t", "emdash": "—",
             "endash": "–", "bullet": "•", "lquote": "‘", "rquote": "’", "ldblquote": "“",
             "rdblquote": "”", "emspace": " ", "enspace": " ", "qmspace": " "}
_JETON = re.compile(r"\\([a-z]{1,32})(-?\d{1,10})?[ ]?|\\'([0-9a-f]{2})|\\([^a-z])|([{}])|[\r\n]+|(.)",
                    re.I | re.S)


def rtf_en_texte(valeur) -> str:
    """Texte brut d'un champ Charlemagne (RTF ou texte simple) ; '' si vide.
    Les paragraphes deviennent des retours à la ligne, les espaces sont normalisés."""
    s = str(valeur or "")
    if not s.strip():
        return ""
    if not s.lstrip().startswith("{\\rtf"):
        return _nettoyer(s)
    pile, ignorer, ucskip, saut, out = [], False, 1, 0, []
    for mot, arg, hexa, car, accolade, autre in _JETON.findall(s):
        if accolade:
            saut = 0
            if accolade == "{":
                pile.append((ucskip, ignorer))
            elif pile:
                ucskip, ignorer = pile.pop()
        elif car:
            saut = 0
            if car == "*":
                ignorer = True
            elif not ignorer:
                out.append("\u00a0" if car == "~" else car if car in "{}\\" else "")
        elif mot:
            saut = 0
            if mot in _DESTINATIONS:
                ignorer = True
            elif ignorer:
                continue
            elif mot in _SPECIAUX:
                out.append(_SPECIAUX[mot])
            elif mot == "uc" and arg:
                ucskip = int(arg)
            elif mot == "u" and arg:
                n = int(arg)
                out.append(chr(n + 0x10000 if n < 0 else n))
                saut = ucskip
        elif hexa:
            if saut:
                saut -= 1
            elif not ignorer:
                out.append(bytes([int(hexa, 16)]).decode("cp1252", errors="replace"))
        elif autre:
            if saut:
                saut -= 1
            elif not ignorer:
                out.append(autre)
    return _nettoyer("".join(out))


def _nettoyer(t: str) -> str:
    lignes = [re.sub(r"[ \t\u00a0]+", " ", l).strip() for l in t.replace("\r", "\n").split("\n")]
    return "\n".join(l for l in lignes if l)
