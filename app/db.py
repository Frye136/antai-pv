"""Base SQLite : schéma, paramètres, journal."""
import json
import sqlite3
import threading
import getpass
from datetime import datetime
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY,
    code_client TEXT UNIQUE,
    type TEXT NOT NULL DEFAULT 'PM',          -- PM = personne morale, PP = particulier
    raison_sociale TEXT, siret TEXT,
    civilite TEXT, nom TEXT, prenom TEXT,
    date_naissance TEXT, lieu_naissance TEXT, pays_naissance TEXT,
    num_permis TEXT, date_permis TEXT,
    adresse TEXT, complement TEXT, code_postal TEXT, ville TEXT, pays TEXT DEFAULT 'FRANCE',
    email TEXT, email_cc TEXT, telephone TEXT,
    frais_dossier REAL,                       -- surcharge du forfait par défaut
    traitement_pv TEXT,                       -- PAIEMENT = ce client préfère qu'on paie et refacture
    notes TEXT, actif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS vehicules (
    id INTEGER PRIMARY KEY,
    immatriculation TEXT UNIQUE NOT NULL,     -- normalisée : AB123CD
    marque TEXT, modele TEXT, categorie TEXT, vin TEXT,
    notes TEXT, actif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS contrats (
    id INTEGER PRIMARY KEY,
    numero TEXT UNIQUE,
    vehicule_id INTEGER NOT NULL REFERENCES vehicules(id),
    client_id INTEGER NOT NULL REFERENCES clients(id),
    date_debut TEXT NOT NULL,                 -- 'YYYY-MM-DD HH:MM'
    date_fin TEXT,                            -- NULL = en cours
    cond_nom TEXT, cond_prenom TEXT, cond_date_naissance TEXT, cond_lieu_naissance TEXT,
    cond_num_permis TEXT, cond_adresse TEXT, cond_code_postal TEXT, cond_ville TEXT,
    designer_conducteur INTEGER DEFAULT 0,    -- 1 = désigner le conducteur plutôt que le client
    notes TEXT
);
CREATE INDEX IF NOT EXISTS ix_contrats_veh ON contrats(vehicule_id, date_debut);
CREATE TABLE IF NOT EXISTS pv (
    id INTEGER PRIMARY KEY,
    numero_avis TEXT UNIQUE,
    type TEXT DEFAULT 'AMENDE',               -- AMENDE / MAJOREE / FPS / AUTRE
    date_infraction TEXT, heure_infraction TEXT,
    immatriculation TEXT, immat_lue TEXT,
    titulaire TEXT,                           -- raison sociale du contrevenant inscrite sur l'avis
    lieu TEXT, nature TEXT, montant REAL,
    date_avis TEXT, date_limite TEXT,
    fichier TEXT, fichier_hash TEXT, ocr_texte TEXT,
    vehicule_id INTEGER, contrat_id INTEGER, client_id INTEGER,
    statut TEXT NOT NULL DEFAULT 'A_VERIFIER',
    anomalie TEXT,
    export_id INTEGER,
    date_designation TEXT, date_notification TEXT,
    frais_dossier REAL, refacture INTEGER DEFAULT 0,  -- refacture : frais de dossier facturés au client
    traitement TEXT,                          -- filière retenue : DESIGNATION ou PAIEMENT
    traitement_manuel TEXT,                   -- filière imposée à la main (sinon automatique)
    date_paiement TEXT, montant_paye REAL, mode_paiement TEXT, ref_paiement TEXT,
    facture_numero TEXT, date_facture TEXT, date_reglement TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_pv_statut ON pv(statut);
CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    fichier TEXT, nb_pv INTEGER, depose_le TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY,
    ts TEXT DEFAULT (datetime('now','localtime')),
    utilisateur TEXT, pv_id INTEGER, action TEXT, details TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

STATUTS = {
    "A_VERIFIER": "À vérifier",
    "NON_IDENTIFIE": "Locataire non trouvé",
    # filière désignation ANTAI
    "A_DENONCER": "À dénoncer",
    "EXPORTE": "Exporté (CSV)",
    "DEPOSE": "Déposé ANTAI",
    # filière payer et refacturer (stationnement, FPS, majorées, autres)
    "A_PAYER": "À payer",
    "PAYE": "Payé – à refacturer",
    "REFACTURE": "Refacturé – attente règlement",
    "CLOS": "Clos",
    "ANNULE": "Annulé",
}
TRAITEMENTS = {"DESIGNATION": "Désignation ANTAI", "PAIEMENT": "Payer et refacturer"}
MODES_PAIEMENT = ["Carte bancaire (en ligne)", "Virement", "Prélèvement", "Chèque", "Timbre amende", "Autre"]
# statuts recalculés par l'identification automatique
STATUTS_AUTO = ("A_VERIFIER", "NON_IDENTIFIE", "A_DENONCER", "A_PAYER")
# statuts soumis à une échéance (désignation ou paiement avant majoration)
STATUTS_ECHEANCE = STATUTS_AUTO
SQL_ECHEANCE = "('A_VERIFIER','NON_IDENTIFIE','A_DENONCER','A_PAYER')"

DEFAULT_SETTINGS = {
    "delai_jours": "45",
    "alerte_jours": "10",
    "frais_dossier": "25.00",
    "dossier_depot": "",
    "surveiller_depot": "1",
    "loueur_raison_sociale": "",
    "loueur_siret": "",
    "mail_mode": "smtp",            # smtp | outlook
    "smtp_host": "", "smtp_port": "587", "smtp_security": "starttls",
    "smtp_user": "", "smtp_password": "", "smtp_from": "", "smtp_bcc": "",
    "mail_sujet": "Avis de contravention – véhicule {immatriculations}",
    "mail_corps": (
        "Bonjour,\n\n"
        "Nous avons reçu {nb_pv} avis de contravention concernant un ou plusieurs véhicules "
        "que vous aviez en location :\n\n{liste_pv}\n\n"
        "Conformément à l'article L121-6 du Code de la route et à vos conditions générales de location, "
        "votre société a été désignée auprès de l'ANTAI en tant que locataire du véhicule. "
        "Vous allez recevoir un nouvel avis à votre nom, pour lequel il vous appartiendra le cas échéant "
        "de désigner le conducteur.\n\n"
        "Des frais de gestion de {frais_total} € HT vous seront facturés.\n\n"
        "Vous trouverez la copie des avis en pièce jointe.\n\n"
        "Cordialement,\n{loueur}"
    ),
    "mail_corps_paiement": (
        "Bonjour,\n\n"
        "Nous avons reçu {nb_pv} avis de contravention concernant un ou plusieurs véhicules "
        "que vous aviez en location :\n\n{liste_pv}\n\n"
        "Ces contraventions (stationnement, forfait post-stationnement ou amende ne pouvant faire l'objet "
        "d'une désignation) ont été réglées par nos soins afin d'éviter toute majoration.\n\n"
        "Conformément à vos conditions générales de location, le montant réglé ({montant_total} €) "
        "ainsi que des frais de gestion de {frais_total} € HT vous seront refacturés.\n\n"
        "Vous trouverez la copie des avis en pièce jointe.\n\n"
        "Cordialement,\n{loueur}"
    ),
    "stationnement_payer": "1",     # contraventions de stationnement : payer et refacturer plutôt que désigner
    "delai_fps_jours": "90",        # FPS : 3 mois pour payer avant majoration
    "mail_ligne_pv": "• Avis n° {numero_avis} – {immatriculation} – le {date_infraction} à {heure_infraction} – {lieu} ({nature})",
    "export_template": "",           # JSON, voir antai_export.DEFAULT_TEMPLATE
    "maj_auto": "1",                 # rechercher une mise à jour (GitHub) au démarrage
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path(), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


_conn: sqlite3.Connection | None = None
_lock = threading.RLock()  # connexion partagée entre l'interface et les traitements en arrière-plan
lock = _lock


def get() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _init()
    return _conn


def _init() -> None:
    global _conn
    _conn = connect()
    _conn.executescript(SCHEMA)
    _migrate(_conn)
    for k, v in DEFAULT_SETTINGS.items():
        _conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    _conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Mise à niveau des bases créées par une version précédente."""
    added = {
        "pv": ["titulaire TEXT", "traitement TEXT", "traitement_manuel TEXT", "date_paiement TEXT",
               "montant_paye REAL", "mode_paiement TEXT", "ref_paiement TEXT", "facture_numero TEXT",
               "date_facture TEXT", "date_reglement TEXT"],
        "clients": ["traitement_pv TEXT"],
    }
    for table, cols in added.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col in cols:
            if col.split()[0] not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
    # v1.3 : « Non désignable » devient la filière payer et refacturer
    conn.execute("UPDATE pv SET statut='A_PAYER', traitement='PAIEMENT' WHERE statut='NON_DESIGNABLE'")
    conn.execute("UPDATE pv SET traitement='DESIGNATION' WHERE traitement IS NULL "
                 "AND statut IN ('A_DENONCER','EXPORTE','DEPOSE')")


def reset_connection() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = None


def q(sql: str, params=()) -> list[sqlite3.Row]:
    with _lock:
        return get().execute(sql, params).fetchall()


def q1(sql: str, params=()) -> sqlite3.Row | None:
    with _lock:
        return get().execute(sql, params).fetchone()


def execute(sql: str, params=()) -> int:
    with _lock:
        cur = get().execute(sql, params)
        get().commit()
        return cur.lastrowid


def setting(key: str, default: str = "") -> str:
    r = q1("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r and r["value"] is not None else DEFAULT_SETTINGS.get(key, default)


def set_setting(key: str, value) -> None:
    execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))


def setting_json(key: str, default):
    try:
        v = setting(key)
        return json.loads(v) if v else default
    except Exception:
        return default


def log(action: str, details: str = "", pv_id: int | None = None) -> None:
    try:
        user = getpass.getuser()
    except Exception:
        user = "?"
    execute("INSERT INTO journal(utilisateur,pv_id,action,details) VALUES(?,?,?,?)",
            (user, pv_id, action, details))


def update(table: str, row_id: int, values: dict) -> None:
    if not values:
        return
    cols = ", ".join(f"{k}=?" for k in values)
    execute(f"UPDATE {table} SET {cols} WHERE id=?", (*values.values(), row_id))


def insert(table: str, values: dict) -> int:
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    return execute(f"INSERT INTO {table}({cols}) VALUES({marks})", tuple(values.values()))


def backup(keep: int = 30, force: bool = False) -> Path | None:
    """Sauvegarde quotidienne de la base (conserve les `keep` dernières)."""
    src = config.db_path()
    if not src.exists():
        return None
    dest_dir = config.sub("sauvegardes")
    dest = dest_dir / (f"antai_pv_{datetime.now():%Y%m%d_%H%M%S}.db" if force else f"antai_pv_{datetime.now():%Y%m%d}.db")
    if not dest.exists():
        bconn = sqlite3.connect(dest)
        get().backup(bconn)
        bconn.close()
    olds = sorted(dest_dir.glob("antai_pv_*.db"))
    for old in olds[:-keep]:
        old.unlink(missing_ok=True)
    return dest
