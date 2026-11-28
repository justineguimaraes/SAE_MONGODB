import os
import numpy
import pandas
import pymongo

connect = pymongo.MongoClient("mongodb://127.0.0.1:27017/")
db = connect.SAE
os.makedirs("resultats_mongo", exist_ok=True)

CA_ARTICLES = {"$add": [{"$sum": "$articles.prix"}, {"$sum": "$articles.frais_port"}]}
NOTE = {"$avg": "$avis.note"}
MOIS = {"$dateToString": {"format": "%Y-%m", "date": "$dates.achat"}}


def executer(collection, pipeline):
    return pandas.DataFrame(list(db[collection].aggregate(pipeline, allowDiskUse=True)))


def compter(collection, pipeline):
    res = list(db[collection].aggregate(pipeline, allowDiskUse=True))
    if len(res) == 0:
        return 0
    return res[0]["n"]


def comparer(nom, df, cle=None, tol=0.011):
    df.to_csv(f"resultats_mongo/{nom}.csv", index=False)
    ref = pandas.read_csv(f"resultats_sqlite/{nom}.csv")
    if len(ref) != len(df):
        print(nom, "KO nombre de lignes :", len(ref), "contre", len(df))
        return
    if cle is not None:
        ref = ref.sort_values(cle).reset_index(drop=True)
        df = df.sort_values(cle).reset_index(drop=True)
    ok = True
    for col in ref.columns:
        if col not in df.columns:
            print(nom, "colonne manquante", col)
            ok = False
        elif ref[col].dtype.kind in "fi":
            if not numpy.allclose(ref[col].astype(float), df[col].astype(float), atol=tol, equal_nan=True):
                print(nom, "difference dans", col)
                ok = False
        elif not (ref[col].astype(str) == df[col].astype(str)).all():
            print(nom, "difference dans", col)
            ok = False
    print(nom, "OK" if ok else "KO")


q0 = pandas.DataFrame([{
    "nb_customer_id": compter("clients", [{"$group": {"_id": None, "n": {"$sum": {"$size": "$customer_ids"}}}}]),
    "nb_personnes_reelles": db.clients.count_documents({}),
    "nb_commandes": db.commandes.count_documents({}),
    "nb_commandes_livrees": db.commandes.count_documents({"statut": "delivered"}),
    "nb_avis": compter("commandes", [{"$group": {"_id": None, "n": {"$sum": {"$size": "$avis"}}}}]),
    "nb_review_id_distincts": compter("commandes", [{"$unwind": "$avis"}, {"$group": {"_id": "$avis.id"}}, {"$count": "n"}]),
    "nb_avis_sans_commentaire": compter("commandes", [{"$unwind": "$avis"}, {"$match": {"avis.commentaire": {"$exists": False}}}, {"$count": "n"}]),
    "nb_produits_sans_categorie": db.produits.count_documents({"categorie_pt": {"$exists": False}}),
    "nb_produits_categorie_sans_traduction": db.produits.count_documents({"categorie_pt": {"$exists": True}, "categorie_en": {"$exists": False}}),
    "nb_commandes_sans_avis": db.commandes.count_documents({"avis": {"$size": 0}}),
    "nb_commandes_plusieurs_avis": db.commandes.count_documents({"avis.1": {"$exists": True}}),
    "nb_commandes_plusieurs_articles": db.commandes.count_documents({"articles.1": {"$exists": True}}),
    "nb_commandes_plusieurs_paiements": db.commandes.count_documents({"paiements.1": {"$exists": True}}),
    "nb_commandes_sans_article": db.commandes.count_documents({"articles": {"$size": 0}}),
}])
comparer("q0_exploration", q0)

df = executer("commandes", [
    {"$group": {"_id": "$statut", "nb_commandes": {"$sum": 1},
                "sans_date_approbation": {"$sum": {"$cond": [{"$ifNull": ["$dates.approbation", False]}, 0, 1]}},
                "sans_date_transporteur": {"$sum": {"$cond": [{"$ifNull": ["$dates.remise_transporteur", False]}, 0, 1]}},
                "sans_date_livraison": {"$sum": {"$cond": [{"$ifNull": ["$dates.livraison_client", False]}, 0, 1]}}}},
    {"$sort": {"nb_commandes": -1}},
])
df = df.rename(columns={"_id": "statut"})
comparer("q0_statuts", df[["statut", "nb_commandes", "sans_date_approbation", "sans_date_transporteur", "sans_date_livraison"]], ["statut"])

print("geolocalisation :", db.geolocalisation.count_documents({}), "préfixes migrés sur",
      int(pandas.read_csv("resultats_sqlite/q0_geolocalisation.csv").nb_prefixes[0]), "(préfixes dont tous les points sont hors du Brésil écartés)")

df = executer("commandes", [
    {"$match": {"statut": "delivered", "articles.0": {"$exists": True}}},
    {"$addFields": {"ca": CA_ARTICLES}},
    {"$group": {"_id": MOIS, "chiffre_affaires": {"$sum": "$ca"}, "nb_commandes_livrees": {"$sum": 1}}},
    {"$sort": {"_id": 1}},
])
df = df.rename(columns={"_id": "mois"})
df["chiffre_affaires"] = df.chiffre_affaires.round(2)
comparer("q1a_ca_mensuel", df[["mois", "chiffre_affaires", "nb_commandes_livrees"]], ["mois"])

df = executer("commandes", [
    {"$match": {"statut": "delivered", "paiements.0": {"$exists": True}}},
    {"$addFields": {"total": {"$sum": "$paiements.montant"}}},
    {"$group": {"_id": "$client.etat", "nb_commandes": {"$sum": 1}, "panier_moyen": {"$avg": "$total"}}},
    {"$sort": {"panier_moyen": -1}},
])
df = df.rename(columns={"_id": "etat"})
df["panier_moyen"] = df.panier_moyen.round(2)
comparer("q1b_panier_moyen_etat", df[["etat", "nb_commandes", "panier_moyen"]], ["etat"])

df = executer("commandes", [
    {"$match": {"statut": "delivered"}},
    {"$unwind": "$articles"},
    {"$group": {"_id": "$articles.categorie", "ca": {"$sum": {"$add": ["$articles.prix", "$articles.frais_port"]}}}},
])
total = df.ca.sum()
df = df.sort_values("ca", ascending=False).head(10)
df["categorie"] = df["_id"]
df["chiffre_affaires"] = df.ca.round(2)
df["part_ca_pct"] = (100 * df.ca / total).round(2)
comparer("q1c_top_categories", df[["categorie", "chiffre_affaires", "part_ca_pct"]], ["categorie"])

df = executer("commandes", [
    {"$match": {"statut": "delivered", "delai_livraison_jours": {"$exists": True}}},
    {"$group": {"_id": "$client.etat",
                "delai_moyen_jours": {"$avg": "$delai_livraison_jours"},
                "retard": {"$avg": {"$cond": [{"$gt": ["$retard_jours", 0]}, 1, 0]}}}},
    {"$sort": {"delai_moyen_jours": -1}},
])
df = df.rename(columns={"_id": "etat"})
df["delai_moyen_jours"] = df.delai_moyen_jours.round(2)
df["taux_retard_pct"] = (100 * df.retard).round(2)
comparer("q1d_delai_retard_etat", df[["etat", "delai_moyen_jours", "taux_retard_pct"]], ["etat"])

df = executer("commandes", [
    {"$match": {"statut": "delivered"}},
    {"$addFields": {"note": NOTE}},
    {"$unwind": "$articles"},
    {"$group": {"_id": {"s": "$articles.vendeur_id", "o": "$_id"},
                "ca": {"$sum": {"$add": ["$articles.prix", "$articles.frais_port"]}},
                "note": {"$first": "$note"}}},
    {"$group": {"_id": "$_id.s", "chiffre_affaires": {"$sum": "$ca"}, "nb_commandes": {"$sum": 1}, "note_moyenne": {"$avg": "$note"}}},
    {"$sort": {"chiffre_affaires": -1}},
    {"$limit": 10},
])
df = df.rename(columns={"_id": "seller_id"})
df["chiffre_affaires"] = df.chiffre_affaires.round(2)
df["note_moyenne"] = df.note_moyenne.round(2)
comparer("q1e_top_vendeurs", df[["seller_id", "chiffre_affaires", "nb_commandes", "note_moyenne"]], ["seller_id"])

stats_vendeurs = executer("commandes", [
    {"$addFields": {"note": NOTE, "r": {"$ifNull": ["$retard_jours", 1000000000]}}},
    {"$addFields": {"flag": {"$cond": [
        {"$and": [{"$eq": ["$statut", "delivered"]}, {"$lt": ["$r", 1000000000]}]},
        {"$cond": [{"$gt": ["$r", 0]}, 1, 0]},
        None]}}},
    {"$unwind": "$articles"},
    {"$group": {"_id": {"s": "$articles.vendeur_id", "o": "$_id"},
                "nb": {"$sum": 1}, "note": {"$first": "$note"}, "flag": {"$first": "$flag"}}},
    {"$group": {"_id": "$_id.s", "nb_articles": {"$sum": "$nb"},
                "note_moyenne": {"$avg": "$note"}, "taux_retard": {"$avg": "$flag"}}},
])
seuils = [(30, 3.5, 0.05), (30, 3.8, 0.08), (30, 4.0, 0.10)]
for s in seuils:
    df = stats_vendeurs[(stats_vendeurs.nb_articles >= s[0]) & (stats_vendeurs.note_moyenne < s[1]) & (stats_vendeurs.taux_retard < s[2])]
    if len(df) > 0:
        break
df = df.sort_values(["note_moyenne", "nb_articles"], ascending=[True, False]).copy()
df["seller_id"] = df["_id"]
df["note_moyenne"] = df.note_moyenne.round(2)
df["taux_retard_pct"] = (100 * df.taux_retard).round(2)
comparer("q1f_vendeurs_mal_notes_ponctuels", df[["seller_id", "nb_articles", "note_moyenne", "taux_retard_pct"]], ["seller_id"])

df = executer("commandes", [
    {"$match": {"statut": "delivered", "delai_livraison_jours": {"$exists": True}}},
    {"$group": {"_id": None, "nb_livrees": {"$sum": 1},
                "nb_a_l_heure": {"$sum": {"$cond": [{"$lte": ["$retard_jours", 0]}, 1, 0]}}}},
])
df["taux_a_l_heure_pct"] = (100 * df.nb_a_l_heure / df.nb_livrees).round(2)
comparer("q1g_taux_heure_global", df[["nb_livrees", "nb_a_l_heure", "taux_a_l_heure_pct"]])

df = executer("commandes", [
    {"$match": {"statut": "delivered", "delai_livraison_jours": {"$exists": True}}},
    {"$group": {"_id": MOIS, "nb_livrees": {"$sum": 1},
                "taux": {"$avg": {"$cond": [{"$lte": ["$retard_jours", 0]}, 1, 0]}}}},
    {"$sort": {"_id": 1}},
])
df = df.rename(columns={"_id": "mois_achat"})
df["taux_a_l_heure_pct"] = (100 * df.taux).round(2)
comparer("q1g_taux_heure_mensuel", df[["mois_achat", "nb_livrees", "taux_a_l_heure_pct"]], ["mois_achat"])

df = executer("commandes", [
    {"$group": {"_id": {"e": "$client.etat", "u": "$client.unique_id"}}},
    {"$group": {"_id": "$_id.e", "nb_clients": {"$sum": 1}}},
    {"$lookup": {"from": "vendeurs", "localField": "_id", "foreignField": "etat", "as": "vendeurs"}},
    {"$lookup": {"from": "geolocalisation", "localField": "_id", "foreignField": "etat", "as": "geo"}},
    {"$unwind": "$geo"},
    {"$addFields": {"lng": {"$arrayElemAt": ["$geo.location.coordinates", 0]},
                    "lat": {"$arrayElemAt": ["$geo.location.coordinates", 1]}}},
    {"$group": {"_id": "$_id",
                "nb_clients": {"$first": "$nb_clients"},
                "nb_vendeurs": {"$first": {"$size": "$vendeurs"}},
                "sum_lat": {"$sum": {"$multiply": ["$lat", "$geo.nb_points"]}},
                "sum_lng": {"$sum": {"$multiply": ["$lng", "$geo.nb_points"]}},
                "nb_points": {"$sum": "$geo.nb_points"}}},
    {"$project": {
        "nb_clients": 1, "nb_vendeurs": 1,
        "ratio_clients_par_vendeur": {"$cond": [{"$gt": ["$nb_vendeurs", 0]}, {"$divide": ["$nb_clients", "$nb_vendeurs"]}, None]},
        "centroide_lat": {"$divide": ["$sum_lat", "$nb_points"]},
        "centroide_lng": {"$divide": ["$sum_lng", "$nb_points"]},
    }},
    {"$sort": {"ratio_clients_par_vendeur": -1}},
])
df = df.rename(columns={"_id": "etat"})
df["ratio_clients_par_vendeur"] = df.ratio_clients_par_vendeur.astype(float).round(1)
df["centroide_lat"] = df.centroide_lat.round(5)
df["centroide_lng"] = df.centroide_lng.round(5)
comparer("q1h_expansion_etat", df[["etat", "nb_clients", "nb_vendeurs", "ratio_clients_par_vendeur", "centroide_lat", "centroide_lng"]], ["etat"], 0.1)

TRANCHE = {"$cond": [{"$lte": ["$retard_jours", 0]}, "1 - a l'heure",
           {"$cond": [{"$lte": ["$retard_jours", 3]}, "2 - 1 a 3 jours",
            {"$cond": [{"$lte": ["$retard_jours", 7]}, "3 - 4 a 7 jours", "4 - plus de 7 jours"]}]}]}
MATCH_RETARD = {"$match": {"statut": "delivered", "retard_jours": {"$exists": True}}}

df = executer("commandes", [
    MATCH_RETARD,
    {"$addFields": {"note": NOTE}},
    {"$match": {"note": {"$ne": None}}},
    {"$group": {"_id": TRANCHE, "nb_commandes": {"$sum": 1}, "note_moyenne": {"$avg": "$note"}}},
    {"$sort": {"_id": 1}},
])
df = df.rename(columns={"_id": "tranche_retard"})
df["note_moyenne"] = df.note_moyenne.round(2)
comparer("q1i_note_par_tranche_retard", df[["tranche_retard", "nb_commandes", "note_moyenne"]], ["tranche_retard"])

df = executer("commandes", [
    MATCH_RETARD,
    {"$addFields": {"y": NOTE}},
    {"$match": {"y": {"$ne": None}}},
    {"$group": {"_id": "$client.etat", "n": {"$sum": 1},
                "sx": {"$sum": "$retard_jours"}, "sy": {"$sum": "$y"},
                "sxy": {"$sum": {"$multiply": ["$retard_jours", "$y"]}},
                "sxx": {"$sum": {"$multiply": ["$retard_jours", "$retard_jours"]}},
                "syy": {"$sum": {"$multiply": ["$y", "$y"]}}}},
])
num = df.n * df.sxy - df.sx * df.sy
den = ((df.n * df.sxx - df.sx ** 2) * (df.n * df.syy - df.sy ** 2)) ** 0.5
df["etat"] = df["_id"]
df["correlation_retard_note"] = (num / den).round(3)
df = df[["etat", "n", "correlation_retard_note"]].sort_values("correlation_retard_note")
comparer("q1i_correlation_retard_note_etat", df, ["etat"])

valeurs = executer("commandes", [
    {"$unwind": "$paiements"},
    {"$group": {"_id": "$paiements.moyen", "valeur_totale": {"$sum": "$paiements.montant"},
                "echeances_moyennes": {"$avg": "$paiements.echeances"}}},
])
nb_cmd = executer("commandes", [
    {"$unwind": "$paiements"},
    {"$group": {"_id": {"m": "$paiements.moyen", "o": "$_id"}}},
    {"$group": {"_id": "$_id.m", "nb_commandes": {"$sum": 1}}},
])
df = valeurs.merge(nb_cmd, on="_id")
nb_total = db.commandes.count_documents({"paiements.0": {"$exists": True}})
df["moyen_paiement"] = df["_id"]
df["pct_commandes"] = (100 * df.nb_commandes / nb_total).round(2)
df["pct_valeur"] = (100 * df.valeur_totale / df.valeur_totale.sum()).round(2)
df["valeur_totale"] = df.valeur_totale.round(2)
df["echeances_moyennes"] = df.echeances_moyennes.round(2)
df = df.sort_values("pct_valeur", ascending=False)
comparer("q1j_moyens_paiement", df[["moyen_paiement", "nb_commandes", "pct_commandes", "valeur_totale", "pct_valeur", "echeances_moyennes"]], ["moyen_paiement"])

df = executer("commandes", [
    {"$match": {"dates.remise_transporteur": {"$exists": True}}},
    {"$addFields": {"delai": {"$divide": [{"$subtract": ["$dates.remise_transporteur", "$dates.achat"]}, 86400000]}}},
    {"$unwind": "$articles"},
    {"$group": {"_id": {"s": "$articles.vendeur_id", "o": "$_id"}, "delai": {"$first": "$delai"}}},
    {"$group": {"_id": "$_id.s", "nb_commandes": {"$sum": 1}, "delai_traitement_moyen_jours": {"$avg": "$delai"}}},
    {"$match": {"nb_commandes": {"$gte": 30}}},
    {"$sort": {"delai_traitement_moyen_jours": -1}},
    {"$limit": 10},
])
df = df.rename(columns={"_id": "seller_id"})
df["delai_traitement_moyen_jours"] = df.delai_traitement_moyen_jours.round(2)
comparer("q1k_vendeurs_lents", df[["seller_id", "nb_commandes", "delai_traitement_moyen_jours"]], ["seller_id"])

df = executer("commandes", [
    {"$match": {"statut": {"$nin": ["canceled", "unavailable"]}}},
    {"$sort": {"dates.achat": -1}},
    {"$group": {"_id": "$client.unique_id", "etat": {"$first": "$client.etat"}, "nb": {"$sum": 1}}},
    {"$group": {"_id": "$etat", "nb_clients": {"$sum": 1},
                "nb_recurrents": {"$sum": {"$cond": [{"$gte": ["$nb", 2]}, 1, 0]}}}},
])
df = df.rename(columns={"_id": "etat"})
df["taux_recurrents_pct"] = (100 * df.nb_recurrents / df.nb_clients).round(2)
df = df.sort_values("taux_recurrents_pct", ascending=False)
comparer("q1l_clients_recurrents_etat", df[["etat", "nb_clients", "nb_recurrents", "taux_recurrents_pct"]], ["etat"])
print("verification avec la collection clients :", db.clients.count_documents({"nb_commandes_valides": {"$gte": 2}}), "recurrents au total contre", int(df.nb_recurrents.sum()))

df = executer("commandes", [
    {"$match": {"statut": "delivered", "delai_livraison_jours": {"$exists": True}}},
    {"$addFields": {"note": NOTE}},
    {"$group": {"_id": {"etat": "$client.etat",
                        "classe": {"$cond": [{"$lt": ["$delai_livraison_jours", 8]}, "rapide",
                                   {"$cond": [{"$lte": ["$delai_livraison_jours", 15]}, "normale", "lente"]}]}},
                "nb_commandes": {"$sum": 1}, "note_moyenne": {"$avg": "$note"}}},
])
df["etat"] = df["_id"].map(lambda x: x["etat"])
df["classe"] = df["_id"].map(lambda x: x["classe"])
df["note_moyenne"] = df.note_moyenne.round(2)
df["ordre"] = df.classe.map({"rapide": 0, "normale": 1, "lente": 2})
df = df.sort_values(["etat", "ordre"])
comparer("q1m_classes_livraison_etat", df[["etat", "classe", "nb_commandes", "note_moyenne"]], ["etat", "classe"])

df = executer("commandes", [
    {"$match": {"statut": "delivered"}},
    {"$addFields": {"note": NOTE}},
    {"$unwind": "$articles"},
    {"$match": {"articles.prix": {"$gt": 0}}},
    {"$addFields": {"ratio": {"$divide": ["$articles.frais_port", "$articles.prix"]}}},
    {"$group": {"_id": {"$cond": [{"$lt": ["$ratio", 0.15]}, "1 - faibles (<15 %)",
                        {"$cond": [{"$lt": ["$ratio", 0.40]}, "2 - moyens (15-40 %)",
                         {"$cond": [{"$lt": ["$ratio", 1.00]}, "3 - eleves (40-100 %)", "4 - superieurs au prix"]}]}]},
                "nb_articles": {"$sum": 1},
                "prix_moyen": {"$avg": "$articles.prix"},
                "frais_port_moyen": {"$avg": "$articles.frais_port"},
                "note_moyenne": {"$avg": "$note"}}},
    {"$sort": {"_id": 1}},
])
df = df.rename(columns={"_id": "poids_frais_port"})
df["prix_moyen"] = df.prix_moyen.round(2)
df["frais_port_moyen"] = df.frais_port_moyen.round(2)
df["note_moyenne"] = df.note_moyenne.round(2)
comparer("q1n_poids_frais_port", df[["poids_frais_port", "nb_articles", "prix_moyen", "frais_port_moyen", "note_moyenne"]], ["poids_frais_port"])
