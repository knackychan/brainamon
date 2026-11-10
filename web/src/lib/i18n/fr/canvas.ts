export const messages = {
  "canvas.waitingBackup": "Canvas en attente",
  "canvas.list": "Canvas",
  "canvas.new": "Nouveau canvas",
  "canvas.empty": "Pas encore de canvas. Demandez à Wiskit d’en créer un.",
  "canvas.elements": {"one":"{n} élément","other":"{n} éléments"},
  "canvas.saved": "Enregistré",
  "canvas.phone": "Téléphone",
  "canvas.offlineSaved": "✓ Enregistré",
  "canvas.offline": "Garder hors ligne",
  "canvas.composer.shared": "Partagé vers Ajouter. Vos choix sont toujours ici.",
  "canvas.composer.name": "Nom du canvas",
  "canvas.composer.namePlaceholder": "Nommez ce canvas",
  "canvas.composer.layout": "Disposition",
  "canvas.composer.rows": "Lignes",
  "canvas.composer.columns": "Colonnes",
  "canvas.composer.addTo": "Y ajouter",
  "canvas.composer.discardTitle": "Abandonner ces choix ?",
  "canvas.composer.uncertainLeave": "Le PC a peut-être enregistré cet ajout. Quitter abandonne seulement ces choix.",
  "canvas.composer.notAdded": {"one":"{n} pas encore ajouté.","other":"{n} pas encore ajoutés."},
  "canvas.composer.keep": "Continuer",
  "canvas.composer.discard": "Abandonner",
  "canvas.composer.picks": "Choix du canvas",
  "canvas.composer.resize": "Redimensionner le volet",
  "canvas.composer.controls": "Commandes de sélection",
  "canvas.composer.search": "Rechercher dans la bibliothèque",
  "canvas.composer.clearSearch": "Effacer la recherche",
  "canvas.composer.smart": "Sémantique",
  "canvas.composer.write": "Écrire une note",
  "canvas.composer.adding": "Ajout…",
  "canvas.composer.colour": "Couleur de la note",
  "canvas.composer.colourNumber": "Couleur {n}",
  "canvas.composer.collections": "Collections",
  "canvas.composer.favs": "Favoris",
  "canvas.composer.item": "Élément {id}",
  "canvas.composer.used": ", déjà sur ce canvas",
  "canvas.composer.loading": "Chargement de la bibliothèque…",
  "canvas.composer.none": "Aucun résultat",
  "canvas.composer.clear": "Effacer",
  "canvas.preview": "Aperçu du canvas, glissez pour déplacer, pincez pour zoomer",
  "canvas.board": "Canvas {name}, glissez pour déplacer, pincez pour zoomer",
  "canvas.pickBelow": "Choisissez des images ci-dessous",
  "canvas.pickedImage": "Image choisie",
  "canvas.notHere": "Pas encore sur ce téléphone",
  "canvas.image": "image",
  "canvas.imageUnavailable": "Image indisponible",
  "canvas.namedUnavailable": "{label} : image indisponible",
  "canvas.remove": "✕ Retirer",
  "canvas.fitBoard": "Ajuster le canvas",
  "canvas.fit": "Ajuster",
  "canvas.fitKey": "VOIR",
  "canvas.zoomIn": "Agrandir",
  "canvas.zoomOut": "Réduire",
  "canvas.proposal.label": "Proposition de canvas de Wiskit",
  "canvas.proposal.add": "Ajouter au canvas",
  "canvas.proposal.helpTitle": "Appliquer les changements au canvas",
  "canvas.proposal.help": "Les éléments existants restent. Seuls les éléments listés bougent si une réorganisation est demandée. Rien ne change avant de toucher Appliquer.",
  "canvas.proposal.newBoard": "Nouveau canvas",
  "canvas.proposal.existing": {"one":"{n} élément déjà présent","other":"{n} éléments déjà présents"},
  "canvas.proposal.summary": "Disposition {layout} · {thumbs} miniatures · {frames} images · {notes} notes de texte · {moves} déplacés",
  "canvas.proposal.ungrouped": "Sans groupe",
  "canvas.proposal.move": "Déplacer l’existant",
  "canvas.proposal.text": "Note de texte",
  "canvas.proposal.frame": "Image",
  "canvas.proposal.thumbnail": "Miniature",
  "canvas.proposal.placed": "Positions définies",
  "canvas.proposal.existingKind": "existant",
  "canvas.proposal.frameKind": "image",
  "canvas.proposal.textKind": "texte",
  "canvas.proposal.thumbnailKind": "miniature",
  "canvas.proposal.decline": "Refuser",
  "canvas.proposal.applying": "Application…",
  "canvas.proposal.apply": "Appliquer",
  "canvas.composer.unavailable": {
    "one": "{n} image choisie n’est pas encore sur ce téléphone",
    "other": "{n} images choisies ne sont pas encore sur ce téléphone"
  },
  "canvas.error.detail": "Erreur du canvas : {detail}",
  "canvas.composer.changed": "Le canvas a changé. Vérifiez-le et touchez à nouveau Ajouter.",
  "canvas.composer.limit": "60 maximum à la fois. Ajoutez ces choix, puis continuez.",
  "canvas.composer.uncertain": "Ajout non confirmé. Touchez Ajouter pour vérifier ce même ajout.",
  "canvas.composer.invalid": "Retirez les caractères invalides du nom ou de la note.",
  "canvas.composer.longName": "Le nom du canvas est limité à 80 caractères.",
  "canvas.composer.longNote": "La note est limitée à 1000 caractères.",
  "canvas.composer.nameFirst": "Nommez d’abord votre canvas.",
  "canvas.composer.exists": "« {name} » existe déjà.",
  "canvas.composer.added": "{n} ajoutés à {name}.",
  "canvas.composer.created": "{name} créé avec {n}.",
  "canvas.composer.duplicates": {
    "one": "{n} choix est déjà sur ce canvas.",
    "other": "{n} choix sont déjà sur ce canvas."
  },
  "canvas.status.missing": "La création précédente du canvas est absente. Actualisez après réception de la sauvegarde.",
  "canvas.status.synced": "Synchronisé",
  "canvas.status.phone": "Sur ce téléphone",
  "canvas.status.waiting": "En attente de synchronisation",
  "canvas.status.update": "Enregistré sur ce téléphone. Mettez le PC à jour pour synchroniser les canvas.",
  "canvas.status.refused": "Non synchronisé : {reason} {kept}",
  "canvas.status.refusedCreation": "Non synchronisé : {reason}",
  "canvas.status.creationReason": "Le PC a refusé cette création.",
  "canvas.status.changeReason": "Le PC a refusé ce changement.",
  "canvas.status.pcCopy": "Le PC a modifié ce canvas depuis ; sa copie est affichée.",
  "canvas.status.kept": "La copie du téléphone est conservée."
} as const

export const budgets = {
  "canvas.offline": {
    "limit": 22,
    "params": {}
  },
  "canvas.composer.rows": {
    "limit": 10,
    "params": {}
  },
  "canvas.composer.columns": {
    "limit": 12,
    "params": {}
  },
  "canvas.composer.keep": {
    "limit": 14,
    "params": {}
  },
  "canvas.composer.discard": {
    "limit": 12,
    "params": {}
  },
  "canvas.fitKey": {
    "limit": 5,
    "params": {}
  },
  "canvas.proposal.apply": {
    "limit": 14,
    "params": {}
  },
  "canvas.proposal.decline": {
    "limit": 14,
    "params": {}
  }
} as const


