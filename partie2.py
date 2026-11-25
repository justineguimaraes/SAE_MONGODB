import sqlite3
import pandas
import pymongo
import unicodedata
from collections import defaultdict

conn = sqlite3.connect("olist.sqlite")

customers = pandas.read_sql_query("SELECT * FROM customers;", conn)
orders = pandas.read_sql_query("SELECT * FROM orders;", conn)
items = pandas.read_sql_query("""
SELECT oi.*, COALESCE(t.product_category_name_english, p.product_category_name, 'inconnue') AS categorie
FROM order_items oi
LEFT JOIN products p ON p.product_id = oi.product_id
LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name;
""", conn)
payments = pandas.read_sql_query("SELECT * FROM order_payments;", conn)
reviews = pandas.read_sql_query("SELECT * FROM order_reviews;", conn)
products = pandas.read_sql_query("""
SELECT p.*, t.product_category_name_english
FROM products p
LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name;
""", conn)
sellers = pandas.read_sql_query("SELECT * FROM sellers;", conn)
geo = pandas.read_sql_query("SELECT * FROM geolocation;", conn)
conn.close()


def nettoyer(d):
    return {k: v for k, v in d.items() if not pandas.isna(v)}


def normaliser(ville):
    ville = unicodedata.normalize("NFKD", str(ville))
    ville = "".join(c for c in ville if not unicodedata.combining(c))
    return ville.strip().lower()


def point(lat, lng):
    return {"type": "Point", "coordinates": [lng, lat]}


geo = geo[geo.geolocation_lat.between(-35, 6) & geo.geolocation_lng.between(-75, -34)].copy()
geo["ville_norm"] = geo.geolocation_city.map(normaliser)

geo_zip = geo.groupby("geolocation_zip_code_prefix").agg(
    lat=("geolocation_lat", "mean"),
    lng=("geolocation_lng", "mean"),
    nb_points=("geolocation_lat", "size"),
    ville=("ville_norm", lambda s: s.mode().iloc[0]),
    etat=("geolocation_state", lambda s: s.mode().iloc[0]),
).reset_index()

docs_geo = []
loc_zip = {}
for r in geo_zip.itertuples():
    loc = point(r.lat, r.lng)
    loc_zip[r.geolocation_zip_code_prefix] = loc
    docs_geo.append({"_id": int(r.geolocation_zip_code_prefix), "ville": r.ville, "etat": r.etat,
                     "nb_points": int(r.nb_points), "location": loc})

docs_vendeurs = []
for r in sellers.to_dict(orient="records"):
    d = {"_id": r["seller_id"], "zip": int(r["seller_zip_code_prefix"]),
         "ville": r["seller_city"], "etat": r["seller_state"]}
    if r["seller_zip_code_prefix"] in loc_zip:
        d["location"] = loc_zip[r["seller_zip_code_prefix"]]
    docs_vendeurs.append(d)

docs_produits = []
for r in products.to_dict(orient="records"):
    d = {"_id": r["product_id"],
         "categorie_pt": r["product_category_name"],
         "categorie_en": r["product_category_name_english"],
         "nom_longueur": r["product_name_lenght"],
         "description_longueur": r["product_description_lenght"],
         "nb_photos": r["product_photos_qty"],
         "poids_g": r["product_weight_g"],
         "dimensions_cm": nettoyer({"longueur": r["product_length_cm"],
                                    "hauteur": r["product_height_cm"],
                                    "largeur": r["product_width_cm"]})}
    d = nettoyer(d)
    for k in ["nom_longueur", "description_longueur", "nb_photos", "poids_g"]:
        if k in d:
            d[k] = int(d[k])
    if len(d["dimensions_cm"]) == 0:
        del d["dimensions_cm"]
    docs_produits.append(d)

for col in ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
            "order_delivered_customer_date", "order_estimated_delivery_date"]:
    orders[col] = pandas.to_datetime(orders[col])
items["shipping_limit_date"] = pandas.to_datetime(items["shipping_limit_date"])
reviews["review_creation_date"] = pandas.to_datetime(reviews["review_creation_date"])
reviews["review_answer_timestamp"] = pandas.to_datetime(reviews["review_answer_timestamp"])

articles = defaultdict(list)
for r in items.to_dict(orient="records"):
    articles[r["order_id"]].append(nettoyer({
        "numero": int(r["order_item_id"]),
        "produit_id": r["product_id"],
        "categorie": r["categorie"],
        "vendeur_id": r["seller_id"],
        "prix": r["price"],
        "frais_port": r["freight_value"],
        "date_limite_expedition": r["shipping_limit_date"].to_pydatetime(),
    }))

paiements = defaultdict(list)
for r in payments.to_dict(orient="records"):
    paiements[r["order_id"]].append({
        "sequence": int(r["payment_sequential"]),
        "moyen": r["payment_type"],
        "echeances": int(r["payment_installments"]),
        "montant": r["payment_value"],
    })

avis = defaultdict(list)
for r in reviews.to_dict(orient="records"):
    avis[r["order_id"]].append(nettoyer({
        "id": r["review_id"],
        "note": int(r["review_score"]),
        "titre": r["review_comment_title"],
        "commentaire": r["review_comment_message"],
        "date_creation": r["review_creation_date"].to_pydatetime(),
        "date_reponse": r["review_answer_timestamp"].to_pydatetime(),
    }))

clients = customers.set_index("customer_id").to_dict(orient="index")

cmd_clients = orders.merge(customers, on="customer_id")
docs_clients = []
for uid, g in cmd_clients.groupby("customer_unique_id"):
    valides = g[~g.order_status.isin(["canceled", "unavailable"])]
    docs_clients.append({"_id": uid,
                         "customer_ids": g.customer_id.tolist(),
                         "nb_commandes": len(g),
                         "nb_commandes_valides": len(valides),
                         "premiere_commande": g.order_purchase_timestamp.min().to_pydatetime(),
                         "derniere_commande": g.order_purchase_timestamp.max().to_pydatetime()})

docs_commandes = []
for r in orders.to_dict(orient="records"):
    c = clients[r["customer_id"]]
    client = {"customer_id": r["customer_id"], "unique_id": c["customer_unique_id"],
              "zip": int(c["customer_zip_code_prefix"]), "ville": c["customer_city"],
              "etat": c["customer_state"]}
    if c["customer_zip_code_prefix"] in loc_zip:
        client["location"] = loc_zip[c["customer_zip_code_prefix"]]
    dates = nettoyer({
        "achat": r["order_purchase_timestamp"],
        "approbation": r["order_approved_at"],
        "remise_transporteur": r["order_delivered_carrier_date"],
        "livraison_client": r["order_delivered_customer_date"],
        "estimee": r["order_estimated_delivery_date"],
    })
    dates = {k: v.to_pydatetime() for k, v in dates.items()}
    d = {"_id": r["order_id"], "statut": r["order_status"], "client": client, "dates": dates,
         "articles": articles.get(r["order_id"], []),
         "paiements": paiements.get(r["order_id"], []),
         "avis": avis.get(r["order_id"], [])}
    if "livraison_client" in dates:
        d["delai_livraison_jours"] = (dates["livraison_client"] - dates["achat"]).total_seconds() / 86400
        if "estimee" in dates:
            d["retard_jours"] = (dates["livraison_client"] - dates["estimee"]).total_seconds() / 86400
    docs_commandes.append(d)

connect = pymongo.MongoClient("mongodb://127.0.0.1:27017/")
db = connect.SAE

for nom in ["commandes", "clients", "vendeurs", "produits", "geolocalisation"]:
    db[nom].drop()

db.geolocalisation.insert_many(docs_geo)
db.clients.insert_many(docs_clients)
db.vendeurs.insert_many(docs_vendeurs)
db.produits.insert_many(docs_produits)
for i in range(0, len(docs_commandes), 10000):
    db.commandes.insert_many(docs_commandes[i:i + 10000])

db.commandes.create_index("statut")
db.commandes.create_index("dates.achat")
db.commandes.create_index("client.etat")
db.commandes.create_index("client.unique_id")
db.commandes.create_index("articles.vendeur_id")
db.commandes.create_index("articles.categorie")
db.geolocalisation.create_index([("location", pymongo.GEOSPHERE)])
db.vendeurs.create_index([("location", pymongo.GEOSPHERE)])
db.vendeurs.create_index("etat")
db.clients.create_index("nb_commandes")

for nom in ["commandes", "clients", "vendeurs", "produits", "geolocalisation"]:
    print(nom, db[nom].count_documents({}))
