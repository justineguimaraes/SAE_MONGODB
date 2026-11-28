import sqlite3
import pandas
import os

conn = sqlite3.connect("olist.sqlite")
os.makedirs("resultats_sqlite", exist_ok=True)

# Exploration : 96 096 personnes réelles pour 99 441 customer_id, review_id en double, 58 % d'avis sans commentaire -> un client par customer_unique_id et des avis imbriqués dans la commande
q0 = """
SELECT
(SELECT COUNT(*) FROM customers) AS nb_customer_id,
(SELECT COUNT(DISTINCT customer_unique_id) FROM customers) AS nb_personnes_reelles,
(SELECT COUNT(*) FROM orders) AS nb_commandes,
(SELECT COUNT(*) FROM orders WHERE order_status = 'delivered') AS nb_commandes_livrees,
(SELECT COUNT(*) FROM order_reviews) AS nb_avis,
(SELECT COUNT(DISTINCT review_id) FROM order_reviews) AS nb_review_id_distincts,
(SELECT COUNT(*) FROM order_reviews WHERE review_comment_message IS NULL) AS nb_avis_sans_commentaire,
(SELECT COUNT(*) FROM products WHERE product_category_name IS NULL) AS nb_produits_sans_categorie,
(SELECT COUNT(*) FROM products p LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
WHERE p.product_category_name IS NOT NULL AND t.product_category_name_english IS NULL) AS nb_produits_categorie_sans_traduction,
(SELECT COUNT(*) FROM orders WHERE order_id NOT IN (SELECT order_id FROM order_reviews)) AS nb_commandes_sans_avis,
(SELECT COUNT(*) FROM (SELECT order_id FROM order_reviews GROUP BY order_id HAVING COUNT(*) >= 2)) AS nb_commandes_plusieurs_avis,
(SELECT COUNT(*) FROM (SELECT order_id FROM order_items GROUP BY order_id HAVING COUNT(*) >= 2)) AS nb_commandes_plusieurs_articles,
(SELECT COUNT(*) FROM (SELECT order_id FROM order_payments GROUP BY order_id HAVING COUNT(*) >= 2)) AS nb_commandes_plusieurs_paiements,
(SELECT COUNT(*) FROM orders WHERE order_id NOT IN (SELECT order_id FROM order_items)) AS nb_commandes_sans_article
"""
df = pandas.read_sql_query(q0, conn)
df.to_csv("resultats_sqlite/q0_exploration.csv", index=False)
print(df)

# Exploration : seules les commandes delivered ont une date de livraison (sauf 8) -> les délais se calculent uniquement sur les commandes livrées
q0_statuts = """
SELECT order_status AS statut,
COUNT(*) AS nb_commandes,
SUM(order_approved_at IS NULL) AS sans_date_approbation,
SUM(order_delivered_carrier_date IS NULL) AS sans_date_transporteur,
SUM(order_delivered_customer_date IS NULL) AS sans_date_livraison
FROM orders
GROUP BY order_status
ORDER BY nb_commandes DESC
"""
df = pandas.read_sql_query(q0_statuts, conn)
df.to_csv("resultats_sqlite/q0_statuts.csv", index=False)
print(df)

# Exploration : 1 million de points pour 19 015 préfixes, plusieurs noms de ville par préfixe et 40 points hors du Brésil -> agréger par préfixe et normaliser les villes
q0_geo = """
SELECT COUNT(*) AS nb_points,
COUNT(DISTINCT geolocation_zip_code_prefix) AS nb_prefixes,
COUNT(DISTINCT geolocation_city) AS nb_noms_villes,
COUNT(DISTINCT LOWER(TRIM(geolocation_city))) AS nb_noms_villes_minuscules,
(SELECT COUNT(*) FROM (SELECT geolocation_zip_code_prefix FROM geolocation
 GROUP BY geolocation_zip_code_prefix HAVING COUNT(DISTINCT geolocation_city) >= 2)) AS nb_prefixes_plusieurs_noms,
SUM(geolocation_lat NOT BETWEEN -35 AND 6 OR geolocation_lng NOT BETWEEN -75 AND -34) AS nb_points_hors_bresil
FROM geolocation
"""
df = pandas.read_sql_query(q0_geo, conn)
df.to_csv("resultats_sqlite/q0_geolocalisation.csv", index=False)
print(df)

# a) Directeur général : le CA progresse jusqu'au pic de novembre 2017 (1,15 M R$, Black Friday) puis se stabilise autour de 1 M R$ par mois -> anticiper les fins d'année
qa = """
WITH ca_commande AS (
SELECT order_id, SUM(price + freight_value) AS ca
FROM order_items
GROUP BY order_id
)
SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS mois,
ROUND(SUM(c.ca), 2) AS chiffre_affaires,
COUNT(*) AS nb_commandes_livrees
FROM orders o
JOIN ca_commande c ON c.order_id = o.order_id
WHERE o.order_status = 'delivered'
GROUP BY mois
ORDER BY mois
"""
df = pandas.read_sql_query(qa, conn)
df.to_csv("resultats_sqlite/q1a_ca_mensuel.csv", index=False)
print(df)

# b) Directeur commercial : le panier moyen est plus élevé dans le Nord-Est (PB 267 R$) que dans le Sud-Est (SP 142 R$) -> cibler les offres premium sur ces États
qb = """
WITH paiement_commande AS (
SELECT order_id, SUM(payment_value) AS total
FROM order_payments
GROUP BY order_id
)
SELECT cu.customer_state AS etat,
COUNT(*) AS nb_commandes,
ROUND(AVG(p.total), 2) AS panier_moyen
FROM orders o
JOIN customers cu ON cu.customer_id = o.customer_id
JOIN paiement_commande p ON p.order_id = o.order_id
WHERE o.order_status = 'delivered'
GROUP BY cu.customer_state
ORDER BY panier_moyen DESC
"""
df = pandas.read_sql_query(qb, conn)
df.to_csv("resultats_sqlite/q1b_panier_moyen_etat.csv", index=False)
print(df)

# c) Directeur commercial : les 10 premières catégories font 62 % du CA, santé-beauté en tête (9,2 %) -> concentrer catalogue et marketing sur ces catégories
qc = """
WITH ca_cat AS (
SELECT COALESCE(t.product_category_name_english, p.product_category_name, 'inconnue') AS categorie,
SUM(oi.price + oi.freight_value) AS ca
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
JOIN products p ON p.product_id = oi.product_id
LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
WHERE o.order_status = 'delivered'
GROUP BY categorie
),
tot AS (
SELECT categorie, ca, SUM(ca) OVER () AS ca_total
FROM ca_cat
)
SELECT categorie,
ROUND(ca, 2) AS chiffre_affaires,
ROUND(100.0 * ca / ca_total, 2) AS part_ca_pct
FROM tot
ORDER BY ca DESC
LIMIT 10
"""
df = pandas.read_sql_query(qc, conn)
df.to_csv("resultats_sqlite/q1c_top_categories.csv", index=False)
print(df)

# d) Directeur logistique : un client de RR attend 29 jours contre 9 à SP, et AL a 24 % de retards -> renégocier les transporteurs du Nord et du Nord-Est
qd = """
SELECT cu.customer_state AS etat,
ROUND(AVG(julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp)), 2) AS delai_moyen_jours,
ROUND(100.0 * AVG(o.order_delivered_customer_date > o.order_estimated_delivery_date), 2) AS taux_retard_pct
FROM orders o
JOIN customers cu ON cu.customer_id = o.customer_id
WHERE o.order_status = 'delivered'
AND o.order_delivered_customer_date IS NOT NULL
GROUP BY cu.customer_state
ORDER BY delai_moyen_jours DESC
"""
df = pandas.read_sql_query(qd, conn)
df.to_csv("resultats_sqlite/q1d_delai_retard_etat.csv", index=False)
print(df)

# e) Responsable marketplace : ces 10 vendeurs pèsent chacun 200 000 à 250 000 R$ de CA -> les fidéliser en priorité, en surveillant ceux notés 3,5
qe = """
WITH rev AS (
SELECT order_id, AVG(review_score) AS score
FROM order_reviews
GROUP BY order_id
),
vendeur_commande AS (
SELECT oi.seller_id, oi.order_id, SUM(oi.price + oi.freight_value) AS ca
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
WHERE o.order_status = 'delivered'
GROUP BY oi.seller_id, oi.order_id
)
SELECT vc.seller_id,
ROUND(SUM(vc.ca), 2) AS chiffre_affaires,
COUNT(*) AS nb_commandes,
ROUND(AVG(r.score), 2) AS note_moyenne
FROM vendeur_commande vc
LEFT JOIN rev r ON r.order_id = vc.order_id
GROUP BY vc.seller_id
ORDER BY chiffre_affaires DESC
LIMIT 10
"""
df = pandas.read_sql_query(qe, conn)
df.to_csv("resultats_sqlite/q1e_top_vendeurs.csv", index=False)
print(df)

# f) Responsable qualité : ces vendeurs livrent à l'heure mais sont mal notés -> le problème vient du produit ou de sa description, pas de la livraison
qf = """
WITH rev AS (
SELECT order_id, AVG(review_score) AS score
FROM order_reviews
GROUP BY order_id
),
vendeur_commande AS (
SELECT oi.seller_id, oi.order_id, COUNT(*) AS nb_articles
FROM order_items oi
GROUP BY oi.seller_id, oi.order_id
),
stats AS (
SELECT vc.seller_id,
SUM(vc.nb_articles) AS nb_articles,
AVG(r.score) AS note_moyenne,
AVG(CASE WHEN o.order_status = 'delivered'
THEN o.order_delivered_customer_date > o.order_estimated_delivery_date END) AS taux_retard
FROM vendeur_commande vc
JOIN orders o ON o.order_id = vc.order_id
LEFT JOIN rev r ON r.order_id = vc.order_id
GROUP BY vc.seller_id
)
SELECT seller_id, nb_articles,
ROUND(note_moyenne, 2) AS note_moyenne,
ROUND(100 * taux_retard, 2) AS taux_retard_pct
FROM stats
WHERE nb_articles >= :min_articles
AND note_moyenne < :max_note
AND taux_retard < :max_retard
ORDER BY note_moyenne ASC, nb_articles DESC
"""
seuils = [(30, 3.5, 0.05), (30, 3.8, 0.08), (30, 4.0, 0.10)]
for s in seuils:
    df = pandas.read_sql_query(qf, conn, params={"min_articles": s[0], "max_note": s[1], "max_retard": s[2]})
    if len(df) > 0:
        break
df.to_csv("resultats_sqlite/q1f_vendeurs_mal_notes_ponctuels.csv", index=False)
print(df)

# g) Directeur logistique : 91,9 % des commandes arrivent à l'heure en moyenne
qg1 = """
SELECT COUNT(*) AS nb_livrees,
SUM(order_delivered_customer_date <= order_estimated_delivery_date) AS nb_a_l_heure,
ROUND(100.0 * AVG(order_delivered_customer_date <= order_estimated_delivery_date), 2) AS taux_a_l_heure_pct
FROM orders
WHERE order_status = 'delivered'
AND order_delivered_customer_date IS NOT NULL
"""
df = pandas.read_sql_query(qg1, conn)
df.to_csv("resultats_sqlite/q1g_taux_heure_global.csv", index=False)
print(df)

# g) Directeur logistique : le taux chute à 85,7 % en novembre 2017 et 78,6 % en mars 2018 -> renforcer les transporteurs avant les pics
qg2 = """
SELECT strftime('%Y-%m', order_purchase_timestamp) AS mois_achat,
COUNT(*) AS nb_livrees,
ROUND(100.0 * AVG(order_delivered_customer_date <= order_estimated_delivery_date), 2) AS taux_a_l_heure_pct
FROM orders
WHERE order_status = 'delivered'
AND order_delivered_customer_date IS NOT NULL
GROUP BY mois_achat
ORDER BY mois_achat
"""
df = pandas.read_sql_query(qg2, conn)
df.to_csv("resultats_sqlite/q1g_taux_heure_mensuel.csv", index=False)
print(df)

# h) Directeur de l'expansion : PA, MA et PI n'ont qu'un vendeur pour des centaines de clients -> recruter des vendeurs locaux dans ces États
qh = """
WITH cl AS (
SELECT customer_state AS etat, COUNT(DISTINCT customer_unique_id) AS nb_clients
FROM customers
GROUP BY customer_state
),
ve AS (
SELECT seller_state AS etat, COUNT(*) AS nb_vendeurs
FROM sellers
GROUP BY seller_state
),
geo AS (
SELECT geolocation_state AS etat,
AVG(geolocation_lat) AS lat, AVG(geolocation_lng) AS lng
FROM geolocation
WHERE geolocation_lat BETWEEN -35 AND 6
AND geolocation_lng BETWEEN -75 AND -34
GROUP BY geolocation_state
)
SELECT cl.etat, cl.nb_clients,
COALESCE(ve.nb_vendeurs, 0) AS nb_vendeurs,
ROUND(1.0 * cl.nb_clients / ve.nb_vendeurs, 1) AS ratio_clients_par_vendeur,
ROUND(geo.lat, 5) AS centroide_lat,
ROUND(geo.lng, 5) AS centroide_lng
FROM cl
LEFT JOIN ve ON ve.etat = cl.etat
LEFT JOIN geo ON geo.etat = cl.etat
ORDER BY ratio_clients_par_vendeur DESC
"""
df = pandas.read_sql_query(qh, conn)
df.to_csv("resultats_sqlite/q1h_expansion_etat.csv", index=False)
print(df)

# i) Responsable satisfaction : la note passe de 4,29 à l'heure à 1,73 au-delà de 7 jours de retard -> traiter en priorité les colis en retard
qi1 = """
WITH rev AS (
SELECT order_id, AVG(review_score) AS score
FROM order_reviews
GROUP BY order_id
),
cmd AS (
SELECT o.order_id,
julianday(o.order_delivered_customer_date) - julianday(o.order_estimated_delivery_date) AS retard
FROM orders o
WHERE o.order_status = 'delivered'
AND o.order_delivered_customer_date IS NOT NULL
)
SELECT CASE WHEN retard <= 0 THEN '1 - a l''heure'
WHEN retard <= 3 THEN '2 - 1 a 3 jours'
WHEN retard <= 7 THEN '3 - 4 a 7 jours'
ELSE '4 - plus de 7 jours' END AS tranche_retard,
COUNT(*) AS nb_commandes,
ROUND(AVG(r.score), 2) AS note_moyenne
FROM cmd
JOIN rev r ON r.order_id = cmd.order_id
GROUP BY tranche_retard
ORDER BY tranche_retard
"""
df = pandas.read_sql_query(qi1, conn)
df.to_csv("resultats_sqlite/q1i_note_par_tranche_retard.csv", index=False)
print(df)

# i) Responsable satisfaction : la corrélation retard/note est la plus forte en CE, AL et PA (-0,47) -> la ponctualité y est le premier levier de satisfaction
qi2 = """
WITH rev AS (
SELECT order_id, AVG(review_score) AS score
FROM order_reviews
GROUP BY order_id
),
cmd AS (
SELECT cu.customer_state AS etat,
julianday(o.order_delivered_customer_date) - julianday(o.order_estimated_delivery_date) AS x,
r.score AS y
FROM orders o
JOIN customers cu ON cu.customer_id = o.customer_id
JOIN rev r ON r.order_id = o.order_id
WHERE o.order_status = 'delivered'
AND o.order_delivered_customer_date IS NOT NULL
)
SELECT etat, COUNT(*) AS n,
SUM(x) AS sx, SUM(y) AS sy, SUM(x*y) AS sxy, SUM(x*x) AS sxx, SUM(y*y) AS syy
FROM cmd
GROUP BY etat
"""
df = pandas.read_sql_query(qi2, conn)
df.to_csv("resultats_sqlite/q1i_agregats_correlation.csv", index=False)
num = df.n * df.sxy - df.sx * df.sy
den = ((df.n * df.sxx - df.sx ** 2) * (df.n * df.syy - df.sy ** 2)) ** 0.5
df["correlation_retard_note"] = (num / den).round(3)
df = df[["etat", "n", "correlation_retard_note"]]
df = df.sort_values("correlation_retard_note")
df.to_csv("resultats_sqlite/q1i_correlation_retard_note_etat.csv", index=False)
print(df)

# j) Directeur financier : la carte de crédit porte 78 % de la valeur avec 3,5 échéances en moyenne -> négocier ses frais et garder le paiement en plusieurs fois
qj = """
WITH tot AS (
SELECT COUNT(DISTINCT order_id) AS nb_cmd, SUM(payment_value) AS valeur
FROM order_payments
)
SELECT p.payment_type AS moyen_paiement,
COUNT(DISTINCT p.order_id) AS nb_commandes,
ROUND(100.0 * COUNT(DISTINCT p.order_id) / tot.nb_cmd, 2) AS pct_commandes,
ROUND(SUM(p.payment_value), 2) AS valeur_totale,
ROUND(100.0 * SUM(p.payment_value) / tot.valeur, 2) AS pct_valeur,
ROUND(AVG(p.payment_installments), 2) AS echeances_moyennes
FROM order_payments p, tot
GROUP BY p.payment_type
ORDER BY pct_valeur DESC
"""
df = pandas.read_sql_query(qj, conn)
df.to_csv("resultats_sqlite/q1j_moyens_paiement.csv", index=False)
print(df)

# k) Responsable vendeurs : ces vendeurs mettent jusqu'à 18 jours pour remettre le colis au transporteur -> les accompagner ou les pénaliser
qk = """
WITH vc AS (
SELECT DISTINCT oi.seller_id, oi.order_id
FROM order_items oi
)
SELECT vc.seller_id,
COUNT(*) AS nb_commandes,
ROUND(AVG(julianday(o.order_delivered_carrier_date) - julianday(o.order_purchase_timestamp)), 2) AS delai_traitement_moyen_jours
FROM vc
JOIN orders o ON o.order_id = vc.order_id
WHERE o.order_delivered_carrier_date IS NOT NULL
GROUP BY vc.seller_id
HAVING COUNT(*) >= 30
ORDER BY delai_traitement_moyen_jours DESC
LIMIT 10
"""
df = pandas.read_sql_query(qk, conn)
df.to_csv("resultats_sqlite/q1k_vendeurs_lents.csv", index=False)
print(df)

# l) Directeur marketing : seuls 3 % des clients repassent commande, et moins de 2 % en CE et AP -> lancer des actions de fidélisation
ql = """
WITH cmd AS (
SELECT cu.customer_unique_id AS uid, cu.customer_state AS etat,
ROW_NUMBER() OVER (PARTITION BY cu.customer_unique_id ORDER BY o.order_purchase_timestamp DESC) AS rn,
COUNT(*) OVER (PARTITION BY cu.customer_unique_id) AS nb_cmd
FROM orders o
JOIN customers cu ON cu.customer_id = o.customer_id
WHERE o.order_status NOT IN ('canceled', 'unavailable')
)
SELECT etat,
COUNT(*) AS nb_clients,
SUM(nb_cmd >= 2) AS nb_recurrents,
ROUND(100.0 * AVG(nb_cmd >= 2), 2) AS taux_recurrents_pct
FROM cmd
WHERE rn = 1
GROUP BY etat
ORDER BY taux_recurrents_pct DESC
"""
df = pandas.read_sql_query(ql, conn)
df.to_csv("resultats_sqlite/q1l_clients_recurrents_etat.csv", index=False)
print(df)

# m) Directeur logistique : la note moyenne passe de 4,41 pour une livraison rapide à 3,65 pour une livraison lente -> réduire les livraisons lentes dans chaque État
qm = """
WITH rev AS (
SELECT order_id, AVG(review_score) AS score
FROM order_reviews
GROUP BY order_id
),
cmd AS (
SELECT o.order_id, cu.customer_state AS etat,
julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp) AS delai
FROM orders o
JOIN customers cu ON cu.customer_id = o.customer_id
WHERE o.order_status = 'delivered'
AND o.order_delivered_customer_date IS NOT NULL
)
SELECT etat,
CASE WHEN delai < 8 THEN 'rapide'
WHEN delai <= 15 THEN 'normale'
ELSE 'lente' END AS classe,
COUNT(*) AS nb_commandes,
ROUND(AVG(r.score), 2) AS note_moyenne
FROM cmd
LEFT JOIN rev r ON r.order_id = cmd.order_id
GROUP BY etat, classe
ORDER BY etat, MIN(delai)
"""
df = pandas.read_sql_query(qm, conn)
df.to_csv("resultats_sqlite/q1m_classes_livraison_etat.csv", index=False)
print(df)

# n) Poids du port dans le prix : la note baisse de 4,13 à 3,89 quand le port dépasse le prix de l'article -> proposer la livraison offerte au-dessus d'un seuil de panier
qn = """
WITH rev AS (
SELECT order_id, AVG(review_score) AS score
FROM order_reviews
GROUP BY order_id
),
art AS (
SELECT oi.order_id, oi.price, oi.freight_value,
oi.freight_value / oi.price AS ratio
FROM order_items oi
JOIN orders o ON o.order_id = oi.order_id
WHERE o.order_status = 'delivered' AND oi.price > 0
)
SELECT CASE WHEN ratio < 0.15 THEN '1 - faibles (<15 %)'
WHEN ratio < 0.40 THEN '2 - moyens (15-40 %)'
WHEN ratio < 1.00 THEN '3 - eleves (40-100 %)'
ELSE '4 - superieurs au prix' END AS poids_frais_port,
COUNT(*) AS nb_articles,
ROUND(AVG(art.price), 2) AS prix_moyen,
ROUND(AVG(art.freight_value), 2) AS frais_port_moyen,
ROUND(AVG(r.score), 2) AS note_moyenne
FROM art
LEFT JOIN rev r ON r.order_id = art.order_id
GROUP BY poids_frais_port
ORDER BY poids_frais_port
"""
df = pandas.read_sql_query(qn, conn)
df.to_csv("resultats_sqlite/q1n_poids_frais_port.csv", index=False)
print(df)

conn.close()
