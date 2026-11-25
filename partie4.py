import os
import json
import urllib.request
import numpy
import pandas
import pymongo
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State, dash_table, ctx, no_update
from dash.dash_table.Format import Format, Scheme
import dash_bootstrap_components as dbc

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
GRIS = "#A9B3CB"
BON = "#0ca30c"
MOYEN = "#fab219"
ORANGE_STATUT = "#ec835a"
MAUVAIS = "#d03b3b"
SEQ_BLEU = [[0, "#DCE6FC"], [0.3, "#93B2F5"], [0.6, "#3F75EC"], [0.8, "#0A4EE4"], [1, "#071A4F"]]
SEQ_CHAUD = [[0, "#FFF3CC"], [0.35, "#FFD45C"], [0.65, "#E09C00"], [1, "#8A4B00"]]
NOMS_PAIEMENT = {"credit_card": "Carte de crédit", "boleto": "Boleto", "voucher": "Bon d'achat", "debit_card": "Carte de débit", "not_defined": "Non défini"}
POLICE = "Instrument Sans, system-ui, sans-serif"
TITRE = "Bricolage Grotesque, Instrument Sans, system-ui, sans-serif"

db = pymongo.MongoClient("mongodb://127.0.0.1:27017/").SAE

lignes_cmd = []
lignes_art = []
lignes_pai = []
projection = {"client": 1, "dates": 1, "articles": 1, "paiements": 1, "avis.note": 1,
              "delai_livraison_jours": 1, "retard_jours": 1}
for c in db.commandes.find({"statut": "delivered"}, projection):
    d = c["dates"]
    loc = c["client"].get("location")
    notes = [a["note"] for a in c.get("avis", [])]
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


def fr(x, d=0):
    if pandas.isna(x):
        return "–"
    return f"{x:,.{d}f}".replace(",", "\u00a0").replace(".", ",")


def mois_texte(m):
    return f"{MOIS_FR[int(m[5:]) - 1]} {m[:4]}"


def nom_categorie(c):
    c = c.replace("_", " ")
    return c[:1].upper() + c[1:]


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
    fig.update_xaxes(gridcolor=grille, zeroline=False, linecolor=grille, title_font=dict(size=12.5))
    fig.update_yaxes(gridcolor=grille, zeroline=False, linecolor=grille, title_font=dict(size=12.5))
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


def decision(texte, sur_bleu=False):
    return html.P([html.Span("Décision", className="tag"), html.Span(texte)],
                  className="decision decision-bleu" if sur_bleu else "decision")


def panneau(titre, id_graph, texte_decision, hauteur=340, sous=None, controle=None):
    tete = [html.H3(titre)]
    if sous:
        tete.append(html.P(sous, className="sous"))
    corps = [html.Div(tete, className="tete")]
    if controle is not None:
        corps.append(controle)
    corps.append(dcc.Graph(id=id_graph, config={"displayModeBar": False}, style={"height": f"{hauteur}px"}))
    corps.append(decision(texte_decision) if isinstance(texte_decision, str) else html.P(
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


def stats_vendeurs(a):
    vc = a.drop_duplicates(["vendeur_id", "order_id"])
    s = vc.groupby("vendeur_id").agg(nb_commandes=("order_id", "size"), note=("note", "mean"),
                                     retard=("en_retard", "mean"), traitement=("traitement", "mean"),
                                     delai=("delai", "mean"), distance=("distance", "mean"))
    s["ca"] = a.groupby("vendeur_id").ca.sum()
    return s.reset_index().merge(vendeurs, on="vendeur_id")


app = Dash(__name__, assets_folder=ASSETS, external_stylesheets=[dbc.themes.BOOTSTRAP], title="olist | Pilotage")
app.index_string = """<!DOCTYPE html>
<html lang="fr"><head>{%metas%}<title>{%title%}</title>{%favicon%}{%css%}
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
.entete .dash-dropdown * { color: #fff; }
.filtre-periode .dash-slider-track { background: rgba(255,255,255,.3); }
.reinit { background: none; border: none; color: #fff; font-size: 13.5px; text-decoration: underline; text-underline-offset: 3px; padding: 0 0 10px; }
.reinit:hover { color: var(--jaune); }
.reinit:focus-visible, .nav-link:focus-visible { outline: 2px solid var(--jaune); outline-offset: 3px; }
.nav-tabs { background: var(--bleu); border: none; padding: 0 40px; }
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
.choix label { font-size: 13.5px; color: var(--encre); }
.choix .form-check-input:checked { background-color: var(--bleu); border-color: var(--bleu); }
.reglages { display: flex; flex-wrap: wrap; gap: 18px 36px; align-items: flex-end; margin: 4px 0 14px; }
.reglages label.titre-reglage { display: block; font-size: 13px; color: var(--encre2); margin-bottom: 6px; }
.fiche { display: flex; flex-wrap: wrap; gap: 14px 48px; margin: 0 0 28px; }
.fiche dt { font-size: 13.5px; color: var(--encre2); font-weight: 400; }
.fiche dd { font-family: var(--titre); font-size: 32px; font-weight: 600; letter-spacing: -.025em; margin: 0; line-height: 1.1; }
.fiche dd small { font-family: var(--texte); font-size: 13px; font-weight: 400; color: var(--encre2); letter-spacing: 0; }
.choix-vendeur { max-width: 640px; margin-bottom: 18px; }
@media (max-width: 900px) {
  .entete, .hero, .contenu { padding-left: 20px; padding-right: 20px; }
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
                  dcc.Dropdown(id="etats", options=[{"label": f"{e} – {NOMS_ETATS.get(e, e)}", "value": e} for e in ETATS],
                               multi=True, placeholder="Tout le Brésil")], className="filtre filtre-liste"),
        html.Div([html.Label("Catégories", htmlFor="categories"),
                  dcc.Dropdown(id="categories", options=[{"label": nom_categorie(c), "value": c} for c in CATEGORIES],
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
        decision("préparer les pics de fin d'année (Black Friday) : stocks des vendeurs, capacité transporteurs et budget marketing.", True),
    ], className="hero"),
    html.Div([
        dbc.Row([
            dbc.Col(panneau("Combien de jours pour être livré ?", "g-delais",
                            "afficher une promesse de délai tenable et traiter en priorité la traîne des commandes à plus de 30 jours.",
                            sous="De l'achat à la réception par le client. Les commandes de plus de 60 jours sont masquées."), lg=7),
            dbc.Col(panneau("Comment les clients paient-ils ?", "g-paiement",
                            "négocier d'abord les commissions carte bancaire, qui portent l'essentiel des montants, et garder le boleto pour les clients sans carte.",
                            sous="Part de la valeur totale payée par moyen de paiement."), lg=5),
        ]),
    ], className="contenu"),
])

onglet_carte = html.Div([
    html.H2(id="constat-carte", className="constat"),
    dbc.Row([
        dbc.Col(panneau("Le Brésil, État par État", "g-choro", html.Span(id="decision-choro"), hauteur=560,
                        sous="Cliquez un État pour l'ajouter au filtre de tout le tableau de bord ; recliquez pour le retirer.",
                        controle=dbc.RadioItems(id="indicateur", inline=True, value="ca", className="choix",
                                                options=[{"label": "Chiffre d'affaires", "value": "ca"},
                                                         {"label": "Délai moyen", "value": "delai"},
                                                         {"label": "Taux de retard", "value": "retard"},
                                                         {"label": "Note moyenne", "value": "note"},
                                                         {"label": "Panier moyen", "value": "panier"}])), lg=8),
        dbc.Col(panneau("Classement des États", "g-classement",
                        "repérer d'un coup d'œil les États en tête et en queue avant d'ouvrir le détail.", hauteur=596,
                        sous="Les États sélectionnés sont en jaune."), lg=4),
    ]),
], className="contenu")

onglet_satisfaction = html.Div([
    html.H2(id="constat-satisfaction", className="constat"),
    dbc.Row([
        dbc.Col(panneau("Combien coûte un retard en satisfaction ?", "g-note-retard",
                        "relancer et dédommager les clients dès 4 jours de retard, seuil où la note s'effondre.",
                        sous="Note moyenne selon l'écart entre la livraison réelle et la date promise."), lg=6),
        dbc.Col(panneau("Mois après mois, les colis arrivent-ils à l'heure ?", "g-heure",
                        "réserver de la capacité transporteur avant les mois où le taux décroche, comme fin 2017 et début 2018.",
                        sous="Part des commandes livrées avant la date estimée, pour les mois d'au moins 30 commandes."), lg=6),
    ]),
    dbc.Row([
        dbc.Col(panneau("Où la lenteur pèse-t-elle le plus ?", "g-heatmap",
                        "changer de transporteur ou ouvrir des points relais dans les États où les livraisons lentes sont les plus mal notées.",
                        hauteur=400, sous="Note moyenne par État et par durée de livraison. Une case vide compte moins de 20 commandes."), lg=7),
        dbc.Col(panneau("Où la ponctualité compte-t-elle le plus ?", "g-correlation",
                        "dans les États en jaune, chaque jour de retard gagné rapporte le plus de satisfaction : à traiter en premier.",
                        hauteur=400, sous="Corrélation entre jours de retard et note, États d'au moins 30 commandes. Les 3 plus fortes sont en jaune."), lg=5),
    ]),
], className="contenu")

onglet_commercial = html.Div([
    html.H2(id="constat-commercial", className="constat"),
    dbc.Row([
        dbc.Col(panneau("Quelles catégories font le chiffre ?", "g-categories",
                        "concentrer le recrutement de vendeurs et le budget d'acquisition sur ces dix catégories.",
                        hauteur=380, sous="Les 10 premières catégories, avec leur part du chiffre d'affaires."), lg=6),
        dbc.Col(panneau("Qui revient commander ?", "g-recurrents",
                        "lancer une offre de deuxième commande dans les États en jaune, où les clients reviennent le moins.",
                        hauteur=380, sous="Part des clients ayant passé au moins 2 commandes, États d'au moins 50 clients. Les 3 plus faibles sont en jaune."), lg=6),
    ]),
    dbc.Row([
        dbc.Col(panneau("Les frais de port font-ils baisser la note ?", "g-port",
                        "proposer la livraison offerte au-dessus d'un seuil de panier, pour les petits articles dont le port dépasse le prix.",
                        sous="Note moyenne selon le poids des frais de port dans le prix de l'article."), lg=6),
        dbc.Col(panneau("Où manque-t-il des vendeurs ?", "g-ratio",
                        "recruter des vendeurs locaux en priorité dans les États en jaune, où chaque vendeur sert le plus de clients.",
                        sous="Clients par vendeur installé dans l'État, 15 premiers. Les 3 plus tendus sont en jaune."), lg=6),
    ]),
], className="contenu")

reglages_vendeurs = html.Div([
    html.Div([html.Label("État du vendeur", className="titre-reglage", htmlFor="v-etats"),
              dcc.Dropdown(id="v-etats", options=sorted(vendeurs.vetat.unique()), multi=True, placeholder="Tous les États",
                           style={"width": "240px"})]),
    html.Div([html.Label("Nombre minimal de commandes", className="titre-reglage", htmlFor="v-min"),
              html.Div(dcc.Slider(id="v-min", min=1, max=200, step=1, value=20,
                                  marks={1: "1", 50: "50", 100: "100", 150: "150", 200: "200"}), style={"width": "340px"})]),
    html.Div([html.Label("Couleur des points", className="titre-reglage"),
              dbc.RadioItems(id="v-couleur", value="note", inline=True, className="choix",
                             options=[{"label": "Note moyenne", "value": "note"}, {"label": "Taux de retard", "value": "retard"}])]),
], className="reglages")

onglet_vendeurs = html.Div([
    html.H2(id="constat-vendeurs", className="constat"),
    panneau("Où sont les vendeurs, et lesquels décrochent ?", "g-vendeurs",
            "accompagner les vendeurs en rouge (fiche produit, emballage, délai d'expédition) avant qu'ils ne dégradent la note de la plateforme.",
            hauteur=540, sous="Un point par vendeur, de taille proportionnelle à son chiffre d'affaires. Cliquez un point pour ouvrir sa fiche.",
            controle=reglages_vendeurs),
    html.Div([
        html.Label("Vendeur affiché", className="titre-reglage sous mb-1", htmlFor="vendeur"),
        dcc.Dropdown(id="vendeur", clearable=False, placeholder="Choisir un vendeur", className="choix-vendeur"),
    ], className="mt-2"),
    html.H2(id="v-titre", className="constat mt-3 mb-3"),
    html.Dl(id="v-fiche", className="fiche"),
    dbc.Row([
        dbc.Col(panneau("Où livre ce vendeur ?", "g-zones",
                        "si les retards (en rouge) se concentrent loin de sa base, lui proposer un transporteur longue distance ou un stock régional.",
                        hauteur=460, sous="Chaque trait relie le vendeur à un client livré sur la période."), lg=7),
        dbc.Col(panneau("Plus c'est loin, plus c'est long ?", "g-distance",
                        "si le délai grimpe vite avec la distance, limiter la zone de livraison promise ou ajuster les dates estimées.",
                        hauteur=460, sous="Délai de livraison de chaque commande selon la distance au client, avec la tendance."), lg=5),
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
                                     "color": MAUVAIS, "fontWeight": "600"}],
        ),
    ], className="panneau"),
], className="contenu")

app.layout = html.Div([
    entete,
    dbc.Tabs([
        dbc.Tab(onglet_global, label="Vue d'ensemble"),
        dbc.Tab(onglet_carte, label="Carte du Brésil"),
        dbc.Tab(onglet_satisfaction, label="Livraison et satisfaction"),
        dbc.Tab(onglet_commercial, label="Ventes"),
        dbc.Tab(onglet_vendeurs, label="Vendeurs"),
    ]),
])


@app.callback(Output("etats", "value"), Output("periode", "value"), Output("categories", "value"),
              Input("g-choro", "clickData"), Input("reset", "n_clicks"), State("etats", "value"),
              prevent_initial_call=True)
def maj_filtres(clic, reset, etats):
    if ctx.triggered_id == "reset":
        return [], [0, len(MOIS) - 1], []
    etat = clic["points"][0]["location"]
    etats = list(etats or [])
    if etat in etats:
        etats.remove(etat)
    else:
        etats.append(etat)
    return etats, no_update, no_update


@app.callback(Output("phrase", "children"), Output("g-ca", "figure"), Output("g-delais", "figure"), Output("g-paiement", "figure"),
              Input("periode", "value"), Input("etats", "value"), Input("categories", "value"), Input("mesure-ca", "value"))
def maj_global(periode, etats, categories, mesure):
    c, a, p = filtrer(periode, etats, categories)
    if len(c) == 0:
        return "Aucune commande livrée ne correspond à ces filtres.", vide(290), vide(), vide()
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
                                        marker_line=dict(color="white", width=2),
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
    return phrase, fig_ca, fig_delais, fig_pai


INDICATEURS = {
    "ca": ("Chiffre d'affaires (R$)", SEQ_BLEU, ",.0f", "consolider la position dans les États les plus foncés et tester des campagnes dans les États clairs à fort potentiel de population."),
    "delai": ("Délai moyen (jours)", SEQ_CHAUD, ".1f", "renégocier les contrats transporteurs dans les États les plus foncés, surtout au Nord et au Nordeste."),
    "retard": ("Taux de retard (%)", SEQ_CHAUD, ".1f", "auditer les transporteurs des États les plus foncés, où la date promise est le moins souvent tenue."),
    "note": ("Note moyenne (sur 5)", SEQ_BLEU, ".2f", "croiser avec le délai : une note faible là où les livraisons sont lentes désigne la logistique, pas les produits."),
    "panier": ("Panier moyen (R$)", SEQ_BLEU, ".0f", "réserver les mises en avant de produits chers aux États où le panier est le plus élevé."),
}


@app.callback(Output("g-choro", "figure"), Output("g-classement", "figure"), Output("decision-choro", "children"),
              Output("constat-carte", "children"),
              Input("periode", "value"), Input("categories", "value"), Input("etats", "value"), Input("indicateur", "value"))
def maj_carte(periode, categories, etats, indicateur):
    c, a, p = filtrer(periode, None, categories)
    if len(c) == 0:
        return vide(560), vide(596), "", "Aucune commande livrée ne correspond à ces filtres."
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

    noms = [NOMS_ETATS.get(e, e) for e in g.index]
    fig = go.Figure(go.Choroplethmap(
        geojson=CARTE_ETATS, featureidkey="properties.sigla", locations=g.index, z=val, colorscale=echelle,
        marker=dict(line=dict(color="white", width=1.2), opacity=0.95),
        colorbar=dict(title=dict(text=titre, side="right"), thickness=10, outlinewidth=0, tickformat=fmt, len=0.8),
        customdata=numpy.stack([noms, g.nb], axis=-1),
        hovertemplate="<b>%{customdata[0]}</b><br>" + titre + " : %{z:" + fmt + "}<br>%{customdata[1]:,} commandes<extra></extra>"))
    if etats:
        fig.add_trace(go.Choroplethmap(geojson=CARTE_ETATS, featureidkey="properties.sigla", locations=etats, z=[0] * len(etats),
                                       colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]], showscale=False,
                                       marker=dict(line=dict(color=JAUNE, width=4)), hoverinfo="skip"))
    fond_bresil(fig, -14.8, -53, 3.35)
    style(fig, 560)

    t = val.sort_values()
    couleurs = [JAUNE_FONCE if e in (etats or []) else BLEU for e in t.index]
    fig_c = go.Figure(go.Bar(x=t.values, y=t.index, orientation="h", marker=dict(color=couleurs, cornerradius=4),
                             customdata=[NOMS_ETATS.get(e, e) for e in t.index],
                             hovertemplate="<b>%{customdata}</b> : %{x:" + fmt + "}<extra></extra>"))
    style(fig_c, 596).update_layout(bargap=0.3)
    fig_c.update_xaxes(title=titre, tickformat=fmt)
    fig_c.update_yaxes(dtick=1, tickfont=dict(size=11.5))
    return fig, fig_c, texte, constat


@app.callback(Output("g-note-retard", "figure"), Output("g-heure", "figure"), Output("g-heatmap", "figure"), Output("g-correlation", "figure"),
              Output("constat-satisfaction", "children"),
              Input("periode", "value"), Input("etats", "value"), Input("categories", "value"))
def maj_satisfaction(periode, etats, categories):
    c, a, p = filtrer(periode, etats, categories)
    c = c.dropna(subset=["retard"])
    if len(c) == 0:
        return vide(), vide(), vide(400), vide(400), "Aucune commande livrée ne correspond à ces filtres."

    tranches = pandas.cut(c.retard, [-numpy.inf, 0, 3, 7, numpy.inf], labels=["À l'heure", "1 à 3 jours", "4 à 7 jours", "Plus de 7 jours"])
    t = c.groupby(tranches, observed=False).agg(note=("note", "mean"), nb=("order_id", "size"))
    part = 100 * t.nb / t.nb.sum()
    fig1 = go.Figure(go.Bar(x=t.index.astype(str), y=t.note, marker=dict(color=[BON, MOYEN, ORANGE_STATUT, MAUVAIS], cornerradius=6),
                            text=[f"<b>{fr(n, 2)}</b>" for n in t.note], textposition="outside", textfont=dict(color=ENCRE, size=14),
                            customdata=numpy.stack([t.nb, part], axis=-1),
                            hovertemplate="%{x}<br><b>note %{y:.2f}</b><br>%{customdata[0]:,} commandes (%{customdata[1]:.1f} %)<extra></extra>"))
    style(fig1)
    fig1.update_yaxes(range=[0, 5.4], title="note moyenne sur 5")
    fig1.update_xaxes(ticktext=[f"{k}<br><span style='font-size:11px'>{fr(v, 1)} % des colis</span>" for k, v in zip(t.index.astype(str), part)],
                      tickvals=t.index.astype(str))

    m = c.groupby("mois").agg(taux=("en_retard", "mean"), nb=("order_id", "size"))
    m = m[m.nb >= 30]
    m["taux"] = 100 * (1 - m.taux)
    moyenne = 100 * (1 - c.en_retard.mean())
    xm = [mois_texte(k) for k in m.index]
    sous_moyenne = m.taux < moyenne - 5
    fig2 = go.Figure(go.Scatter(x=xm, y=m.taux, mode="lines+markers", line=dict(color=BLEU, width=2.5),
                                marker=dict(size=9, color=[JAUNE_FONCE if s else BLEU for s in sous_moyenne], line=dict(color="white", width=2)),
                                customdata=m.nb, hovertemplate="%{x}<br><b>%{y:.1f} % à l'heure</b><br>%{customdata:,} commandes<extra></extra>"))
    fig2.add_hline(y=moyenne, line=dict(color=ENCRE2, width=1, dash="dot"),
                   annotation_text=f"moyenne {fr(moyenne, 1)} %", annotation_position="bottom left", annotation_font_color=ENCRE2)
    style(fig2)
    fig2.update_yaxes(title="livrées à l'heure", ticksuffix=" %")
    fig2.update_xaxes(showgrid=False, tickvals=xm[::3])

    classes = pandas.cut(c.delai, [-numpy.inf, 8, 15.0000001, numpy.inf], right=False, labels=["Rapide, moins de 8 j", "Normale, 8 à 15 j", "Lente, plus de 15 j"])
    h = c.assign(classe=classes).groupby(["etat", "classe"], observed=False).agg(note=("note", "mean"), nb=("order_id", "size")).reset_index()
    pivot = h.pivot(index="classe", columns="etat", values="note")
    nb = h.pivot(index="classe", columns="etat", values="nb")
    ordre = c.groupby("etat").size().sort_values(ascending=False).index
    pivot, nb = pivot[ordre], nb[ordre]
    pivot = pivot.where(nb >= 20)
    fig3 = go.Figure(go.Heatmap(z=pivot.values, x=pivot.columns, y=pivot.index.astype(str), colorscale=SEQ_BLEU, zmin=3, zmax=5,
                                xgap=3, ygap=3, customdata=nb.values,
                                colorbar=dict(title=dict(text="note", side="right"), thickness=10, outlinewidth=0),
                                hovertemplate="<b>%{x}</b>, livraison %{y}<br>note %{z:.2f}<br>%{customdata:,} commandes<extra></extra>"))
    style(fig3, 400)
    fig3.update_xaxes(title="États, du plus au moins de commandes", showgrid=False, tickfont=dict(size=11))
    fig3.update_yaxes(showgrid=False)

    cc = c.dropna(subset=["note"])
    corr = cc.groupby("etat").apply(lambda x: x.retard.corr(x.note) if len(x) >= 30 else numpy.nan, include_groups=False).dropna().sort_values(ascending=False)
    fig4 = go.Figure(go.Bar(x=corr.values, y=corr.index, orientation="h",
                            marker=dict(color=couleurs_alerte(-corr, 3), cornerradius=4),
                            customdata=[NOMS_ETATS.get(e, e) for e in corr.index],
                            hovertemplate="<b>%{customdata}</b><br>corrélation %{x:.2f}<extra></extra>"))
    style(fig4, 400).update_layout(bargap=0.3)
    fig4.update_xaxes(title="corrélation retard / note (plus c'est négatif, plus le retard pèse)", range=[min(-0.6, corr.min() - 0.05), 0])
    fig4.update_yaxes(dtick=1, tickfont=dict(size=11))

    constat = ["Au-delà de 7 jours de retard, la note moyenne tombe de ", b(fr(t.note.iloc[0], 2)), " à ", b(fr(t.note.iloc[-1], 2)),
               ". Cela concerne ", b(f"{fr(part.iloc[-1], 1)} %"), " des colis."]
    return fig1, fig2, fig3, fig4, constat


@app.callback(Output("g-categories", "figure"), Output("g-recurrents", "figure"), Output("g-port", "figure"), Output("g-ratio", "figure"),
              Output("constat-commercial", "children"),
              Input("periode", "value"), Input("etats", "value"), Input("categories", "value"))
def maj_commercial(periode, etats, categories):
    c, a, p = filtrer(periode, etats, categories)
    if len(c) == 0:
        return vide(380), vide(380), vide(), vide(), "Aucune commande livrée ne correspond à ces filtres."

    cat = a.groupby("categorie").ca.sum().sort_values(ascending=False)
    part = 100 * cat / cat.sum()
    top = cat.head(10)[::-1]
    fig1 = go.Figure(go.Bar(x=top.values, y=[nom_categorie(x) for x in top.index], orientation="h",
                            marker=dict(color=BLEU, cornerradius=4), cliponaxis=False,
                            text=[f"{fr(v, 1)} %" for v in part[top.index]], textposition="outside", textfont=dict(color=ENCRE),
                            hovertemplate="<b>%{y}</b><br>%{x:,.0f} R$<extra></extra>"))
    style(fig1, 380).update_layout(bargap=0.3)
    fig1.update_xaxes(title="chiffre d'affaires (R$)", range=[0, top.max() * 1.16])

    dernier = c.sort_values("achat").groupby("uid").agg(etat=("etat", "last"), nb=("order_id", "size"))
    r = dernier.groupby("etat").agg(clients=("nb", "size"), recurrents=("nb", lambda s: (s >= 2).sum()))
    r = r[r.clients >= 50]
    r["taux"] = 100 * r.recurrents / r.clients
    r = r.sort_values("taux", ascending=False)
    if len(r) > 0:
        fig2 = go.Figure(go.Bar(x=r.taux, y=r.index, orientation="h",
                                marker=dict(color=couleurs_alerte(r.taux, 3, plus_grands=False), cornerradius=4),
                                customdata=numpy.stack([r.recurrents, r.clients, [NOMS_ETATS.get(e, e) for e in r.index]], axis=-1),
                                hovertemplate="<b>%{customdata[2]}</b><br>%{x:.2f} % de clients récurrents<br>%{customdata[0]} sur %{customdata[1]} clients<extra></extra>"))
        style(fig2, 380).update_layout(bargap=0.3)
        fig2.update_xaxes(title="clients ayant commandé au moins 2 fois", ticksuffix=" %")
        fig2.update_yaxes(dtick=1, tickfont=dict(size=11))
    else:
        fig2 = vide(380, "Pas assez de clients (50 minimum par État) pour ce filtre.")

    q = a[a.prix > 0]
    tranche = pandas.cut(q.frais_port / q.prix, [-numpy.inf, 0.15, 0.40, 1, numpy.inf], right=False,
                         labels=["moins de 15 %", "15 à 40 %", "40 à 100 %", "plus cher que l'article"])
    t = q.groupby(tranche, observed=False).agg(note=("note", "mean"), nb=("order_id", "size"), prix=("prix", "mean"))
    fig3 = go.Figure(go.Bar(x=t.index.astype(str), y=t.note, marker=dict(color=[BLEU, BLEU, BLEU, JAUNE_FONCE], cornerradius=6),
                            text=[f"<b>{fr(n, 2)}</b>" for n in t.note], textposition="outside", textfont=dict(color=ENCRE, size=14),
                            customdata=numpy.stack([t.nb, t.prix], axis=-1),
                            hovertemplate="port %{x} du prix<br><b>note %{y:.2f}</b><br>%{customdata[0]:,} articles, prix moyen %{customdata[1]:.0f} R$<extra></extra>"))
    style(fig3)
    bas = numpy.nanmin(t.note.values) if t.note.notna().any() else 3.5
    fig3.update_yaxes(range=[max(0, bas - 0.4), 4.4], title="note moyenne sur 5")
    fig3.update_xaxes(title="frais de port rapportés au prix de l'article")

    cl = c.groupby("etat").uid.nunique()
    ve = vendeurs.groupby("vetat").size()
    ratio = (cl / ve).dropna()
    if etats:
        ratio = ratio[ratio.index.isin(etats)]
    ratio = ratio.sort_values(ascending=False).head(15)
    fig4 = go.Figure(go.Bar(x=ratio.values, y=ratio.index, orientation="h",
                            marker=dict(color=couleurs_alerte(ratio, 3), cornerradius=4),
                            customdata=numpy.stack([cl[ratio.index], ve[ratio.index], [NOMS_ETATS.get(e, e) for e in ratio.index]], axis=-1),
                            hovertemplate="<b>%{customdata[2]}</b><br>%{x:,.0f} clients par vendeur<br>%{customdata[0]} clients, %{customdata[1]} vendeurs<extra></extra>"))
    style(fig4).update_layout(bargap=0.3)
    fig4.update_xaxes(title="clients par vendeur installé dans l'État")
    fig4.update_yaxes(dtick=1, autorange="reversed", tickfont=dict(size=11))

    total = len(dernier)
    taux = 100 * (dernier.nb >= 2).mean()
    constat = ["Les dix premières catégories font ", b(f"{fr(part.head(10).sum(), 0)} %"), " des ventes, mais seuls ",
               b(f"{fr(taux, 1)} %"), " des ", b(fr(total)), " clients ont commandé une deuxième fois."]
    return fig1, fig2, fig3, fig4, constat


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
        return vide(540, "Aucun vendeur ne passe ce seuil. Baissez le nombre minimal de commandes."), [], None, "Aucun vendeur ne correspond à ces réglages."
    s = s.assign(classe=classe_perf(s, critere), ville=s.vville.str.title()).sort_values("ca", ascending=False)

    fig = go.Figure()
    for classe, couleur in [("bien", BON), ("moyen", MOYEN), ("mal", MAUVAIS)]:
        g = s[s.classe == classe]
        fig.add_trace(go.Scattermap(
            lat=g.vlat, lon=g.vlng, mode="markers", name=f"{LEGENDES[critere][classe]} ({len(g)})",
            marker=dict(size=numpy.clip(numpy.sqrt(g.ca) / 11, 9, 36), color=couleur, opacity=0.82),
            customdata=numpy.stack([g.vendeur_id, g.ville, g.vetat, g.nb_commandes, g.ca, g.note, g.traitement, g.retard * 100], axis=-1),
            hovertemplate="<b>%{customdata[1]} (%{customdata[2]})</b><br>%{customdata[3]:,} commandes<br>%{customdata[4]:,.0f} R$ de chiffre d'affaires<br>"
                          "note %{customdata[5]:.2f}, %{customdata[7]:.1f} % de retards<br>expédie en %{customdata[6]:.1f} jours en moyenne<extra></extra>"))
    fond_bresil(fig, -15.5, -53, 3.12)
    fig.update_layout(clickmode="event")
    style(fig, 540, legende=True).update_layout(legend=dict(bgcolor="rgba(255,255,255,0.9)", y=0.97, x=0.01, orientation="v"))

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
        for nom, masque, couleur in [("Livrés à l'heure", geo.en_retard == 0, BON), ("Livrés en retard", geo.en_retard == 1, MAUVAIS)]:
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


if __name__ == "__main__":
    app.run(debug=False)
