import os
import json
import urllib.request
import numpy
import pandas
import pymongo
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State, ALL, dash_table, ctx, no_update
from dash.dash_table.Format import Format, Scheme
import dash_bootstrap_components as dbc
import folium
import branca.colormap as cm

DOSSIER = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(DOSSIER, "assets")
os.makedirs(ASSETS, exist_ok=True)

URL_GEOJSON = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
FICHIER_GEOJSON = os.path.join(ASSETS, "bresil-etats.geojson")
CARTE_ETATS = "/assets/bresil-etats.geojson"


def alleger(coords):
    if isinstance(coords[0][0], (int, float)):
        points = []
        for x, y in coords:
            p = [round(x, 2), round(y, 2)]
            if not points or points[-1] != p:
                points.append(p)
        return points if len(points) >= 4 else coords
    return [alleger(c) for c in coords]


if not os.path.exists(FICHIER_GEOJSON):
    with urllib.request.urlopen(URL_GEOJSON) as r:
        brut = json.load(r)
    for f in brut["features"]:
        f["properties"] = {"sigla": f["properties"]["sigla"], "name": f["properties"]["name"]}
        f["geometry"]["coordinates"] = alleger(f["geometry"]["coordinates"])
    with open(FICHIER_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(brut, f)

with open(FICHIER_GEOJSON, encoding="utf-8") as f:
    BRESIL = json.load(f)

URL_LOGO = "https://d3hw41hpah8tvx.cloudfront.net/images/logo_olist_branco_4a23bcfd6a.svg"
FICHIER_LOGO = os.path.join(ASSETS, "logo_olist_blanc.svg")
if not os.path.exists(FICHIER_LOGO):
    try:
        urllib.request.urlretrieve(URL_LOGO, FICHIER_LOGO)
    except Exception:
        pass

BLEU = "#0A4EE4"
ENCRE = "#071A4F"
ENCRE2 = "rgba(7,26,79,0.62)"
BRUME = "#EEF2FB"
JAUNE = "#FFC629"
JAUNE_FONCE = "#E09C00"
GRIS = "#B4BFD6"
CLAIR = "#93B2F5"
JAUNE_PALE = "#FFF3CC"
SEQ_BLEU = [[0, "#DCE6FC"], [0.3, "#93B2F5"], [0.6, "#3F75EC"], [0.8, "#0A4EE4"], [1, "#071A4F"]]
NOMS_PAIEMENT = {"credit_card": "Carte de crédit", "boleto": "Boleto", "voucher": "Bon d'achat", "debit_card": "Carte de débit", "not_defined": "Non défini"}
POLICE = "Instrument Sans, system-ui, sans-serif"
TITRE = "Bricolage Grotesque, Instrument Sans, system-ui, sans-serif"

db = pymongo.MongoClient("mongodb://127.0.0.1:27017/").SAE

lignes_cmd = []
lignes_art = []
lignes_pai = []
lignes_avis = []
projection = {"client": 1, "dates": 1, "articles": 1, "paiements": 1, "avis.note": 1, "avis.commentaire": 1,
              "delai_livraison_jours": 1, "retard_jours": 1}
for c in db.commandes.find({"statut": "delivered"}, projection):
    d = c["dates"]
    loc = c["client"].get("location")
    notes = [a["note"] for a in c.get("avis", [])]
    for a in c.get("avis", []):
        if "commentaire" in a:
            lignes_avis.append({"order_id": c["_id"], "note": a["note"], "texte": a["commentaire"].lower()})
    traitement = numpy.nan
    if "remise_transporteur" in d:
        traitement = (d["remise_transporteur"] - d["achat"]).total_seconds() / 86400
    lignes_cmd.append({
        "order_id": c["_id"],
        "achat": d["achat"],
        "uid": c["client"]["unique_id"],
        "etat": c["client"]["etat"],
        "ville": c["client"]["ville"],
        "clat": loc["coordinates"][1] if loc else numpy.nan,
        "clng": loc["coordinates"][0] if loc else numpy.nan,
        "delai": c.get("delai_livraison_jours", numpy.nan),
        "retard": c.get("retard_jours", numpy.nan),
        "traitement": traitement,
        "note": numpy.mean(notes) if notes else numpy.nan,
        "nb_articles": len(c["articles"]),
        "montant": sum(p["montant"] for p in c["paiements"]),
    })
    for a in c["articles"]:
        lignes_art.append({"order_id": c["_id"], "vendeur_id": a["vendeur_id"], "categorie": a["categorie"],
                           "prix": a["prix"], "frais_port": a["frais_port"]})
    for p in c["paiements"]:
        lignes_pai.append({"order_id": c["_id"], "moyen": p["moyen"], "echeances": p["echeances"], "montant": p["montant"]})

cmd = pandas.DataFrame(lignes_cmd)
cmd["mois"] = cmd.achat.dt.strftime("%Y-%m")
cmd["en_retard"] = numpy.where(cmd.retard.isna(), numpy.nan, (cmd.retard > 0).astype(float))
avis = pandas.DataFrame(lignes_avis)
THEMES = {
    "Colis non reçu": r"n[ãa]o recebi|ainda n[ãa]o chegou|ainda n[ãa]o recebi|n[ãa]o chegou|n[ãa]o foi entregue",
    "Pas de réponse du vendeur": r"resposta|retorno|contato|ningu[ée]m|n[ãa]o responde",
    "Remboursement, annulation": r"dinheiro|reembolso|estorno|devolu|cancel",
    "Colis incomplet": r"unidades|faltando|falta |apenas um|incomplet",
    "Produit différent ou abîmé": r"diferente|errado|quebrad|defeito|danificad|n[ãa]o funciona",
}
for nom, motif in THEMES.items():
    avis[nom] = avis.texte.str.contains(motif, regex=True)

vendeurs = []
for v in db.vendeurs.find():
    if "location" in v:
        vendeurs.append({"vendeur_id": v["_id"], "vville": v["ville"], "vetat": v["etat"],
                         "vlat": v["location"]["coordinates"][1], "vlng": v["location"]["coordinates"][0]})
vendeurs = pandas.DataFrame(vendeurs)

art = pandas.DataFrame(lignes_art)
art["ca"] = art.prix + art.frais_port
art = art.merge(cmd.drop(columns=["nb_articles", "montant"]), on="order_id").merge(vendeurs, on="vendeur_id", how="left")
lat1, lng1, lat2, lng2 = [numpy.radians(art[c]) for c in ["vlat", "vlng", "clat", "clng"]]
h = numpy.sin((lat2 - lat1) / 2) ** 2 + numpy.cos(lat1) * numpy.cos(lat2) * numpy.sin((lng2 - lng1) / 2) ** 2
art["distance"] = 6371 * 2 * numpy.arcsin(numpy.sqrt(h))

pai = pandas.DataFrame(lignes_pai).merge(cmd[["order_id", "mois", "etat"]], on="order_id")

MOIS = list(pandas.period_range(cmd.mois.min(), cmd.mois.max(), freq="M").astype(str))
ETATS = sorted(cmd.etat.unique())
CATEGORIES = sorted(art.categorie.unique())


MOIS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
NOMS_ETATS = {"AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
              "DF": "District fédéral", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
              "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambouc",
              "PI": "Piauí", "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia",
              "RR": "Roraima", "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
              "TO": "Tocantins"}


LIBELLES = {"select_all": "Tout sélectionner", "deselect_all": "Tout désélectionner", "selected_count": "{num_selected} sélectionnés",
            "search": "Rechercher", "clear_search": "Effacer", "clear_selection": "Tout retirer", "no_options_found": "Aucun résultat"}


def fr(x, d=0):
    if pandas.isna(x):
        return "–"
    return f"{x:,.{d}f}".replace(",", "\u00a0").replace(".", ",")


def mois_texte(m):
    return f"{MOIS_FR[int(m[5:]) - 1]} {m[:4]}"


CATEGORIES_FR = {
    "bed_bath_table": "Linge de maison", "health_beauty": "Beauté et santé", "sports_leisure": "Sport et loisirs",
    "furniture_decor": "Meubles et déco", "computers_accessories": "Accessoires informatiques", "housewares": "Articles ménagers",
    "watches_gifts": "Montres et cadeaux", "telephony": "Téléphonie", "garden_tools": "Jardinage", "auto": "Automobile",
    "toys": "Jouets", "cool_stuff": "Objets tendance", "perfumery": "Parfumerie", "baby": "Bébé", "electronics": "Électronique",
    "stationery": "Papeterie", "fashion_bags_accessories": "Sacs et accessoires", "pet_shop": "Animalerie",
    "office_furniture": "Mobilier de bureau", "inconnue": "Catégorie inconnue", "consoles_games": "Consoles et jeux vidéo",
    "luggage_accessories": "Bagagerie", "construction_tools_construction": "Outillage de chantier",
    "home_appliances": "Électroménager", "musical_instruments": "Instruments de musique", "small_appliances": "Petit électroménager",
    "home_construction": "Construction et rénovation", "books_general_interest": "Livres", "food": "Alimentation",
    "furniture_living_room": "Meubles de salon", "home_confort": "Confort de la maison", "drinks": "Boissons", "audio": "Audio",
    "market_place": "Marketplace", "construction_tools_lights": "Éclairage", "air_conditioning": "Climatisation",
    "kitchen_dining_laundry_garden_furniture": "Mobilier de cuisine et de jardin", "food_drink": "Épicerie",
    "industry_commerce_and_business": "Équipement professionnel", "books_technical": "Livres techniques",
    "fixed_telephony": "Téléphonie fixe", "fashion_shoes": "Chaussures", "home_appliances_2": "Gros électroménager",
    "costruction_tools_garden": "Outillage de jardin", "agro_industry_and_commerce": "Agro-industrie", "art": "Art",
    "computers": "Ordinateurs", "signaling_and_security": "Signalisation et sécurité", "construction_tools_safety": "Équipement de sécurité",
    "christmas_supplies": "Décorations de Noël", "fashion_male_clothing": "Mode homme", "fashion_underwear_beach": "Lingerie et plage",
    "furniture_bedroom": "Meubles de chambre", "costruction_tools_tools": "Outils", "tablets_printing_image": "Tablettes et impression",
    "small_appliances_home_oven_and_coffee": "Fours et machines à café", "cine_photo": "Photo et cinéma", "dvds_blu_ray": "DVD et Blu-ray",
    "books_imported": "Livres importés", "fashio_female_clothing": "Mode femme", "party_supplies": "Articles de fête",
    "diapers_and_hygiene": "Couches et hygiène", "music": "Musique", "furniture_mattress_and_upholstery": "Literie",
    "flowers": "Fleurs", "home_comfort_2": "Confort de la maison", "fashion_sport": "Mode sport", "arts_and_craftmanship": "Loisirs créatifs",
    "portateis_cozinha_e_preparadores_de_alimentos": "Robots de cuisine", "la_cuisine": "Ustensiles de cuisine",
    "cds_dvds_musicals": "CD et DVD musicaux", "pc_gamer": "PC gamer", "fashion_childrens_clothes": "Mode enfant",
    "security_and_services": "Sécurité et services",
}


def nom_categorie(c):
    if c in CATEGORIES_FR:
        return CATEGORIES_FR[c]
    c = c.replace("_", " ")
    return c[:1].upper() + c[1:]


def compact(v):
    if pandas.isna(v):
        return "–"
    if abs(v) >= 1e6:
        return f"{fr(v / 1e6, 1)} M"
    if abs(v) >= 1e4:
        return f"{fr(v / 1e3, 0)} k"
    return fr(v, 0)


def style(fig, hauteur=340, legende=False, sur_bleu=False):
    texte = "rgba(255,255,255,0.75)" if sur_bleu else ENCRE2
    grille = "rgba(255,255,255,0.14)" if sur_bleu else "#E4EAF6"
    fig.update_layout(
        template="plotly_white", height=hauteur, margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=POLICE, size=12.5, color=texte),
        hoverlabel=dict(bgcolor="white", bordercolor=ENCRE, font=dict(family=POLICE, size=12.5, color=ENCRE)),
        showlegend=legende, legend=dict(orientation="h", y=1.1, x=0, font=dict(color=texte)),
        separators=", ",
    )
    for axe in (fig.update_xaxes, fig.update_yaxes):
        axe(gridcolor=grille, zeroline=False, showline=False, ticks="", tickfont=dict(size=12, color=texte),
            title_font=dict(size=12, color=texte), title_standoff=12)
    return fig


def barres_v(fig, maxi, mini=0):
    fig.update_yaxes(showticklabels=False, showgrid=False, title=None, range=[mini, maxi * 1.08])
    fig.update_xaxes(showgrid=False, tickfont=dict(size=12, color=ENCRE))
    return fig


def barres_h(fig, textes, maxi, mini=0, reference=27):
    nb = len(textes)
    fig.update_layout(bargap=min(0.8, max(0.28, 1 - 0.72 * nb / reference)))
    fig.update_traces(text=textes, textposition="outside", cliponaxis=False,
                      textfont=dict(family=TITRE, size=13, color=ENCRE), selector=dict(type="bar"))
    marge = (maxi - mini) * 0.22
    fig.update_xaxes(showticklabels=False, showgrid=False, title=None,
                     range=[mini - (marge if mini < 0 else 0), maxi + (marge if maxi > 0 else 0)])
    fig.update_yaxes(showgrid=False, tickfont=dict(size=12, color=ENCRE))
    return fig


def fond_bresil(fig, lat=-14.5, lon=-52, zoom=3.1):
    fig.update_layout(map=dict(style="white-bg", center=dict(lat=lat, lon=lon), zoom=zoom, layers=[
        dict(source=CARTE_ETATS, type="fill", color=BRUME, below="traces"),
        dict(source=CARTE_ETATS, type="line", color="#C5D1EC", line=dict(width=0.8), below="traces"),
    ]))
    return fig


def vide(hauteur=340, message="Aucune commande ne correspond à ces filtres. Élargissez la période ou retirez un filtre."):
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(size=13, color=ENCRE2))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return style(fig, hauteur)


def couleurs_alerte(valeurs, nb, plus_grands=True):
    rang = valeurs.rank(ascending=not plus_grands, method="first")
    return [JAUNE_FONCE if r <= nb else BLEU for r in rang]


def decision(texte, sur_bleu=False, ident=None):
    contenu = html.Span(texte, id=ident) if ident else html.Span(texte)
    return html.P([html.Span("Décision", className="tag"), contenu],
                  className="decision decision-bleu" if sur_bleu else "decision")


def panneau(titre, id_graph, texte_decision, hauteur=340, sous=None, controle=None):
    tete = [html.H3(titre)]
    if sous:
        tete.append(html.P(sous, className="sous"))
    corps = [html.Div(tete, className="tete")]
    if controle is not None:
        corps.append(controle)
    corps.append(dcc.Loading(dcc.Graph(id=id_graph, config={"displayModeBar": False}, style={"height": f"{hauteur}px"}),
                             color=BLEU, type="dot", delay_show=350, overlay_style={"visibility": "visible", "opacity": 0.45}))
    corps.append(decision(texte_decision, ident="d-" + id_graph) if isinstance(texte_decision, str) else html.P(
        [html.Span("Décision", className="tag"), texte_decision], className="decision"))
    return html.Section(corps, className="panneau")


def b(x):
    return html.B(str(x).replace(" ", "\u00a0"))


def filtrer(periode, etats, categories):
    m0, m1 = MOIS[periode[0]], MOIS[periode[1]]
    c = cmd[(cmd.mois >= m0) & (cmd.mois <= m1)]
    a = art[(art.mois >= m0) & (art.mois <= m1)]
    p = pai[(pai.mois >= m0) & (pai.mois <= m1)]
    if etats:
        c = c[c.etat.isin(etats)]
        a = a[a.etat.isin(etats)]
        p = p[p.etat.isin(etats)]
    if categories:
        a = a[a.categorie.isin(categories)]
        c = c[c.order_id.isin(a.order_id)]
        p = p[p.order_id.isin(a.order_id)]
    return c, a, p


def vendeurs_actifs(periode, categories):
    _, a_tous, _ = filtrer(periode, None, categories)
    return a_tous.drop_duplicates("vendeur_id").groupby("vetat").size()


def stats_vendeurs(a):
    vc = a.drop_duplicates(["vendeur_id", "order_id"])
    s = vc.groupby("vendeur_id").agg(nb_commandes=("order_id", "size"), note=("note", "mean"),
                                     retard=("en_retard", "mean"), traitement=("traitement", "mean"),
                                     delai=("delai", "mean"), distance=("distance", "mean"))
    s["ca"] = a.groupby("vendeur_id").ca.sum()
    return s.reset_index().merge(vendeurs, on="vendeur_id")


app = Dash(__name__, assets_folder=ASSETS, external_stylesheets=[dbc.themes.BOOTSTRAP], title="olist | Pilotage")
app.index_string = """<!DOCTYPE html>
<html lang="fr"><head>{%metas%}<title>{%title%}</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='16' fill='%230A4EE4'/%3E%3Ccircle cx='32' cy='34' r='13' fill='none' stroke='white' stroke-width='8'/%3E%3C/svg%3E">{%css%}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,500;12..96,600;12..96,700&family=Instrument+Sans:wght@400;500;600&display=swap">
<style>
:root {
  --bleu: #0A4EE4; --encre: #071A4F; --encre2: rgba(7,26,79,.62); --brume: #EEF2FB; --jaune: #FFC629;
  --titre: "Bricolage Grotesque", "Instrument Sans", system-ui, sans-serif;
  --texte: "Instrument Sans", system-ui, sans-serif;
  --Dash-Fill-Interactive-Strong: #0A4EE4;
}
body { background: var(--brume); font-family: var(--texte); color: var(--encre); font-size: 15px; }
.entete { background: var(--bleu); color: #fff; padding: 26px 48px 10px; display: flex; flex-wrap: wrap; align-items: flex-end; gap: 28px 56px; }
.marque { display: flex; align-items: center; gap: 18px; }
.marque img { height: 38px; display: block; }
.mot { font-family: var(--titre); font-size: 42px; font-weight: 700; letter-spacing: -.055em; line-height: .9; }
.marque p { margin: 0; font-size: 13.5px; line-height: 1.35; color: rgba(255,255,255,.78); max-width: 15em; }
.filtres { display: flex; flex-wrap: wrap; gap: 18px 22px; align-items: flex-end; margin-left: auto; }
.filtre label { display: block; font-size: 12.5px; color: rgba(255,255,255,.78); margin-bottom: 6px; }
.filtre-periode { width: 310px; --Dash-Fill-Interactive-Strong: #fff; }
.filtre-periode .dash-slider-mark { color: rgba(255,255,255,.75); }
.filtre-liste { width: 230px; }
.entete .dash-dropdown { background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.4); border-radius: 999px; min-height: 42px; padding: 0 14px; color: #fff; }
.entete .dash-dropdown:hover { background: rgba(255,255,255,.2); }
.entete .dash-dropdown-trigger, .entete .dash-dropdown-trigger * { color: #fff; }
.dash-dropdown-content { min-width: 320px; background: #fff; border-radius: 14px; box-shadow: 0 12px 32px rgba(7,26,79,.18); }
.dash-dropdown-content, .dash-dropdown-content * { color: var(--encre); }
.dash-dropdown-content input { color: var(--encre); background: #fff; }
.dash-options-list-option { display: flex !important; align-items: center; gap: 10px; padding: 7px 12px; cursor: pointer; }
.dash-options-list-option input { margin: 0; flex: none; }
.dash-options-list-option:hover { background: var(--brume); }
.filtre-periode .dash-slider-track { background: rgba(255,255,255,.3); }
.reinit { background: none; border: none; color: #fff; font-size: 13.5px; text-decoration: underline; text-underline-offset: 3px; padding: 0 0 10px; }
.reinit:hover { color: var(--jaune); }
.reinit:focus-visible, .nav-link:focus-visible { outline: 2px solid var(--jaune); outline-offset: 3px; }
.nav-tabs { background: var(--bleu); border: none; padding: 0 40px; }
.tab-content:empty { display: none; }
.nav-tabs .nav-link { color: rgba(255,255,255,.72); background: none !important; border: none; border-bottom: 3px solid transparent; border-radius: 0; padding: 16px 0 12px; margin: 0 26px 0 8px; font-weight: 500; font-size: 15.5px; }
.nav-tabs .nav-link:hover { color: #fff; border-bottom-color: rgba(255,255,255,.4); }
.nav-tabs .nav-link.active { color: #fff; border-bottom-color: var(--jaune); }
.hero { background: var(--bleu); color: #fff; padding: 34px 48px 26px; }
.hero h1 { font-family: var(--titre); font-weight: 400; font-size: clamp(30px, 3.2vw, 50px); line-height: 1.1; letter-spacing: -.03em; max-width: 25em; margin: 0 0 30px; }
.hero h1 b { font-weight: 700; }
.choix-bleu label { color: rgba(255,255,255,.85); font-size: 13.5px; }
.choix-bleu .form-check-input { background-color: transparent; border-color: rgba(255,255,255,.7); }
.choix-bleu .form-check-input:checked { background-color: var(--jaune); border-color: var(--jaune); }
.contenu { padding: 38px 48px 72px; }
.constat { font-family: var(--titre); font-weight: 400; font-size: clamp(26px, 2.3vw, 36px); line-height: 1.15; letter-spacing: -.025em; max-width: 30em; margin: 0 0 30px; }
.constat b { font-weight: 700; }
.panneau { background: #fff; border-radius: 24px; padding: 26px 28px 20px; margin-bottom: 24px; height: calc(100% - 24px); display: flex; flex-direction: column; }
.panneau .tete { margin-bottom: 10px; }
.panneau h3 { font-family: var(--titre); font-size: 20px; font-weight: 600; letter-spacing: -.015em; margin: 0; }
.sous { font-size: 13.5px; line-height: 1.45; color: var(--encre2); margin: 5px 0 0; max-width: 60ch; }
.decision { display: flex; gap: 12px; align-items: baseline; font-size: 14px; line-height: 1.45; margin: auto 0 0; padding-top: 12px; max-width: 75ch; }
.tag { flex: none; background: var(--jaune); color: var(--encre); font-weight: 600; font-size: 12px; border-radius: 999px; padding: 2px 11px; }
.decision-bleu { color: rgba(255,255,255,.9); margin-top: 6px; }
.objectif { display: block; margin-top: 4px; }
.decision-bleu b { color: #fff; }
.choix label { font-size: 13.5px; color: var(--encre); }
.choix .form-check-input:checked { background-color: var(--bleu); border-color: var(--bleu); }
.reglages { display: flex; flex-wrap: wrap; gap: 18px 36px; align-items: flex-end; margin: 4px 0 14px; }
.reglages label.titre-reglage { display: block; font-size: 13px; color: var(--encre2); margin-bottom: 6px; }
.fiche { display: flex; flex-wrap: wrap; gap: 14px 48px; margin: 0 0 28px; }
.fiche dt { font-size: 13.5px; color: var(--encre2); font-weight: 400; }
.fiche dd { font-family: var(--titre); font-size: 32px; font-weight: 600; letter-spacing: -.025em; margin: 0; line-height: 1.1; }
.fiche dd small { font-family: var(--texte); font-size: 13px; font-weight: 400; color: var(--encre2); letter-spacing: 0; }
.choix-vendeur { max-width: 640px; margin-bottom: 18px; }
.carte-folium { width: 100%; height: 540px; border: none; border-radius: 16px; margin-top: 12px; background: var(--brume); }
.legende { display: flex; align-items: center; gap: 12px; font-size: 13px; color: var(--encre2); margin-top: 12px; }
.legende .degrade { flex: 1; max-width: 320px; height: 10px; border-radius: 999px; }
.legende b { color: var(--encre); font-weight: 600; }
.barre-fixe { position: sticky; top: 0; z-index: 1030; box-shadow: 0 6px 18px rgba(7,26,79,.10); }
.filtres-actifs { background: #fff; padding: 10px 48px; display: flex; flex-wrap: wrap; gap: 8px 10px; align-items: center; font-size: 13px; min-height: 46px; }
.libelle-filtres { color: var(--encre2); margin-right: 4px; }
.sans-filtre { color: var(--encre2); }
.puce { background: var(--brume); color: var(--encre); border: 1px solid #DCE3F2; border-radius: 999px; padding: 3px 6px 3px 12px; font-size: 13px; display: inline-flex; align-items: center; gap: 6px; }
.puce:hover { background: #DCE6FC; }
.puce:focus-visible, .lien:focus-visible { outline: 2px solid var(--bleu); outline-offset: 2px; }
.croix { display: inline-flex; width: 18px; height: 18px; border-radius: 999px; align-items: center; justify-content: center; font-size: 15px; line-height: 1; color: var(--encre2); }
.puce:hover .croix { background: #fff; color: var(--encre); }
.panneau-auto { height: auto; }
.points { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 8px 40px; margin-top: 6px; }
.point p { font-size: 14px; line-height: 1.45; margin: 4px 0 8px; max-width: 34ch; }
.point-chiffre { font-family: var(--titre); font-size: 34px; font-weight: 600; letter-spacing: -.025em; line-height: 1.1; }
.lien { background: none; border: none; padding: 0; color: var(--bleu); font-size: 13.5px; font-weight: 600; text-decoration: underline; text-underline-offset: 3px; }
.lien:hover { color: var(--encre); }
.intertitre { font-family: var(--titre); font-size: 22px; font-weight: 600; letter-spacing: -.02em; margin: 14px 0 16px; color: var(--encre); }
.reglages-col { display: flex; flex-direction: column; gap: 26px; padding: 8px 4px 0 12px; }
.reglages-col label.titre-reglage { display: block; font-size: 13px; color: var(--encre2); margin-bottom: 8px; }
.bande-fiche { background: #DCE6FC; border-radius: 24px; padding: 26px 30px 4px; margin: 8px 0 24px; }
.entete-fiche { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 20px; margin-bottom: 18px; }
.titre-fiche { font-family: var(--titre); font-size: 15px; font-weight: 600; color: var(--bleu); margin: 0; }
.entete-fiche .choix-vendeur { flex: 1; min-width: 280px; max-width: 620px; margin: 0; }
.pied { margin: 0 48px; padding: 24px 0 40px; font-size: 13px; color: var(--encre2); border-top: 1px solid #DCE3F2; line-height: 1.5; }
.pied p { margin: 0; max-width: 110ch; }
.pied b { color: var(--encre); font-weight: 600; }
@media (max-width: 900px) {
  .entete, .hero, .contenu, .filtres-actifs { padding-left: 20px; padding-right: 20px; }
  .pied { margin: 0 20px; }
  .nav-tabs { padding: 0 12px; }
  .filtres { margin-left: 0; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style></head>
<body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>"""

marques = {i: {"label": f"{MOIS_FR[int(m[5:]) - 1]} {m[2:4]}"} for i, m in enumerate(MOIS) if m[5:] in ("01", "07")}

if os.path.exists(FICHIER_LOGO):
    logo = html.Img(src=app.get_asset_url("logo_olist_blanc.svg"), alt="olist")
else:
    logo = html.Div("olist", className="mot")

entete = html.Header([
    html.Div([logo, html.P("Pilotage de la marketplace, de la commande à l'avis client")], className="marque"),
    html.Div([
        html.Div([html.Label("Période d'achat", htmlFor="periode"),
                  dcc.RangeSlider(id="periode", min=0, max=len(MOIS) - 1, step=1, value=[0, len(MOIS) - 1],
                                  marks=marques, allowCross=False, allow_direct_input=False)], className="filtre filtre-periode"),
        html.Div([html.Label("États des clients", htmlFor="etats"),
                  dcc.Dropdown(id="etats", labels=LIBELLES, maxHeight=340, options=[{"label": f"{e} – {NOMS_ETATS.get(e, e)}", "value": e} for e in ETATS],
                               multi=True, placeholder="Tout le Brésil")], className="filtre filtre-liste"),
        html.Div([html.Label("Catégories", htmlFor="categories"),
                  dcc.Dropdown(id="categories", labels=LIBELLES, maxHeight=340, options=sorted([{"label": nom_categorie(c), "value": c} for c in CATEGORIES], key=lambda o: o["label"]),
                               multi=True, placeholder="Toutes")], className="filtre filtre-liste"),
        html.Button("Tout réinitialiser", id="reset", className="reinit"),
    ], className="filtres"),
], className="entete")

onglet_global = html.Div([
    html.Div([
        html.H1(id="phrase"),
        dbc.RadioItems(id="mesure-ca", inline=True, value="ca", className="choix-bleu mb-1",
                       options=[{"label": "Chiffre d'affaires par mois", "value": "ca"},
                                {"label": "Commandes livrées par mois", "value": "nb"}]),
        dcc.Graph(id="g-ca", config={"displayModeBar": False}, style={"height": "290px"}),
        decision("préparer les pics de fin d'année (Black Friday) : stocks des vendeurs, capacité transporteurs et budget marketing.", True, ident="d-g-ca"),
    ], className="hero"),
    html.Div([
        html.Section([
            html.Div([html.H3("Points d'attention"),
                      html.P("Calculés selon les filtres en cours. Chaque point renvoie vers l'onglet qui le détaille.", className="sous")],
                     className="tete"),
            html.Div(id="points", className="points"),
        ], className="panneau panneau-auto"),
        dbc.Row([
            dbc.Col(panneau("Combien de jours pour être livré ?", "g-delais",
                            "afficher une promesse de délai tenable et traiter en priorité la traîne des commandes à plus de 30 jours.",
                            sous="De l'achat à la réception par le client. Les commandes de plus de 60 jours sont masquées."), lg=8),
            dbc.Col(panneau("Comment les clients paient-ils ?", "g-paiement",
                            "négocier d'abord les commissions carte bancaire, qui portent l'essentiel des montants, et garder le boleto pour les clients sans carte.",
                            sous="Part de la valeur totale payée par moyen de paiement."), lg=4),
        ]),
    ], className="contenu"),
], id="section-global")

onglet_carte = html.Div([
    html.H2(id="constat-carte", className="constat"),
    dbc.Row([
        dbc.Col(html.Section([
            html.Div([html.H3("Le Brésil, État par État"),
                      html.P("Survolez un État pour lire sa valeur. Les États sélectionnés dans le filtre sont entourés de jaune.", className="sous")],
                     className="tete"),
            dbc.RadioItems(id="indicateur", inline=True, value="ca", className="choix",
                           options=[{"label": "Chiffre d'affaires", "value": "ca"},
                                    {"label": "Délai moyen", "value": "delai"},
                                    {"label": "Taux de retard", "value": "retard"},
                                    {"label": "Note moyenne", "value": "note"},
                                    {"label": "Panier moyen", "value": "panier"}]),
            html.Iframe(id="carte-folium", className="carte-folium"),
            html.Div(id="legende-choro", className="legende"),
            html.P([html.Span("Décision", className="tag"), html.Span(id="decision-choro")], className="decision"),
        ], className="panneau"), lg=8),
        dbc.Col(panneau("Classement des États", "g-classement",
                        "repérer d'un coup d'œil les États en tête et en queue avant d'ouvrir le détail.", hauteur=596,
                        sous="Cliquez une barre pour ajouter l'État au filtre de tout le tableau de bord, recliquez pour le retirer. Les États sélectionnés sont en jaune."), lg=4),
    ]),
    html.Section([
        html.Div([html.H3("Tous les États en un tableau"),
                  html.P("Tous les indicateurs côte à côte. Triez en cliquant un en-tête, filtrez avec la ligne sous les en-têtes.", className="sous")],
                 className="tete"),
        dash_table.DataTable(
            id="t-etats", page_size=27, sort_action="native", filter_action="native",
            filter_options={"placeholder_text": "Filtrer"}, locale_format={"decimal": ",", "group": " "},
            style_as_list_view=True,
            style_header={"fontWeight": "600", "backgroundColor": BRUME, "border": "none", "color": ENCRE},
            style_cell={"fontFamily": POLICE, "fontSize": "13.5px", "padding": "8px 12px", "textAlign": "left",
                        "backgroundColor": "white", "color": ENCRE, "borderBottom": "1px solid #E4EAF6"},
            style_filter={"backgroundColor": "white"},
        ),
    ], className="panneau panneau-auto"),
], className="contenu", id="section-carte")

onglet_satisfaction = html.Div([
    html.H2(id="constat-satisfaction", className="constat"),
    html.H3("1. La promesse de livraison est-elle tenue ?", className="intertitre"),
    dbc.Row([
        dbc.Col(panneau("La date promise est-elle trop prudente ?", "g-promesse",
                        "raccourcir les délais affichés au client pour lever un frein à l'achat, sans créer de retards.",
                        sous="Écart entre la date de livraison annoncée et la date réelle. En jaune, les colis livrés après la date promise."), lg=6),
        dbc.Col(panneau("Mois après mois, les colis arrivent-ils à l'heure ?", "g-heure",
                        "réserver de la capacité transporteur avant les mois où le taux décroche, comme fin 2017 et début 2018.",
                        sous="Part des commandes livrées avant la date estimée, pour les mois d'au moins 30 commandes."), lg=6),
    ]),
    html.H3("2. Que coûte un retard ?", className="intertitre"),
    dbc.Row([
        dbc.Col(panneau("Combien coûte un retard en satisfaction ?", "g-note-retard",
                        "relancer et dédommager les clients dès 4 jours de retard, seuil où la note s'effondre.",
                        sous="Note moyenne selon l'écart entre la livraison réelle et la date promise."), lg=6),
        dbc.Col(panneau("De quoi se plaignent les clients ?", "g-plaintes",
                        "renforcer le suivi de colis et imposer aux vendeurs un délai de réponse : les plaintes portent sur le service, rarement sur le produit.",
                        sous="Part des avis commentés qui évoquent chaque thème, repéré par mots-clés portugais (« não recebi », « sem resposta », « reembolso »…)."), lg=6),
    ]),
    html.H3("3. Où agir en priorité ?", className="intertitre"),
    dbc.Row([
        dbc.Col(panneau("Où la lenteur pèse-t-elle le plus ?", "g-heatmap",
                        "changer de transporteur ou ouvrir des points relais dans les États où les livraisons lentes sont les plus mal notées.",
                        hauteur=520, sous="Note moyenne des 15 États qui commandent le plus, selon la durée de livraison. Une case vide compte moins de 20 commandes."), lg=6),
        dbc.Col(panneau("Où la ponctualité compte-t-elle le plus ?", "g-correlation",
                        "dans les États en jaune, chaque jour de retard gagné rapporte le plus de satisfaction : à traiter en premier.",
                        hauteur=520, sous="Corrélation entre jours de retard et note, États d'au moins 30 commandes. Les 3 plus fortes sont en jaune."), lg=6),
    ]),
], className="contenu", id="section-livraison")

onglet_commercial = html.Div([
    html.H2(id="constat-commercial", className="constat"),
    dbc.Row([
        dbc.Col(panneau("Quelles catégories font le chiffre ?", "g-categories",
                        "concentrer le recrutement de vendeurs et le budget d'acquisition sur ces dix catégories.",
                        hauteur=500, sous="Les 10 premières catégories : chiffre d'affaires et part du total."), lg=6),
        dbc.Col(panneau("Qui revient commander ?", "g-recurrents",
                        "lancer une offre de deuxième commande dans les États en jaune, où les clients reviennent le moins.",
                        hauteur=500, sous="Part des clients ayant passé au moins 2 commandes, États d'au moins 50 clients. Les 3 plus faibles sont en jaune."), lg=6),
    ]),
    dbc.Row([
        dbc.Col(panneau("Les frais de port font-ils baisser la note ?", "g-port",
                        "proposer la livraison offerte au-dessus d'un seuil de panier, pour les petits articles dont le port dépasse le prix.",
                        sous="Note moyenne selon le poids des frais de port dans le prix de l'article."), lg=6),
        dbc.Col(panneau("Où manque-t-il des vendeurs ?", "g-ratio",
                        "recruter des vendeurs locaux en priorité dans les États en jaune, où chaque vendeur sert le plus de clients.",
                        sous="Clients par vendeur installé dans l'État et actif sur la période, 15 premiers. Les 3 plus tendus sont en jaune."), lg=6),
    ]),
    panneau("Quand les clients achètent-ils ?", "g-heures",
            "programmer campagnes et promotions sur les créneaux les plus actifs, et y renforcer le service client.",
            hauteur=320, sous="Commandes selon le jour de la semaine et l'heure d'achat."),
], className="contenu", id="section-ventes")

reglages_vendeurs = html.Div([
    html.Div([html.Label("État du vendeur", className="titre-reglage", htmlFor="v-etats"),
              dcc.Dropdown(id="v-etats", labels=LIBELLES, maxHeight=340, options=sorted(vendeurs.vetat.unique()), multi=True,
                           placeholder="Tous les États")]),
    html.Div([html.Label("Nombre minimal de commandes", className="titre-reglage", htmlFor="v-min"),
              dcc.Slider(id="v-min", min=1, max=200, step=1, value=20,
                         marks={1: "1", 50: "50", 100: "100", 150: "150", 200: "200"})]),
    html.Div([html.Label("Couleur des points", className="titre-reglage"),
              dbc.RadioItems(id="v-couleur", value="note", className="choix",
                             options=[{"label": "Note moyenne", "value": "note"}, {"label": "Taux de retard", "value": "retard"}])]),
    html.P("La période et les catégories du bandeau s'appliquent aussi. Le filtre des États clients ne s'applique pas ici : "
           "on filtre sur l'État du vendeur.", className="sous"),
], className="reglages-col")

onglet_vendeurs = html.Div([
    html.H2(id="constat-vendeurs", className="constat"),
    html.Section([
        html.Div([html.H3("Où sont les vendeurs, et lesquels décrochent ?"),
                  html.P("Un point par vendeur, de taille proportionnelle à son chiffre d'affaires. Cliquez un point pour ouvrir sa fiche.", className="sous")],
                 className="tete"),
        dbc.Row([
            dbc.Col(dcc.Loading(dcc.Graph(id="g-vendeurs", config={"displayModeBar": False}, style={"height": "560px"}),
                                color=BLEU, type="dot", delay_show=350, overlay_style={"visibility": "visible", "opacity": 0.45}), lg=8),
            dbc.Col(reglages_vendeurs, lg=4),
        ]),
        decision("accompagner les vendeurs en jaune (fiche produit, emballage, délai d'expédition) avant qu'ils ne dégradent la note de la plateforme.", ident="d-g-vendeurs"),
    ], className="panneau panneau-auto"),
    html.Div([
        html.Div([html.Label("Fiche vendeur", className="titre-fiche", htmlFor="vendeur"),
                  dcc.Dropdown(id="vendeur", labels=LIBELLES, maxHeight=340, clearable=False, placeholder="Choisir un vendeur",
                               className="choix-vendeur")], className="entete-fiche"),
        html.H2(id="v-titre", className="constat mb-3"),
        html.Dl(id="v-fiche", className="fiche"),
    ], className="bande-fiche"),
    dbc.Row([
        dbc.Col(panneau("Où livre ce vendeur ?", "g-zones",
                        "si les retards (en jaune) se concentrent loin de sa base, lui proposer un transporteur longue distance ou un stock régional.",
                        hauteur=460, sous="Chaque trait relie le vendeur à un client livré sur la période."), lg=6),
        dbc.Col(panneau("Plus c'est loin, plus c'est long ?", "g-distance",
                        "si le délai grimpe vite avec la distance, limiter la zone de livraison promise ou ajuster les dates estimées.",
                        hauteur=460, sous="Délai de livraison de chaque commande selon la distance au client, avec la tendance."), lg=6),
    ]),
    html.Section([
        html.Div([html.H3("Ses commandes"), html.P("Triez en cliquant un en-tête, filtrez avec la ligne sous les en-têtes (par exemple > 0 dans la colonne Retard).", className="sous")], className="tete"),
        dash_table.DataTable(
            id="t-commandes", page_size=10, sort_action="native", filter_action="native",
            filter_options={"placeholder_text": "Filtrer"},
            locale_format={"decimal": ",", "group": " "},
            style_as_list_view=True,
            style_header={"fontWeight": "600", "backgroundColor": BRUME, "border": "none", "color": ENCRE},
            style_cell={"fontFamily": POLICE, "fontSize": "13.5px", "padding": "8px 12px", "textAlign": "left",
                        "backgroundColor": "white", "color": ENCRE, "borderBottom": "1px solid #E4EAF6"},
            style_filter={"backgroundColor": "white"},
            style_data_conditional=[{"if": {"filter_query": "{Retard (j)} > 0", "column_id": "Retard (j)"},
                                     "backgroundColor": JAUNE_PALE, "fontWeight": "600"}],
        ),
    ], className="panneau panneau-auto"),
], className="contenu", id="section-vendeurs")

for section in (onglet_carte, onglet_satisfaction, onglet_commercial, onglet_vendeurs):
    section.style = {"display": "none"}

ONGLETS = [("global", "Vue d'ensemble"), ("carte", "Carte du Brésil"), ("livraison", "Livraison et satisfaction"),
           ("ventes", "Ventes"), ("vendeurs", "Vendeurs")]

app.layout = html.Div([
    entete,
    html.Div([
        dbc.Tabs([dbc.Tab(label=nom, tab_id=cle) for cle, nom in ONGLETS], id="onglets", active_tab="global"),
        html.Div(id="filtres-actifs", className="filtres-actifs"),
    ], className="barre-fixe"),
    onglet_global, onglet_carte, onglet_satisfaction, onglet_commercial, onglet_vendeurs,
    html.Footer(html.P([html.B("Source : "), "base publique Olist (Kaggle), commandes passées de septembre 2016 à octobre 2018, migrée de SQLite vers MongoDB. ",
                        "Sauf mention contraire, les indicateurs portent sur les commandes livrées et les montants sont en réais brésiliens (R$)."]),
                className="pied"),
])


@app.callback([Output(f"section-{cle}", "style") for cle, _ in ONGLETS], Input("onglets", "active_tab"))
def afficher_onglet(actif):
    return [{"display": "block"} if cle == actif else {"display": "none"} for cle, _ in ONGLETS]


@app.callback(Output("onglets", "active_tab"), Input({"type": "aller", "onglet": ALL}, "n_clicks"), prevent_initial_call=True)
def aller_onglet(clics):
    if not ctx.triggered or not ctx.triggered[0]["value"]:
        return no_update
    return ctx.triggered_id["onglet"]


@app.callback(Output("filtres-actifs", "children"),
              Input("periode", "value"), Input("etats", "value"), Input("categories", "value"), Input("onglets", "active_tab"))
def maj_puces(periode, etats, categories, actif):
    puces = []
    if periode != [0, len(MOIS) - 1]:
        puces.append(("periode", f"De {mois_texte(MOIS[periode[0]])} à {mois_texte(MOIS[periode[1]])}"))
    for e in etats or []:
        puces.append((f"etat:{e}", NOMS_ETATS.get(e, e)))
    for c in categories or []:
        puces.append((f"cat:{c}", nom_categorie(c)))
    if not puces:
        contenu = [html.Span("Aucun filtre : toute la période, tout le Brésil, toutes les catégories.", className="sans-filtre")]
    else:
        contenu = [html.Span("Filtres actifs", className="libelle-filtres")]
        contenu += [html.Button([texte, html.Span("×", className="croix")], id={"type": "puce", "cle": cle},
                                className="puce", title=f"Retirer le filtre {texte}") for cle, texte in puces]
    if actif == "vendeurs" and etats:
        contenu.append(html.Span("Le filtre des États clients ne s'applique pas à cet onglet.", className="sans-filtre"))
    return contenu


@app.callback(Output("etats", "value"), Output("periode", "value"), Output("categories", "value"),
              Input("g-classement", "clickData"), Input("reset", "n_clicks"), Input({"type": "puce", "cle": ALL}, "n_clicks"),
              State("etats", "value"), State("categories", "value"), prevent_initial_call=True)
def maj_filtres(clic, reset, puces, etats, categories):
    if ctx.triggered_id == "reset":
        return [], [0, len(MOIS) - 1], []
    if isinstance(ctx.triggered_id, dict):
        if not ctx.triggered[0]["value"]:
            return no_update, no_update, no_update
        cle = ctx.triggered_id["cle"]
        if cle == "periode":
            return no_update, [0, len(MOIS) - 1], no_update
        if cle.startswith("etat:"):
            return [e for e in etats or [] if e != cle[5:]], no_update, no_update
        return no_update, no_update, [c for c in categories or [] if c != cle[4:]]
    etat = clic["points"][0]["y"]
    etats = list(etats or [])
    if etat in etats:
        etats.remove(etat)
    else:
        etats.append(etat)
    return etats, no_update, no_update


@app.callback(Output("phrase", "children"), Output("g-ca", "figure"), Output("g-delais", "figure"), Output("g-paiement", "figure"), Output("points", "children"),
              Input("periode", "value"), Input("etats", "value"), Input("categories", "value"), Input("mesure-ca", "value"))
def maj_global(periode, etats, categories, mesure):
    c, a, p = filtrer(periode, etats, categories)
    if len(c) == 0:
        return "Aucune commande livrée ne correspond à ces filtres.", vide(290), vide(), vide(), []
    lieu = "au Brésil" if not etats else ("en " + ", ".join(etats) if len(etats) <= 4 else f"dans {len(etats)} États")
    phrase = ["Entre ", b(mois_texte(MOIS[periode[0]])), " et ", b(mois_texte(MOIS[periode[1]])), ", ",
              b(fr(len(c))), f" commandes livrées {lieu} ont rapporté ", b(f"{fr(a.ca.sum() / 1e6, 1)} M R$"), ". ",
              b(f"{fr(100 * (1 - c.en_retard.mean()), 1)} %"), " sont arrivées à l'heure, et les clients leur donnent ",
              b(fr(c.note.mean(), 2)), " sur 5."]

    mois = MOIS[periode[0]:periode[1] + 1]
    if mesure == "ca":
        serie = a.groupby("mois").ca.sum().reindex(mois, fill_value=0)
        modele = "%{x}<br><b>%{y:,.0f} R$</b><extra></extra>"
    else:
        serie = c.groupby("mois").size().reindex(mois, fill_value=0)
        modele = "%{x}<br><b>%{y:,.0f} commandes</b><extra></extra>"
    x = [mois_texte(m) for m in serie.index]
    fig_ca = go.Figure(go.Scatter(x=x, y=serie.values, mode="lines+markers", line=dict(color="white", width=2.5, shape="spline", smoothing=0.4),
                                  marker=dict(size=8, color="white", line=dict(color=BLEU, width=2)),
                                  fill="tozeroy", fillcolor="rgba(255,255,255,0.10)", hovertemplate=modele))
    if len(serie) > 0 and serie.max() > 0:
        i = int(numpy.argmax(serie.values))
        fig_ca.add_trace(go.Scatter(x=[x[i]], y=[serie.values[i]], mode="markers", hoverinfo="skip",
                                    marker=dict(size=14, color=JAUNE, line=dict(color=BLEU, width=3))))
        fig_ca.add_annotation(x=x[i], y=serie.values[i], text=f"Record : {mois_texte(serie.index[i])}", showarrow=False,
                              yshift=22, font=dict(color="white", size=13))
    style(fig_ca, 290, sur_bleu=True)
    fig_ca.update_xaxes(showgrid=False, tickvals=x[::3])
    fig_ca.update_yaxes(rangemode="tozero")

    d = c.delai.dropna()
    fig_delais = go.Figure(go.Histogram(x=d[d <= 60], xbins=dict(start=0, end=60, size=2), marker_color=BLEU,
                                        marker_line=dict(color="white", width=1),
                                        hovertemplate="%{x} jours<br><b>%{y:,} commandes</b><extra></extra>"))
    med = d.median()
    part30 = 100 * (d > 30).mean()
    fig_delais.add_vline(x=med, line=dict(color=ENCRE, width=1.5, dash="dot"))
    fig_delais.add_annotation(x=med, y=1, yref="paper", text=f"la moitié des colis arrive en {fr(med, 0)} jours ou moins",
                              showarrow=False, xanchor="left", xshift=8, font=dict(color=ENCRE, size=12.5))
    fig_delais.add_annotation(x=45, y=0.35, yref="paper", text=f"{fr(part30, 1)} % au-delà de 30 jours", showarrow=False,
                              font=dict(color=ENCRE2, size=12.5))
    style(fig_delais).update_layout(bargap=0)
    fig_delais.update_xaxes(title="jours entre l'achat et la livraison")
    fig_delais.update_yaxes(title="commandes")

    v = p.groupby("moyen").montant.sum()
    principaux = [m for m in ["credit_card", "boleto"] if m in v.index]
    autres = v.drop(principaux)
    noms = [NOMS_PAIEMENT[m] for m in principaux]
    valeurs = [v[m] for m in principaux]
    couleurs = [BLEU, JAUNE_FONCE][:len(principaux)]
    survol = ["" for m in principaux]
    if autres.sum() > 0:
        noms.append("Autres")
        valeurs.append(autres.sum())
        couleurs.append(GRIS)
        survol.append("<br>".join(f"{NOMS_PAIEMENT.get(m, m)} : {fr(x / v.sum() * 100, 1)} %" for m, x in autres.sort_values(ascending=False).items()))
    fig_pai = go.Figure(go.Pie(labels=noms, values=valeurs, hole=0.62, sort=False, direction="clockwise",
                               marker=dict(colors=couleurs, line=dict(color="white", width=3)),
                               customdata=survol, texttemplate="%{label}<br><b>%{percent:.1%}</b>", textposition="outside",
                               textfont=dict(color=ENCRE, size=13),
                               hovertemplate="%{label}<br><b>%{value:,.0f} R$</b><br>%{customdata}<extra></extra>"))
    fig_pai.add_annotation(text=f"<b>{fr(v.sum() / 1e6, 1)} M R$</b><br>payés", showarrow=False,
                           font=dict(size=15, color=ENCRE, family=TITRE))
    style(fig_pai).update_layout(margin=dict(l=40, r=40, t=30, b=30))
    return phrase, fig_ca, fig_delais, fig_pai, points_attention(c, a)


def carte_folium(val, nb, titre, echelle, decimales, etats):
    vmin, vmax = float(val.min()), float(val.max())
    if vmax == vmin:
        vmax = vmin + 1
    couleurs = cm.LinearColormap([c for _, c in echelle], index=[vmin + p * (vmax - vmin) for p, _ in echelle], vmin=vmin, vmax=vmax)
    entites = []
    for f in BRESIL["features"]:
        sigla = f["properties"]["sigla"]
        v = val.get(sigla, numpy.nan)
        entites.append({"type": "Feature", "geometry": f["geometry"], "properties": {
            "sigla": sigla,
            "nom": f"{NOMS_ETATS.get(sigla, sigla)} ({sigla})",
            "valeur": fr(v, decimales),
            "commandes": fr(nb.get(sigla, 0)),
            "couleur": couleurs(v) if not pandas.isna(v) else BRUME,
            "choisi": sigla in etats,
        }})

    carte = folium.Map(location=[-14.5, -53.5], zoom_start=4, tiles=None, scrollWheelZoom=False)
    carte.get_root().header.add_child(folium.Element(
        "<style>.leaflet-container { background: #EEF2FB !important; font-family: 'Instrument Sans', system-ui, sans-serif; }</style>"))
    folium.GeoJson(
        {"type": "FeatureCollection", "features": entites},
        style_function=lambda f: {"fillColor": f["properties"]["couleur"], "fillOpacity": 0.92,
                                  "color": JAUNE if f["properties"]["choisi"] else "white",
                                  "weight": 4 if f["properties"]["choisi"] else 1.2},
        highlight_function=lambda f: {"weight": 3, "color": ENCRE},
        tooltip=folium.GeoJsonTooltip(
            fields=["nom", "valeur", "commandes"], aliases=["", titre, "Commandes livrées"], labels=True, sticky=True,
            style="font-family: 'Instrument Sans', system-ui, sans-serif; font-size: 13px; color: #071A4F; "
                  "background: white; border: none; border-radius: 10px; box-shadow: 0 8px 24px rgba(7,26,79,.18); padding: 8px 12px;"),
    ).add_to(carte)

    degrade = "linear-gradient(90deg, " + ", ".join(f"{c} {p * 100:.0f}%" for p, c in echelle) + ")"
    legende = [html.Span(titre), html.B(fr(vmin, decimales)), html.Div(className="degrade", style={"background": degrade}),
               html.B(fr(vmax, decimales))]
    return carte.get_root().render(), legende


def points_attention(c, a):
    def point(chiffre, texte, onglet, nom_onglet):
        return html.Div([html.Div(chiffre, className="point-chiffre"), html.P(texte),
                         html.Button(f"Voir l'onglet {nom_onglet}", id={"type": "aller", "onglet": onglet}, className="lien")],
                        className="point")
    liste = []
    r = c.dropna(subset=["retard"])
    if len(r) > 0:
        tard = r[r.retard > 7]
        liste.append(point(f"{fr(100 * len(tard) / len(r), 1)} %",
                           f"des colis arrivent avec plus de 7 jours de retard, et leurs clients donnent {fr(tard.note.mean(), 2)} sur 5 en moyenne.",
                           "livraison", "Livraison"))
        liste.append(point(f"{fr(-r.retard.mean(), 0)} jours",
                           "d'avance en moyenne sur la date promise : une partie de cette marge peut être rendue au client, État par État.",
                           "livraison", "Livraison"))
    par_etat = r.groupby("etat").agg(nb=("order_id", "size"), retard=("en_retard", "mean"))
    par_etat = par_etat[par_etat.nb >= 100]
    if len(par_etat) > 0:
        pire = par_etat.retard.idxmax()
        liste.append(point(f"{fr(100 * par_etat.retard.max(), 0)} %",
                           f"de colis en retard en {NOMS_ETATS.get(pire, pire)}, l'État le plus touché parmi ceux d'au moins 100 commandes.",
                           "carte", "Carte du Brésil"))
    s = stats_vendeurs(a)
    s = s[s.nb_commandes >= 20]
    mal = s[s.note < 3.5]
    if len(s) > 0:
        liste.append(point(fr(len(mal)),
                           f"vendeurs d'au moins 20 commandes sont notés sous 3,5, pour {compact(mal.ca.sum())} R$ de ventes.",
                           "vendeurs", "Vendeurs"))
    return liste


INDICATEURS = {
    "ca": ("Chiffre d'affaires (R$)", SEQ_BLEU, ",.0f", "consolider la position dans les États les plus foncés et tester des campagnes dans les États clairs à fort potentiel de population."),
    "delai": ("Délai moyen (jours)", SEQ_BLEU, ".1f", "renégocier les contrats transporteurs dans les États les plus foncés, surtout au Nord et au Nordeste."),
    "retard": ("Taux de retard (%)", SEQ_BLEU, ".1f", "auditer les transporteurs des États les plus foncés, où la date promise est le moins souvent tenue."),
    "note": ("Note moyenne (sur 5)", SEQ_BLEU, ".2f", "croiser avec le délai : une note faible là où les livraisons sont lentes désigne la logistique, pas les produits."),
    "panier": ("Panier moyen (R$)", SEQ_BLEU, ".0f", "réserver les mises en avant de produits chers aux États où le panier est le plus élevé."),
}


@app.callback(Output("carte-folium", "srcDoc"), Output("legende-choro", "children"), Output("g-classement", "figure"), Output("decision-choro", "children"),
              Output("t-etats", "data"), Output("t-etats", "columns"),
              Output("constat-carte", "children"),
              Input("periode", "value"), Input("categories", "value"), Input("etats", "value"), Input("indicateur", "value"))
def maj_carte(periode, categories, etats, indicateur):
    c, a, p = filtrer(periode, None, categories)
    if len(c) == 0:
        return "", "", vide(596), "", [], [], "Aucune commande livrée ne correspond à ces filtres."
    g = c.groupby("etat").agg(delai=("delai", "mean"), retard=("en_retard", "mean"), note=("note", "mean"),
                              panier=("montant", "mean"), nb=("order_id", "size"))
    g["ca"] = a.groupby("etat").ca.sum()
    g["retard"] = 100 * g.retard
    titre, echelle, fmt, texte = INDICATEURS[indicateur]
    val = g[indicateur]
    haut, bas = val.idxmax(), val.idxmin()
    if indicateur == "ca":
        constat = [b(NOMS_ETATS.get(haut, haut)), " pèse à lui seul ", b(f"{fr(100 * val[haut] / val.sum(), 0)} %"),
                   " du chiffre d'affaires ; les trois premiers États en font ", b(f"{fr(100 * val.nlargest(3).sum() / val.sum(), 0)} %"), "."]
    elif indicateur == "delai":
        constat = ["Un client de ", b(NOMS_ETATS.get(haut, haut)), " attend en moyenne ", b(f"{fr(val[haut], 0)} jours"),
                   ", contre ", b(f"{fr(val[bas], 0)}"), " à ", b(NOMS_ETATS.get(bas, bas)), "."]
    elif indicateur == "retard":
        constat = ["En ", b(NOMS_ETATS.get(haut, haut)), ", ", b(f"{fr(val[haut], 0)} %"), " des colis arrivent après la date promise, contre ",
                   b(f"{fr(val[bas], 0)} %"), " en ", b(NOMS_ETATS.get(bas, bas)), "."]
    elif indicateur == "note":
        constat = ["La note moyenne va de ", b(fr(val[bas], 2)), " en ", b(NOMS_ETATS.get(bas, bas)), " à ", b(fr(val[haut], 2)),
                   " en ", b(NOMS_ETATS.get(haut, haut)), "."]
    else:
        constat = ["Le panier moyen culmine en ", b(NOMS_ETATS.get(haut, haut)), " à ", b(f"{fr(val[haut], 0)} R$"),
                   ", contre ", b(f"{fr(val[bas], 0)} R$"), " en ", b(NOMS_ETATS.get(bas, bas)), "."]

    decimales = {",.0f": 0, ".0f": 0, ".1f": 1, ".2f": 2}[fmt]
    carte, legende = carte_folium(val, g.nb, titre, echelle, decimales, etats or [])

    t = val.sort_values()
    couleurs = [JAUNE_FONCE if e in (etats or []) else BLEU for e in t.index]
    fig_c = go.Figure(go.Bar(x=t.values, y=t.index, orientation="h", marker=dict(color=couleurs, cornerradius=6),
                             customdata=[NOMS_ETATS.get(e, e) for e in t.index],
                             hovertemplate="<b>%{customdata}</b> : %{x:" + fmt + "}<extra></extra>"))
    style(fig_c, 596).update_layout(bargap=0.28)
    unite = {"ca": "", "delai": " j", "retard": " %", "note": "", "panier": " R$"}[indicateur]
    textes = [compact(v) if indicateur == "ca" else fr(v, {",.0f": 0, ".0f": 0, ".1f": 1, ".2f": 2}[fmt]) + unite for v in t.values]
    barres_h(fig_c, textes, float(t.max()))
    fig_c.update_yaxes(dtick=1, tickfont=dict(size=11.5))
    tableau = pandas.DataFrame({
        "État": [f"{NOMS_ETATS.get(e, e)} ({e})" for e in g.index],
        "Commandes": g.nb.values,
        "Chiffre d'affaires (R$)": g.ca.round(0).values,
        "Panier moyen (R$)": g.panier.round(0).values,
        "Délai moyen (j)": g.delai.round(1).values,
        "Retard (%)": g.retard.round(1).values,
        "Note": g.note.round(2).values,
    }).sort_values("Chiffre d'affaires (R$)", ascending=False)
    decimales = {"Commandes": 0, "Chiffre d'affaires (R$)": 0, "Panier moyen (R$)": 0, "Délai moyen (j)": 1, "Retard (%)": 1, "Note": 2}
    colonnes = [{"name": col, "id": col, "type": "numeric", "format": Format(precision=decimales[col], scheme=Scheme.fixed, group=True)}
                if col in decimales else {"name": col, "id": col, "type": "text"} for col in tableau.columns]
    return carte, legende, fig_c, decision_choro(g, indicateur, c), tableau.to_dict("records"), colonnes, constat


@app.callback(Output("g-note-retard", "figure"), Output("g-heure", "figure"), Output("g-heatmap", "figure"), Output("g-correlation", "figure"),
              Output("constat-satisfaction", "children"), Output("g-promesse", "figure"), Output("g-plaintes", "figure"),
              Input("periode", "value"), Input("etats", "value"), Input("categories", "value"))
def maj_satisfaction(periode, etats, categories):
    c, a, p = filtrer(periode, etats, categories)
    c = c.dropna(subset=["retard"])
    if len(c) == 0:
        return vide(), vide(), vide(520), vide(520), "Aucune commande livrée ne correspond à ces filtres.", vide(), vide()

    tranches = pandas.cut(c.retard, [-numpy.inf, 0, 3, 7, numpy.inf], labels=["À l'heure", "1 à 3 jours", "4 à 7 jours", "Plus de 7 jours"])
    t = c.groupby(tranches, observed=False).agg(note=("note", "mean"), nb=("order_id", "size"))
    part = 100 * t.nb / t.nb.sum()
    fig1 = go.Figure(go.Bar(x=t.index.astype(str), y=t.note, marker=dict(color=[BLEU, BLEU, JAUNE_FONCE, JAUNE_FONCE], cornerradius=6),
                            text=[fr(n, 2) for n in t.note], textposition="outside", textfont=dict(family=TITRE, size=13, color=ENCRE), cliponaxis=False,
                            customdata=numpy.stack([t.nb, part], axis=-1),
                            hovertemplate="%{x}<br><b>note %{y:.2f}</b><br>%{customdata[0]:,} commandes (%{customdata[1]:.1f} %)<extra></extra>"))
    style(fig1)
    barres_v(fig1, 5)
    fig1.update_xaxes(ticktext=[f"{k}<br><span style='font-size:11px'>{fr(v, 1)} % des colis</span>" for k, v in zip(t.index.astype(str), part)],
                      tickvals=t.index.astype(str))

    m = c.groupby("mois").agg(taux=("en_retard", "mean"), nb=("order_id", "size"))
    m = m[m.nb >= 30]
    m["taux"] = 100 * (1 - m.taux)
    moyenne = 100 * (1 - c.en_retard.mean())
    xm = [mois_texte(k) for k in m.index]
    sous_moyenne = m.taux < moyenne - 5
    fig2 = go.Figure(go.Scatter(x=xm, y=m.taux, mode="lines+markers", line=dict(color=BLEU, width=2.5),
                                marker=dict(size=8, color=[JAUNE_FONCE if s else BLEU for s in sous_moyenne], line=dict(color="white", width=2)),
                                customdata=m.nb, hovertemplate="%{x}<br><b>%{y:.1f} % à l'heure</b><br>%{customdata:,} commandes<extra></extra>"))
    fig2.add_hline(y=moyenne, line=dict(color=ENCRE2, width=1, dash="dot"),
                   annotation_text=f"moyenne {fr(moyenne, 1)} %", annotation_position="bottom left", annotation_font_color=ENCRE2)
    style(fig2)
    fig2.update_yaxes(title="livrées à l'heure", ticksuffix=" %")
    fig2.update_xaxes(showgrid=False, tickvals=xm[::3])

    classes = pandas.cut(c.delai, [-numpy.inf, 8, 15.0000001, numpy.inf], right=False, labels=["Rapide, moins de 8 j", "Normale, 8 à 15 j", "Lente, plus de 15 j"])
    h = c.assign(classe=classes).groupby(["etat", "classe"], observed=False).agg(note=("note", "mean"), nb=("order_id", "size")).reset_index()
    ordre = c.groupby("etat").size().sort_values(ascending=False).index[:15]
    pivot = h.pivot(index="etat", columns="classe", values="note").reindex(ordre)
    nb = h.pivot(index="etat", columns="classe", values="nb").reindex(ordre)
    pivot = pivot.where(nb >= 20)
    z = pivot.astype(object).where(pivot.notna(), None).values
    fig3 = go.Figure(go.Heatmap(z=z, x=["Rapide<br>moins de 8 j", "Normale<br>8 à 15 j", "Lente<br>plus de 15 j"], y=pivot.index,
                                colorscale=SEQ_BLEU, zmin=3.2, zmax=4.6, xgap=4, ygap=4, customdata=nb.values,
                                texttemplate="%{z:.2f}", textfont=dict(family=TITRE, size=13),
                                colorbar=dict(title=dict(text="note", side="right"), thickness=10, outlinewidth=0, len=0.7),
                                hovertemplate="<b>%{y}</b>, livraison %{x}<br>note %{z:.2f}<br>%{customdata:,} commandes<extra></extra>"))
    style(fig3, 520)
    fig3.update_xaxes(side="top", showgrid=False, tickfont=dict(size=12, color=ENCRE))
    fig3.update_yaxes(autorange="reversed", showgrid=False, tickfont=dict(size=12, color=ENCRE))

    cc = c.dropna(subset=["note"])
    corr = cc.groupby("etat").apply(lambda x: x.retard.corr(x.note) if len(x) >= 30 else numpy.nan, include_groups=False).dropna().sort_values(ascending=False)
    fig4 = go.Figure(go.Bar(x=corr.values, y=corr.index, orientation="h",
                            marker=dict(color=couleurs_alerte(-corr, 3), cornerradius=6),
                            customdata=[NOMS_ETATS.get(e, e) for e in corr.index],
                            hovertemplate="<b>%{customdata}</b><br>corrélation %{x:.2f}<extra></extra>"))
    style(fig4, 520).update_layout(bargap=0.28)
    barres_h(fig4, [fr(v, 2) for v in corr.values], 0, float(corr.min()))
    fig4.update_yaxes(dtick=1, tickfont=dict(size=11.5), side="right")

    constat = ["Au-delà de 7 jours de retard, la note moyenne tombe de ", b(fr(t.note.iloc[0], 2)), " à ", b(fr(t.note.iloc[-1], 2)),
               ". Cela concerne ", b(f"{fr(part.iloc[-1], 1)} %"), " des colis."]
    avance = (-c.retard).clip(-30, 45)
    fig5 = go.Figure([
        go.Histogram(x=avance[avance >= 0], xbins=dict(start=0, end=46, size=1), marker=dict(color=BLEU, line=dict(color="white", width=1)),
                     name="Livrées avant la date promise", hovertemplate="%{x} jours d'avance<br><b>%{y:,} commandes</b><extra></extra>"),
        go.Histogram(x=avance[avance < 0], xbins=dict(start=-30, end=0, size=1), marker=dict(color=JAUNE_FONCE, line=dict(color="white", width=1)),
                     name="Livrées en retard", hovertemplate="%{x} jours<br><b>%{y:,} commandes</b><extra></extra>"),
    ])
    fig5.add_vline(x=avance.mean(), line=dict(color=ENCRE, width=1.5, dash="dot"))
    fig5.add_annotation(x=avance.mean(), y=0.88, yref="paper", xanchor="left", xshift=8, showarrow=False, bgcolor="rgba(255,255,255,0.85)",
                        text=f"en moyenne <b>{fr(avance.mean(), 0)} jours d'avance</b>", font=dict(color=ENCRE, size=13))
    style(fig5, legende=True).update_layout(barmode="overlay", bargap=0.05)
    fig5.update_xaxes(title="jours d'avance sur la date annoncée (négatif = retard)")
    fig5.update_yaxes(title="commandes")

    av = avis[avis.order_id.isin(c.order_id)]
    neg, pos = av[av.note <= 2], av[av.note >= 4]
    if len(neg) > 0 and len(pos) > 0:
        t = pandas.DataFrame({"neg": neg[list(THEMES)].mean() * 100, "pos": pos[list(THEMES)].mean() * 100}).sort_values("neg")
        fig6 = go.Figure([
            go.Bar(y=t.index, x=t.neg, orientation="h", name="Avis à 1-2 étoiles", marker=dict(color=JAUNE_FONCE, cornerradius=6),
                   text=[f"{fr(v, 0)} %" for v in t.neg], textposition="outside", textfont=dict(color=ENCRE), cliponaxis=False,
                   hovertemplate="%{y}<br><b>%{x:.1f} % des avis négatifs</b><extra></extra>"),
            go.Bar(y=t.index, x=t.pos, orientation="h", name="Avis à 4-5 étoiles", marker=dict(color=GRIS, cornerradius=6),
                   hovertemplate="%{y}<br>%{x:.1f} % des avis positifs<extra></extra>"),
        ])
        style(fig6, legende=True).update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
        fig6.update_traces(textfont=dict(family=TITRE, size=13, color=ENCRE))
        fig6.update_xaxes(showticklabels=False, showgrid=False, range=[0, t.neg.max() * 1.22])
        fig6.update_yaxes(tickfont=dict(size=12, color=ENCRE))
    else:
        fig6 = vide(340, "Pas assez d'avis commentés pour ces filtres.")
    return fig1, fig2, fig3, fig4, constat, fig5, fig6


@app.callback(Output("g-categories", "figure"), Output("g-recurrents", "figure"), Output("g-port", "figure"), Output("g-ratio", "figure"),
              Output("constat-commercial", "children"), Output("g-heures", "figure"),
              Input("periode", "value"), Input("etats", "value"), Input("categories", "value"))
def maj_commercial(periode, etats, categories):
    c, a, p = filtrer(periode, etats, categories)
    if len(c) == 0:
        return vide(500), vide(500), vide(), vide(), "Aucune commande livrée ne correspond à ces filtres.", vide(320)

    cat = a.groupby("categorie").ca.sum().sort_values(ascending=False)
    part = 100 * cat / cat.sum()
    top = cat.head(10)[::-1]
    fig1 = go.Figure(go.Bar(x=top.values, y=[nom_categorie(x) for x in top.index], orientation="h",
                            marker=dict(color=BLEU, cornerradius=6),
                            hovertemplate="<b>%{y}</b><br>%{x:,.0f} R$<extra></extra>"))
    style(fig1, 500).update_layout(bargap=0.28)
    barres_h(fig1, [f"{compact(v)} R$   {fr(part[k], 1)} %" for k, v in top.items()], float(top.max()) * 1.15, reference=10)

    dernier = c.sort_values("achat").groupby("uid").agg(etat=("etat", "last"), nb=("order_id", "size"))
    r = dernier.groupby("etat").agg(clients=("nb", "size"), recurrents=("nb", lambda s: (s >= 2).sum()))
    r = r[r.clients >= 50]
    r["taux"] = 100 * r.recurrents / r.clients
    r = r.sort_values("taux")
    if len(r) > 0:
        fig2 = go.Figure(go.Bar(x=r.taux, y=r.index, orientation="h",
                                marker=dict(color=couleurs_alerte(r.taux, 3, plus_grands=False), cornerradius=6),
                                customdata=numpy.stack([r.recurrents, r.clients, [NOMS_ETATS.get(e, e) for e in r.index]], axis=-1),
                                hovertemplate="<b>%{customdata[2]}</b><br>%{x:.2f} % de clients récurrents<br>%{customdata[0]} sur %{customdata[1]} clients<extra></extra>"))
        style(fig2, 500).update_layout(bargap=0.28)
        barres_h(fig2, [f"{fr(v, 1)} %" for v in r.taux], float(r.taux.max()))
        fig2.update_yaxes(dtick=1, tickfont=dict(size=11.5), autorange="reversed")
    else:
        fig2 = vide(500, "Pas assez de clients (50 minimum par État) pour ce filtre.")

    q = a[a.prix > 0]
    tranche = pandas.cut(q.frais_port / q.prix, [-numpy.inf, 0.15, 0.40, 1, numpy.inf], right=False,
                         labels=["moins de 15 %", "15 à 40 %", "40 à 100 %", "plus cher que l'article"])
    t = q.groupby(tranche, observed=False).agg(note=("note", "mean"), nb=("order_id", "size"), prix=("prix", "mean"))
    fig3 = go.Figure(go.Bar(x=t.index.astype(str), y=t.note, marker=dict(color=[BLEU, BLEU, BLEU, JAUNE_FONCE], cornerradius=6),
                            text=[fr(n, 2) for n in t.note], textposition="outside", textfont=dict(family=TITRE, size=13, color=ENCRE), cliponaxis=False,
                            customdata=numpy.stack([t.nb, t.prix], axis=-1),
                            hovertemplate="port %{x} du prix<br><b>note %{y:.2f}</b><br>%{customdata[0]:,} articles, prix moyen %{customdata[1]:.0f} R$<extra></extra>"))
    style(fig3)
    bas = numpy.nanmin(t.note.values) if t.note.notna().any() else 3.5
    barres_v(fig3, 4.4, max(0, bas - 0.4))
    fig3.update_xaxes(title="frais de port rapportés au prix de l'article")

    cl = c.groupby("etat").uid.nunique()
    ve = vendeurs_actifs(periode, categories)
    ratio = (cl / ve).dropna()
    if etats:
        ratio = ratio[ratio.index.isin(etats)]
    ratio = ratio.sort_values(ascending=False).head(15)
    fig4 = go.Figure(go.Bar(x=ratio.values, y=ratio.index, orientation="h",
                            marker=dict(color=couleurs_alerte(ratio, 3), cornerradius=6),
                            customdata=numpy.stack([cl[ratio.index], ve[ratio.index], [NOMS_ETATS.get(e, e) for e in ratio.index]], axis=-1),
                            hovertemplate="<b>%{customdata[2]}</b><br>%{x:,.0f} clients par vendeur<br>%{customdata[0]} clients, %{customdata[1]} vendeurs<extra></extra>"))
    style(fig4).update_layout(bargap=0.28)
    barres_h(fig4, [fr(v, 0) for v in ratio.values], float(ratio.max()), reference=15)
    fig4.update_yaxes(dtick=1, autorange="reversed", tickfont=dict(size=11.5))

    total = len(dernier)
    taux = 100 * (dernier.nb >= 2).mean()
    constat = ["Les dix premières catégories font ", b(f"{fr(part.head(10).sum(), 0)} %"), " des ventes, mais seuls ",
               b(f"{fr(taux, 1)} %"), " des ", b(fr(total)), " clients ont commandé une deuxième fois."]
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    grille = c.groupby([c.achat.dt.dayofweek, c.achat.dt.hour]).size().unstack(fill_value=0).reindex(index=range(7), columns=range(24), fill_value=0)
    fig5 = go.Figure(go.Heatmap(z=grille.values, x=[f"{h} h" for h in range(24)], y=jours, colorscale=SEQ_BLEU, xgap=2, ygap=2,
                                colorbar=dict(title=dict(text="commandes", side="right"), thickness=10, outlinewidth=0),
                                hovertemplate="%{y} à %{x}<br><b>%{z:,} commandes</b><extra></extra>"))
    style(fig5, 320)
    fig5.update_yaxes(autorange="reversed", showgrid=False)
    fig5.update_xaxes(showgrid=False, dtick=2)
    return fig1, fig2, fig3, fig4, constat, fig5


def classe_perf(s, critere):
    if critere == "note":
        return numpy.select([s.note >= 4.2, s.note >= 3.5], ["bien", "moyen"], "mal")
    return numpy.select([s.retard < 0.05, s.retard < 0.10], ["bien", "moyen"], "mal")


LEGENDES = {
    "note": {"bien": "Note de 4,2 et plus", "moyen": "Note entre 3,5 et 4,2", "mal": "Note sous 3,5"},
    "retard": {"bien": "Moins de 5 % de retards", "moyen": "5 à 10 % de retards", "mal": "Plus de 10 % de retards"},
}


@app.callback(Output("g-vendeurs", "figure"), Output("vendeur", "options"), Output("vendeur", "value"), Output("constat-vendeurs", "children"),
              Input("periode", "value"), Input("categories", "value"), Input("v-etats", "value"), Input("v-min", "value"),
              Input("v-couleur", "value"), Input("g-vendeurs", "clickData"), State("vendeur", "value"))
def maj_vendeurs(periode, categories, v_etats, v_min, critere, clic, actuel):
    if ctx.triggered_id == "g-vendeurs":
        return no_update, no_update, clic["points"][0]["customdata"][0], no_update
    c, a, p = filtrer(periode, None, categories)
    s = stats_vendeurs(a)
    s = s[s.nb_commandes >= v_min]
    if v_etats:
        s = s[s.vetat.isin(v_etats)]
    if len(s) == 0:
        return vide(560, "Aucun vendeur ne passe ce seuil. Baissez le nombre minimal de commandes."), [], None, "Aucun vendeur ne correspond à ces réglages."
    s = s.assign(classe=classe_perf(s, critere), ville=s.vville.str.title()).sort_values("ca", ascending=False)

    fig = go.Figure()
    for classe, couleur in [("bien", BLEU), ("moyen", CLAIR), ("mal", JAUNE_FONCE)]:
        g = s[s.classe == classe]
        fig.add_trace(go.Scattermap(
            lat=g.vlat, lon=g.vlng, mode="markers", name=f"{LEGENDES[critere][classe]} ({len(g)})",
            marker=dict(size=numpy.clip(numpy.sqrt(g.ca) / 11, 9, 36), color=couleur, opacity=0.82),
            customdata=numpy.stack([g.vendeur_id, g.ville, g.vetat, g.nb_commandes, g.ca, g.note, g.traitement, g.retard * 100], axis=-1),
            hovertemplate="<b>%{customdata[1]} (%{customdata[2]})</b><br>%{customdata[3]:,} commandes<br>%{customdata[4]:,.0f} R$ de chiffre d'affaires<br>"
                          "note %{customdata[5]:.2f}, %{customdata[7]:.1f} % de retards<br>expédie en %{customdata[6]:.1f} jours en moyenne<extra></extra>"))
    fond_bresil(fig, -15.5, -53, 3.12)
    fig.update_layout(clickmode="event")
    style(fig, 560, legende=True).update_layout(legend=dict(bgcolor="rgba(255,255,255,0.9)", y=0.97, x=0.01, orientation="v"))

    options = [{"label": f"{r.ville} ({r.vetat}), {fr(r.nb_commandes)} commandes, réf. {r.vendeur_id[:8]}", "value": r.vendeur_id}
               for r in s.itertuples()]
    valeur = actuel if actuel in set(s.vendeur_id) else s.vendeur_id.iloc[0]
    nb_mal = int((s.classe == "mal").sum())
    critere_txt = "une note sous 3,5" if critere == "note" else "plus de 10 % de retards"
    constat = [b(fr(len(s))), f" vendeurs ont au moins {v_min} commandes sur la période. ", b(fr(nb_mal)),
               f" d'entre eux ont {critere_txt}, pour ", b(f"{fr(s[s.classe == 'mal'].ca.sum() / 1e3, 0)} k R$"), " de ventes."]
    return fig, options, valeur, constat


@app.callback(Output("v-titre", "children"), Output("v-fiche", "children"), Output("g-zones", "figure"), Output("g-distance", "figure"),
              Output("t-commandes", "data"), Output("t-commandes", "columns"),
              Input("vendeur", "value"), Input("periode", "value"), Input("categories", "value"))
def maj_fiche(vendeur, periode, categories):
    if not vendeur:
        return "", [], vide(460), vide(460), [], []
    c, a, p = filtrer(periode, None, categories)
    a = a[a.vendeur_id == vendeur]
    if len(a) == 0:
        return "Ce vendeur n'a pas de commande livrée sur cette période.", [], vide(460), vide(460), [], []
    vc = a.groupby("order_id").agg(achat=("achat", "first"), etat=("etat", "first"), ville=("ville", "first"),
                                   clat=("clat", "first"), clng=("clng", "first"), nb=("prix", "size"), ca=("ca", "sum"),
                                   delai=("delai", "first"), retard=("retard", "first"), en_retard=("en_retard", "first"),
                                   traitement=("traitement", "first"), note=("note", "first"), distance=("distance", "first"),
                                   vlat=("vlat", "first"), vlng=("vlng", "first"), vville=("vville", "first"), vetat=("vetat", "first"))
    ville = str(vc.vville.iloc[0]).title()
    titre = ["Vendeur de ", b(f"{ville} ({vc.vetat.iloc[0]})"), " : ", b(fr(len(vc))), " commandes, livrées en moyenne à ",
             b(f"{fr(vc.distance.mean(), 0)} km"), " de chez lui."]

    def item(label, valeur, detail=None):
        dd = [valeur]
        if detail:
            dd += [" ", html.Small(detail)]
        return html.Div([html.Dt(label), html.Dd(dd)])

    fiche = [
        item("Chiffre d'affaires", f"{fr(vc.ca.sum(), 0)} R$"),
        item("Note moyenne", fr(vc.note.mean(), 2), "sur 5"),
        item("Colis en retard", f"{fr(100 * vc.en_retard.mean(), 1)} %"),
        item("Expédition", f"{fr(vc.traitement.mean(), 1)} j", "de l'achat au transporteur"),
        item("Livraison", f"{fr(vc.delai.mean(), 1)} j", "de l'achat au client"),
    ]

    geo = vc.dropna(subset=["clat", "vlat"])
    fig_z = go.Figure()
    if len(geo) > 0:
        vlat, vlng = geo.vlat.iloc[0], geo.vlng.iloc[0]
        lats, lngs = [], []
        for la, ln in zip(geo.clat, geo.clng):
            lats += [vlat, la, None]
            lngs += [vlng, ln, None]
        fig_z.add_trace(go.Scattermap(lat=lats, lon=lngs, mode="lines", line=dict(width=1, color="rgba(10,78,228,0.22)"),
                                      hoverinfo="skip", showlegend=False))
        for nom, masque, couleur in [("Livrés à l'heure", geo.en_retard == 0, BLEU), ("Livrés en retard", geo.en_retard == 1, JAUNE_FONCE)]:
            g = geo[masque]
            fig_z.add_trace(go.Scattermap(lat=g.clat, lon=g.clng, mode="markers", name=f"{nom} ({len(g)})",
                                          marker=dict(size=8, color=couleur, opacity=0.85),
                                          customdata=numpy.stack([g.ville.str.title(), g.etat, g.delai, g.distance], axis=-1),
                                          hovertemplate="%{customdata[0]} (%{customdata[1]})<br>%{customdata[3]:.0f} km, livré en %{customdata[2]:.1f} jours<extra></extra>"))
        fig_z.add_trace(go.Scattermap(lat=[vlat], lon=[vlng], mode="markers", name="Le vendeur",
                                      marker=dict(size=20, color=ENCRE), hovertemplate=f"Le vendeur, à {ville}<extra></extra>"))
        etendue = max(geo.clat.max() - geo.clat.min(), geo.clng.max() - geo.clng.min(), 1)
        zoom = float(numpy.clip(8 - numpy.log2(etendue * 2), 2.8, 9))
        fond_bresil(fig_z, (geo.clat.max() + geo.clat.min()) / 2, (geo.clng.max() + geo.clng.min()) / 2, zoom)
    style(fig_z, 460, legende=True).update_layout(legend=dict(bgcolor="rgba(255,255,255,0.9)", y=0.97, x=0.01, orientation="v"))

    d = vc.dropna(subset=["distance", "delai"])
    if len(d) >= 3:
        r = d.distance.corr(d.delai)
        pente, origine = numpy.polyfit(d.distance, d.delai, 1)
        xs = numpy.array([d.distance.min(), d.distance.max()])
        fig_d = go.Figure(go.Scatter(x=d.distance, y=d.delai, mode="markers", name="commandes",
                                     marker=dict(size=8, color=BLEU, opacity=0.45, line=dict(color="white", width=1)),
                                     hovertemplate="%{x:.0f} km<br><b>%{y:.1f} jours</b><extra></extra>"))
        fig_d.add_trace(go.Scatter(x=xs, y=origine + pente * xs, mode="lines", name="tendance",
                                   line=dict(color=JAUNE_FONCE, width=3), hoverinfo="skip"))
        fig_d.add_annotation(x=0.02, y=0.98, xref="paper", yref="paper", xanchor="left", yanchor="top", showarrow=False,
                             align="left", font=dict(color=ENCRE, size=13), bgcolor="rgba(255,255,255,0.9)",
                             text=f"<b>+{fr(pente * 100, 1)} jour</b> tous les 100 km<br>corrélation {fr(r, 2)}")
        style(fig_d, 460)
        fig_d.update_xaxes(title="distance entre le vendeur et le client (km)")
        fig_d.update_yaxes(title="délai de livraison (jours)")
    else:
        fig_d = vide(460, "Moins de 3 commandes géolocalisées : pas de tendance à tracer.")

    t = vc.sort_values("achat", ascending=False).reset_index()
    table = pandas.DataFrame({
        "Commande": t.order_id.str[:10],
        "Achat": t.achat.dt.strftime("%d/%m/%Y"),
        "Client": t.ville.str.title() + " (" + t.etat + ")",
        "Articles": t.nb,
        "Montant (R$)": t.ca.round(2),
        "Distance (km)": t.distance.round(0),
        "Délai (j)": t.delai.round(1),
        "Retard (j)": t.retard.round(1),
        "Note": t.note.round(1),
    })
    decimales = {"Articles": 0, "Montant (R$)": 2, "Distance (km)": 0, "Délai (j)": 1, "Retard (j)": 1, "Note": 1}
    colonnes = []
    for col in table.columns:
        if col in decimales:
            colonnes.append({"name": col, "id": col, "type": "numeric",
                             "format": Format(precision=decimales[col], scheme=Scheme.fixed, group=True)})
        else:
            colonnes.append({"name": col, "id": col, "type": "text"})
    return titre, fiche, fig_z, fig_d, table.to_dict("records"), colonnes



def liste(codes):
    noms = [NOMS_ETATS.get(e, e) for e in codes]
    if len(noms) <= 1:
        return "".join(noms)
    return ", ".join(noms[:-1]) + " et " + noms[-1]


def dans(codes):
    codes = list(codes)
    noms = liste(codes)
    de = "d'" if noms[:1] in "AEIOUÉÂ" else "de "
    return ("dans l'État " if len(codes) == 1 else "dans les États ") + de + noms


def dec(role, *morceaux, objectif=None):
    contenu = [html.B(role + " : ")] + list(morceaux)
    if objectif:
        contenu.append(html.Span([html.B("Objectif : ")] + list(objectif), className="objectif"))
    return contenu


def jours(k):
    return f"{k} jour" if k <= 1 else f"{k} jours"


def de_mois(m):
    texte = mois_texte(m)
    return ("d'" if texte[0] in "ao" else "de ", b(texte))


def pct(x, d=1):
    return b(f"{fr(x, d)} %")


def decisions_global(c, a, p):
    ca_mois = a.groupby("mois").ca.sum()
    ca_mois = ca_mois[ca_mois > 0]
    if len(ca_mois) >= 2:
        pic = ca_mois.idxmax()
        ecart = 100 * (ca_mois[pic] / ca_mois.mean() - 1)
        heure_pic = 100 * (1 - c[c.mois == pic].en_retard.mean())
        heure = 100 * (1 - c.en_retard.mean())
        recent = len(ca_mois) >= 6 and list(ca_mois.index).index(pic) >= len(ca_mois) - 3
        if recent and ecart >= 30:
            d_ca = dec("Directeur général", "le meilleur mois est l'un des plus récents (", b(mois_texte(pic)), ", ", pct(ecart, 0),
                       " au-dessus de la moyenne) : la hausse vient de la croissance plus que d'un pic ponctuel. ",
                       "Augmenter en continu la capacité transporteurs et le nombre de vendeurs.",
                       objectif=["garder au moins ", pct(heure), " de livraisons à l'heure malgré la hausse des volumes."])
        elif ecart < 30:
            d_ca = dec("Directeur général", "l'activité est régulière : le meilleur mois, ", b(mois_texte(pic)), ", ne dépasse la moyenne que de ",
                       pct(ecart, 0), ". Pas de dispositif exceptionnel à prévoir : piloter stocks et transporteurs au mois.")
        elif heure_pic >= heure - 1:
            d_ca = dec("Directeur général", "le pic ", *de_mois(pic), " (", pct(ecart, 0), " au-dessus de la moyenne) a été bien absorbé : ",
                       pct(heure_pic), " de livraisons à l'heure. Reconduire le même dispositif stocks et transporteurs au prochain pic.")
        else:
            d_ca = dec("Directeur général", "le pic ", *de_mois(pic), " a dépassé de ", pct(ecart, 0),
                       " la moyenne mensuelle, et la ponctualité y est tombée à ", pct(heure_pic),
                       ". Réserver stocks vendeurs et capacité transporteurs un mois avant le prochain pic.",
                       objectif=["garder au moins ", pct(heure), " de livraisons à l'heure pendant le pic."])
    else:
        d_ca = "élargir la période pour comparer les mois entre eux."

    d = c.delai.dropna()
    n30 = int((d > 30).sum())
    p30 = 100 * n30 / len(d) if len(d) else 0
    if p30 < 2:
        d_delais = dec("Directeur logistique", "la moitié des colis arrive en ", b(f"{fr(d.median(), 0)} jours"), " et seulement ", pct(p30),
                       " des commandes dépassent 30 jours : la traîne est maîtrisée. Surveiller ce taux sans action particulière.")
    else:
        longues = c[c.delai > 30].etat.value_counts()
        part_top = 100 * longues.head(3).sum() / longues.sum()
        d_delais = dec("Directeur logistique", "la moitié des colis arrive en ", b(f"{fr(d.median(), 0)} jours"), ", mais ", b(fr(n30)),
                       " commandes (", pct(p30), ") dépassent 30 jours, dont ", pct(part_top, 0), " vers ", liste(longues.index[:3]),
                       ". Commencer par ces destinations pour réduire la traîne.",
                       objectif=["passer sous ", pct(max(p30 / 2, 2)), " de commandes livrées en plus de 30 jours."])

    v = p.groupby("moyen").montant.sum()
    carte_credit, boleto = v.get("credit_card", 0), v.get("boleto", 0)
    part_boleto = 100 * boleto / v.sum()
    if part_boleto >= 25:
        d_pai = dec("Directeur financier", "le boleto porte ", pct(part_boleto, 0), " des montants payés (", b(f"{compact(boleto)} R$"),
                    ") : ces paiements ne sont encaissés qu'après le règlement du client, ce qui retarde l'expédition. Inciter au paiement par carte (remise, paiement en plusieurs fois sans frais).")
    else:
        d_pai = dec("Directeur financier", "la carte de crédit porte ", pct(100 * carte_credit / v.sum(), 0), " des montants payés (",
                    b(f"{compact(carte_credit)} R$"), "). Négocier d'abord ses commissions : chaque point gagné vaut ",
                    b(f"{compact(carte_credit * 0.01)} R$"), " sur la période.")
    return d_ca, d_delais, d_pai


def decision_choro(g, indicateur, c):
    val = g[indicateur]
    gros = g[g.nb >= 100]
    if len(gros) < 3:
        return "pas assez d'États avec 100 commandes sur cette sélection pour comparer."
    if indicateur == "ca":
        top = val.nlargest(6)
        part3 = 100 * top.iloc[:3].sum() / val.sum()
        part_suivants = 100 * top.iloc[3:].sum() / val.sum()
        if part3 >= 60:
            return dec("Directeur commercial", liste(top.index[:3]), " font ", pct(part3, 0),
                       " du chiffre d'affaires : la plateforme dépend de trois États. Cibler les campagnes sur ", liste(top.index[3:]),
                       ", qui pèsent déjà ", pct(part_suivants, 0), ".",
                       objectif=["porter ces trois États à ", pct(part_suivants + 3, 0), " du chiffre d'affaires."])
        return dec("Directeur commercial", "le chiffre d'affaires est bien réparti : les trois premiers États n'en font que ", pct(part3, 0),
                   ". Consolider les États moteurs (", liste(top.index[:3]), ") plutôt que d'ouvrir de nouvelles zones.")
    if indicateur == "delai":
        nat = c.delai.mean()
        lents = gros.delai.sort_values(ascending=False)
        au_dessus = lents[lents > 20]
        if len(au_dessus) == 0:
            return dec("Directeur logistique", "aucun État d'au moins 100 commandes ne dépasse 20 jours de délai moyen (le plus lent : ",
                       b(NOMS_ETATS.get(lents.index[0], lents.index[0])), ", ", b(f"{fr(lents.iloc[0], 1)} j"), "). Maintenir les contrats transporteurs actuels.")
        return dec("Directeur logistique", b(fr(len(au_dessus))), " États ont un délai moyen supérieur à 20 jours, dont ",
                   liste(au_dessus.index[:3]), ". Renégocier en priorité les transporteurs qui desservent ces États.",
                   objectif=["les ramener sous 20 jours (moyenne nationale : ", b(f"{fr(nat, 1)} j"), ")."])
    if indicateur == "retard":
        nat = 100 * c.en_retard.mean()
        pires = gros.retard.sort_values(ascending=False).iloc[:3]
        if pires.max() < 1.5 * nat:
            return dec("Directeur logistique", "les écarts entre États sont faibles (au pire ", pct(pires.max()), " de retards contre ", pct(nat),
                       " en moyenne) : le problème est national. Agir sur les transporteurs principaux plutôt qu'État par État.")
        return dec("Directeur logistique", liste(pires.index), " ont entre ", pct(pires.min(), 0), " et ", pct(pires.max(), 0),
                   " de colis en retard, contre ", pct(nat), " en moyenne. Auditer leurs transporteurs et revoir les dates promises.",
                   objectif=["revenir sous la moyenne nationale."])
    if indicateur == "note":
        bas = gros.note.sort_values().iloc[:3]
        if bas.min() >= 4:
            return dec("Responsable satisfaction", "toutes les zones d'au moins 100 commandes notent au-dessus de 4 (la plus basse : ",
                       b(NOMS_ETATS.get(bas.index[0], bas.index[0])), ", ", b(fr(bas.iloc[0], 2)), "). Maintenir le niveau de service actuel.")
        delai_bas, nat = gros.delai[bas.index].mean(), c.delai.mean()
        if delai_bas > nat + 3:
            cause = ["Leur délai moyen est de ", b(f"{fr(delai_bas, 0)} jours"), " contre ", b(f"{fr(nat, 0)}"), " au niveau national : la lenteur des livraisons est la première piste à traiter."]
        else:
            cause = ["Leur délai est proche de la moyenne nationale : la cause est plutôt du côté des produits ou des vendeurs."]
        return dec("Responsable satisfaction", liste(bas.index), " ont les notes les plus basses (", b(fr(bas.min(), 2)), " à ",
                   b(fr(bas.max(), 2)), "). ", *cause)
    haut = gros.panier.sort_values(ascending=False).iloc[:3]
    return dec("Directeur commercial", "le panier moyen dépasse ", b(f"{fr(haut.min(), 0)} R$"), " " + dans(haut.index),
               ", contre ", b(f"{fr(c.montant.mean(), 0)} R$"), " au niveau national. Y mettre en avant les produits chers et le paiement en plusieurs fois.")


def decision_classement(g, indicateur):
    gros = g[g.nb >= 300]
    if len(gros) == 0:
        return "élargir les filtres : aucun État n'a 300 commandes sur cette sélection."
    croissant = indicateur in ("ca", "note", "panier")
    pires = gros[indicateur].sort_values(ascending=croissant).iloc[:3]
    role = "Directeur logistique" if indicateur in ("delai", "retard") else "Directeur commercial"
    return dec(role, "à volume suffisant (300 commandes et plus), commencer par ", liste(pires.index),
               " : ce sont les États les moins bien placés sur cet indicateur parmi ceux où une action touchera le plus de clients.")


ACTIONS_PLAINTES = {
    "Colis non reçu": "renforcer le suivi de colis et relancer les transporteurs sur les envois non livrés",
    "Pas de réponse du vendeur": "imposer aux vendeurs une réponse aux clients sous 48 h",
    "Produit différent ou abîmé": "contrôler les fiches produit et l'emballage des vendeurs les plus cités",
    "Remboursement, annulation": "accélérer les remboursements et simplifier l'annulation",
    "Colis incomplet": "imposer un contrôle des envois de plusieurs articles avant expédition",
}


def decisions_livraison(c):
    r = c.dropna(subset=["retard"])
    if len(r) == 0:
        return ["élargir les filtres."] * 6
    taux0 = 100 * (r.retard > 0).mean()
    taux2 = 100 * (r.retard + 2 > 0).mean()
    marges = {}
    for e, x in r.groupby("etat"):
        if len(x) >= 300:
            k = max([j for j in range(0, 16) if 100 * (x.retard + j > 0).mean() <= 10] or [0])
            marges[e] = (k, len(x))
    meilleurs = [m for m in sorted(marges.items(), key=lambda kv: kv[1][0] * kv[1][1], reverse=True) if m[1][0] > 0][:2]
    if taux0 > 10:
        d_promesse = dec("Directeur commercial", "les retards touchent déjà ", pct(taux0), " des colis : ne surtout pas raccourcir la date promise. ",
                         "Revoir d'abord les délais annoncés dans les États les plus en retard.")
    elif len(meilleurs) == 0:
        d_promesse = dec("Directeur commercial", "la date promise est déjà au plus juste : aucun grand État ne peut l'avancer d'un jour sans dépasser 10 % de retards. La laisser telle quelle.")
    else:
        morceaux = ["raccourcir la date promise partout coûte vite : avec 2 jours de moins, les retards passent de ", pct(taux0), " à ", pct(taux2),
                    ". Mieux vaut l'ajuster par État : elle peut être avancée de ", b(jours(meilleurs[0][1][0])), " " + dans([meilleurs[0][0]])]
        if len(meilleurs) == 2:
            morceaux += [" et de ", b(jours(meilleurs[1][1][0])), " " + dans([meilleurs[1][0]])]
        morceaux.append(", en restant sous 10 % de retards.")
        d_promesse = dec("Directeur commercial", *morceaux, objectif=["une date promise calculée par État, avec au plus 10 % de retards partout."])

    m = r.groupby("mois").agg(taux=("en_retard", "mean"), nb=("order_id", "size"))
    m = m[m.nb >= 30]
    m["taux"] = 100 * (1 - m.taux)
    moyenne = 100 - taux0
    if len(m) < 2:
        d_heure = "élargir la période pour comparer les mois."
    elif m.taux.min() >= moyenne - 3:
        d_heure = dec("Directeur logistique", "la ponctualité est stable : le moins bon mois (", b(mois_texte(m.taux.idxmin())), ", ", pct(m.taux.min()),
                      ") reste proche de la moyenne. Pas d'action saisonnière nécessaire.")
    else:
        pires = m.taux.nsmallest(2)
        charge = m.nb[pires.index[0]] > 1.2 * m.nb.median()
        if charge:
            cause = ". Ce mois a aussi un volume de commandes élevé : prévoir de la capacité transporteur de réserve avant les mois de forte activité."
        else:
            cause = ". Le volume de ce mois était normal : la baisse vient plutôt d'un incident de transport, d'où l'intérêt d'avoir plusieurs transporteurs par zone."
        d_heure = dec("Directeur logistique", "la ponctualité est tombée à ", pct(pires.iloc[0]), " en ", b(mois_texte(pires.index[0])),
                      " et ", pct(pires.iloc[1]), " en ", b(mois_texte(pires.index[1])), cause,
                      objectif=["rester au-dessus de ", pct(moyenne), " chaque mois."])

    tard = r[r.retard > 3]
    part_tard = 100 * len(tard) / len(r)
    if len(tard) == 0:
        d_note = dec("Responsable service client", "aucune commande n'a eu 4 jours de retard ou plus sur cette sélection : rien à rattraper.")
    elif part_tard < 1:
        d_note = dec("Responsable service client", "seulement ", b(fr(len(tard))), " commandes (", pct(part_tard), ") ont eu au moins 4 jours de retard : les traiter au cas par cas, avec un geste commercial.")
    else:
        d_note = dec("Responsable service client", b(fr(len(tard))), " commandes ont eu au moins 4 jours de retard, notées ", b(fr(tard.note.mean(), 2)),
                     " en moyenne contre ", b(fr(r[r.retard <= 0].note.mean(), 2)), " à l'heure. Prévenir ces clients avant la livraison et leur proposer un geste commercial.",
                     objectif=["remonter leur note au-dessus de 3."])

    av = avis[avis.order_id.isin(r.order_id)]
    neg = av[av.note <= 2]
    if len(neg) >= 20:
        parts = (neg[list(THEMES)].mean() * 100).sort_values(ascending=False)
        premier, second = parts.index[0], parts.index[1]
        d_plaintes = dec("Responsable marketplace", "le premier motif de plainte est « ", premier.lower(), " » (", pct(parts.iloc[0], 0),
                         " des avis négatifs), devant « ", second.lower(), " » (", pct(parts.iloc[1], 0), "). Action prioritaire : ",
                         ACTIONS_PLAINTES[premier], ".",
                         objectif=["diviser par deux ce motif, qui touche ", b(fr(int(neg[premier].sum()))), " avis négatifs."])
    else:
        d_plaintes = "pas assez d'avis négatifs commentés (20 minimum) sur cette sélection."

    classes = pandas.cut(r.delai, [-numpy.inf, 8, 15.0000001, numpy.inf], right=False, labels=["rapide", "normale", "lente"])
    h = r.assign(classe=classes).groupby(["etat", "classe"], observed=False).agg(note=("note", "mean"), nb=("order_id", "size")).reset_index()
    pv = h.pivot(index="etat", columns="classe", values="note").where(h.pivot(index="etat", columns="classe", values="nb") >= 20)
    ecart = (pv["rapide"] - pv["lente"]).dropna().sort_values(ascending=False)
    if len(ecart) == 0:
        d_heatmap = "pas assez de commandes lentes et rapides par État sur cette sélection."
    elif ecart.iloc[0] < 0.3:
        d_heatmap = dec("Directeur logistique", "la durée de livraison pèse peu sur la note (au plus ", b(fr(ecart.iloc[0], 2)),
                        " point d'écart entre livraison rapide et lente) : chercher la cause des mauvaises notes du côté des produits ou des vendeurs.")
    else:
        e1 = ecart.index[0]
        autres = list(ecart.index[:2])
        if len(autres) == 2:
            debut = ["c'est ", dans(autres), " qu'une livraison lente coûte le plus de satisfaction : ", dans([e1]), ", la note passe de "]
        else:
            debut = [dans([e1]), ", une livraison lente fait passer la note de "]
        d_heatmap = dec("Directeur logistique", *debut, b(fr(pv.loc[e1, "rapide"], 2)), " en livraison rapide à ", b(fr(pv.loc[e1, "lente"], 2)),
                        " en livraison lente (plus de 15 jours). Y réduire en priorité les livraisons de plus de 15 jours : points relais, transporteur plus rapide ou vendeurs plus proches.")

    cc = r.dropna(subset=["note"])
    corr = cc.groupby("etat").apply(lambda x: x.retard.corr(x.note) if len(x) >= 30 else numpy.nan, include_groups=False).dropna().sort_values()
    if len(corr) < 3:
        d_corr = "pas assez d'États avec 30 commandes notées sur cette sélection."
    elif corr.iloc[0] > -0.2:
        d_corr = dec("Responsable satisfaction", "le lien entre retard et note est faible dans tous les États (corrélation au plus ", b(fr(corr.iloc[0], 2)),
                     ") : pas de priorité géographique, traiter les retards au fil de l'eau.")
    else:
        top = corr.index[:3]
        n_tard = int(r[r.etat.isin(top) & (r.retard > 0)].shape[0])
        d_corr = dec("Responsable satisfaction", dans(top), ", le lien entre retard et mauvaise note est le plus marqué (corrélation jusqu'à ",
                     b(fr(corr.iloc[0], 2)), ") : c'est là qu'un retard évité améliore le plus sûrement la satisfaction. Y suivre en priorité les colis en retard (",
                     b(fr(n_tard)), " sur la période).")
    return d_promesse, d_heure, d_note, d_plaintes, d_heatmap, d_corr


def decisions_ventes(c, a, ve):
    cat = a.groupby("categorie").ca.sum().sort_values(ascending=False)
    if len(cat) >= 3:
        top = cat.head(3)
        noms = f"{nom_categorie(top.index[0])}, {nom_categorie(top.index[1])} et {nom_categorie(top.index[2])}"
        part = 100 * top.sum() / cat.sum()
        if part >= 40:
            d_cat = dec("Directeur commercial", noms, " font ", pct(part, 0), " du chiffre d'affaires : forte dépendance à quelques catégories. ",
                        "Développer les catégories suivantes pour répartir le risque.")
        else:
            d_cat = dec("Directeur commercial", noms, " font ", pct(part, 0), " du chiffre d'affaires. Y recruter des vendeurs et y concentrer le budget d'acquisition.")
    else:
        d_cat = "sélection limitée à moins de trois catégories : élargir le filtre pour comparer."

    dernier = c.sort_values("achat").groupby("uid").agg(etat=("etat", "last"), nb=("order_id", "size"))
    taux = 100 * (dernier.nb >= 2).mean()
    r = dernier.groupby("etat").agg(clients=("nb", "size"), rec=("nb", lambda s: (s >= 2).mean() * 100))
    bas = r[r.clients >= 50].rec.nsmallest(3)
    if taux >= 5:
        d_rec = dec("Directeur marketing", pct(taux), " des clients repassent commande, un bon niveau pour la plateforme : lancer un programme de parrainage pour transformer ces clients fidèles en prescripteurs.")
    elif len(bas) == 3:
        d_rec = dec("Directeur marketing", "seuls ", pct(taux), " des clients repassent commande, et moins de ", pct(bas.max()), " " + dans(bas.index),
                    ". Y tester un bon de réduction sur la deuxième commande.",
                    objectif=["gagner un point de réachat, soit ", b(fr(len(dernier) / 100)), " clients fidèles de plus."])
    else:
        d_rec = dec("Directeur marketing", "seuls ", pct(taux), " des clients repassent commande. Tester un bon de réduction sur la deuxième commande.")

    q = a[a.prix > 0]
    cher = q[q.frais_port > q.prix]
    autres = q[q.frais_port <= q.prix]
    if len(cher) < 30:
        d_port = "trop peu d'articles dont le port dépasse le prix sur cette sélection pour conclure."
    elif autres.note.mean() - cher.note.mean() < 0.1:
        d_port = dec("Directeur commercial", "les articles dont le port dépasse le prix sont notés presque comme les autres (", b(fr(cher.note.mean(), 2)), " contre ",
                     b(fr(autres.note.mean(), 2)), ") : le port n'est pas un irritant ici, pas besoin de livraison offerte.")
    else:
        seuil = int(numpy.ceil(2 * cher.prix.mean() / 10) * 10)
        d_port = dec("Directeur commercial", b(fr(len(cher))), " articles ont des frais de port supérieurs à leur prix ; ils sont notés ", b(fr(cher.note.mean(), 2)),
                     " contre ", b(fr(autres.note.mean(), 2)), " pour les autres. Ils coûtent ", b(f"{fr(cher.prix.mean(), 0)} R$"),
                     " en moyenne : offrir le port dès ", b(f"{seuil} R$"), " de panier pour inciter à les grouper.")

    cl = c.groupby("etat").uid.nunique()
    ratio = (cl / ve).dropna()
    nat = cl.sum() / ve[ve.index.isin(cl.index)].sum()
    top3 = ratio.nlargest(3)
    sans = [e for e in cl[cl >= 30].index if e not in ve.index]
    if sans:
        d_ratio = dec("Responsable recrutement vendeurs", "aucun vendeur actif sur la période ", dans(sans), ", qui comptent pourtant ", b(fr(int(cl[sans].sum()))),
                      " clients : tous leurs colis viennent d'autres États. Y recruter des vendeurs locaux en priorité.")
    elif len(top3) == 0:
        d_ratio = "aucun vendeur installé dans les États sélectionnés."
    elif top3.max() < 2 * nat:
        d_ratio = dec("Responsable recrutement vendeurs", "la couverture est équilibrée : aucun État ne dépasse deux fois la moyenne de la sélection (",
                      b(fr(nat, 0)), " clients par vendeur). Pas de recrutement ciblé nécessaire.")
    else:
        a_recruter = int(sum(max(0, numpy.ceil(cl[e] / nat) - ve[e]) for e in top3.index))
        d_ratio = dec("Responsable recrutement vendeurs", dans(top3.index), ", on compte ", b(f"{fr(top3.min(), 0)} à {fr(top3.max(), 0)}"),
                      " clients pour un vendeur installé sur place, contre ", b(fr(nat, 0)), " en moyenne sur la sélection : leurs clients sont livrés depuis d'autres États, donc plus lentement. ",
                      "Il faudrait ", b(fr(a_recruter)), " vendeurs locaux de plus pour atteindre la densité moyenne.")

    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    grille = c.groupby([c.achat.dt.dayofweek, c.achat.dt.hour]).size()
    (j, hh), n = grille.idxmax(), grille.max()
    heures = c.groupby(c.achat.dt.hour).size()
    fortes = heures[heures >= 0.9 * heures.max()].index
    part_we = 100 * (c.achat.dt.dayofweek >= 5).mean()
    fin = (" Le week-end pèse ", pct(part_we, 0), " des commandes : y prévoir aussi des promotions.") if part_we >= 30 else \
          (" Le week-end ne pèse que ", pct(part_we, 0), " des commandes : concentrer l'effort en semaine.")
    d_heures = dec("Directeur marketing", "le créneau le plus actif est le ", b(f"{jours[j]} de {hh} h à {hh + 1} h"), " (", b(fr(n)),
                   " commandes), et l'activité reste forte de ", b(f"{fortes.min()} h à {fortes.max() + 1} h"),
                   ". Envoyer emails et promotions juste avant ces créneaux.", *fin)
    return d_cat, d_rec, d_port, d_ratio, d_heures


def decision_vendeurs(s, critere):
    mal = s[s.classe == "mal"].sort_values("ca", ascending=False)
    if len(mal) == 0:
        return dec("Responsable qualité vendeurs", "aucun vendeur en jaune avec ces réglages : maintenir le suivi trimestriel.")
    part = 100 * len(mal) / len(s)
    if part > 10:
        return dec("Responsable qualité vendeurs", pct(part, 0), " des vendeurs affichés sont en jaune : le problème est général, pas individuel. ",
                   "Revoir les critères d'admission et l'accompagnement des nouveaux vendeurs.")
    noms = [f"{r.ville} ({r.vetat})" for r in mal.head(3).itertuples()]
    seuil = "une note au-dessus de 3,5" if critere == "note" else "moins de 10 % de retards"
    return dec("Responsable qualité vendeurs", b(fr(len(mal))), " vendeurs sont en jaune, pour ", b(f"{compact(mal.ca.sum())} R$"),
               " de ventes. Commencer par les plus gros, à ", ", ".join(noms), ", sur la fiche produit, l'emballage et le délai d'expédition.",
               objectif=["les ramener à ", seuil, " d'ici un trimestre."])


def decisions_fiche(vc):
    d = vc.dropna(subset=["distance", "en_retard"])
    if len(d) < 10:
        return "pas assez de commandes géolocalisées pour conclure.", "pas assez de commandes pour tracer une tendance."
    med = d.distance.median()
    loin, pres = 100 * d[d.distance > med].en_retard.mean(), 100 * d[d.distance <= med].en_retard.mean()
    if loin + pres == 0:
        suite = "Aucun retard sur la période : rien à corriger."
    elif loin > 1.5 * pres and loin - pres >= 3:
        suite = "Ses retards sont nettement plus fréquents au loin : lui proposer un transporteur longue distance ou un stock régional."
    else:
        suite = f"La distance n'explique pas ses retards : regarder plutôt son délai d'expédition ({fr(vc.traitement.mean(), 1)} j)."
    d_zones = dec("Responsable vendeurs", "au-delà de ", b(f"{fr(med, 0)} km"), ", ", pct(loin, 0), " de ses colis arrivent en retard, contre ",
                  pct(pres, 0), " en deçà. ", suite)
    dd = vc.dropna(subset=["distance", "delai"])
    pente, origine = numpy.polyfit(dd.distance, dd.delai, 1)
    if pente * 100 < 0.3:
        d_distance = dec("Responsable vendeurs", "la distance allonge à peine le délai (", b(f"+{fr(pente * 100, 1)} jour"),
                         " tous les 100 km) : un délai promis unique suffit pour ce vendeur.")
    else:
        d_distance = dec("Responsable vendeurs", "ses colis mettent environ ", b(f"{fr(origine + 300 * pente, 0)} jours"), " à 300 km et ",
                         b(f"{fr(origine + 1500 * pente, 0)} jours"), " à 1 500 km. Adapter la date promise à la distance plutôt qu'afficher un délai unique.")
    return d_zones, d_distance


@app.callback(Output("d-g-ca", "children"), Output("d-g-delais", "children"), Output("d-g-paiement", "children"),
              Input("periode", "value"), Input("etats", "value"), Input("categories", "value"))
def maj_decisions_global(periode, etats, categories):
    c, a, p = filtrer(periode, etats, categories)
    if len(c) == 0:
        return ["élargir les filtres."] * 3
    return decisions_global(c, a, p)


@app.callback(Output("d-g-classement", "children"),
              Input("periode", "value"), Input("categories", "value"), Input("indicateur", "value"))
def maj_decision_classement(periode, categories, indicateur):
    c, a, p = filtrer(periode, None, categories)
    if len(c) == 0:
        return "élargir les filtres."
    g = c.groupby("etat").agg(delai=("delai", "mean"), retard=("en_retard", "mean"), note=("note", "mean"),
                              panier=("montant", "mean"), nb=("order_id", "size"))
    g["ca"] = a.groupby("etat").ca.sum()
    g["retard"] = 100 * g.retard
    return decision_classement(g, indicateur)


@app.callback(Output("d-g-promesse", "children"), Output("d-g-heure", "children"), Output("d-g-note-retard", "children"),
              Output("d-g-plaintes", "children"), Output("d-g-heatmap", "children"), Output("d-g-correlation", "children"),
              Input("periode", "value"), Input("etats", "value"), Input("categories", "value"))
def maj_decisions_livraison(periode, etats, categories):
    c, a, p = filtrer(periode, etats, categories)
    return decisions_livraison(c)


@app.callback(Output("d-g-categories", "children"), Output("d-g-recurrents", "children"), Output("d-g-port", "children"),
              Output("d-g-ratio", "children"), Output("d-g-heures", "children"),
              Input("periode", "value"), Input("etats", "value"), Input("categories", "value"))
def maj_decisions_ventes(periode, etats, categories):
    c, a, p = filtrer(periode, etats, categories)
    if len(c) == 0:
        return ["élargir les filtres."] * 5
    return decisions_ventes(c, a, vendeurs_actifs(periode, categories))


@app.callback(Output("d-g-vendeurs", "children"),
              Input("periode", "value"), Input("categories", "value"), Input("v-etats", "value"), Input("v-min", "value"), Input("v-couleur", "value"))
def maj_decision_vendeurs(periode, categories, v_etats, v_min, critere):
    c, a, p = filtrer(periode, None, categories)
    s = stats_vendeurs(a)
    s = s[s.nb_commandes >= v_min]
    if v_etats:
        s = s[s.vetat.isin(v_etats)]
    if len(s) == 0:
        return "baisser le nombre minimal de commandes pour afficher des vendeurs."
    s = s.assign(classe=classe_perf(s, critere), ville=s.vville.str.title())
    return decision_vendeurs(s, critere)


@app.callback(Output("d-g-zones", "children"), Output("d-g-distance", "children"),
              Input("vendeur", "value"), Input("periode", "value"), Input("categories", "value"))
def maj_decisions_fiche(vendeur, periode, categories):
    if not vendeur:
        return "", ""
    c, a, p = filtrer(periode, None, categories)
    a = a[a.vendeur_id == vendeur]
    if len(a) == 0:
        return "", ""
    vc = a.groupby("order_id").agg(distance=("distance", "first"), en_retard=("en_retard", "first"),
                                   delai=("delai", "first"), traitement=("traitement", "first"))
    return decisions_fiche(vc)

if __name__ == "__main__":
    app.run(debug=False, jupyter_mode="external")
