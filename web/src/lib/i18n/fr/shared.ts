import type { messages as English } from '../en/shared.ts'
import type { Localized } from '../en/index.ts'

export const messages = {
  "shared.analysis.interval": "Intervalle des images",
  "shared.analysis.seconds": "secondes · 0 = désactivé (aucune image)",
  "shared.analysis.transcription": "Transcription",
  "shared.analysis.extract": "Extraire l’audio et transcrire",
  "shared.analysis.model": "Modèle de transcription",
  "shared.analysis.openai": "GPT-Transcribe (clé OpenAI)",
  "shared.analysis.provider": "Fournisseur IA",
  "shared.analysis.none": "aucun",
  "shared.analysis.budget": "Images envoyées à l’IA",
  "shared.analysis.frames": "Images extraites",
  "shared.analysis.after": "Après l’analyse",
  "shared.analysis.deleteVideo": "Supprimer la vidéo téléchargée après l’analyse",
  "shared.analysis.deleteAudio": "Supprimer l’audio extrait après l’analyse",
  "shared.analysis.disclosure": "Si la transcription est activée, l’audio extrait est envoyé à OpenAI. Un rapport IA envoie le texte et les images choisies à Anthropic (claude), OpenAI ou au serveur FreeLLMAPI configuré et à ses fournisseurs en amont. Les frais des fournisseurs sont distincts ; leurs conditions et durées de conservation s’appliquent. Choisir « none » désactive uniquement le rapport IA.",
  "shared.analysis.keepShow": "Garder et afficher dans le canvas de l’élément",
  "shared.analysis.keepDisk": "Garder sur disque (masqué dans le canvas)",
  "shared.analysis.deleteFrames": "Supprimer les images après l’analyse",
  "shared.analysis.auto": "Auto (selon la durée)",
  "shared.analysis.off": "Désactivé (transcription seule)",
  "shared.analysis.upTo": "Jusqu’à {n}",
  "shared.native.google.replaced": "Remplacé par une connexion plus récente.",

  "shared.native.backup.pc-managed": "Gérez la sauvegarde PC sur votre PC. Seules les sauvegardes de téléphones autonomes se modifient ici.",
  "shared.native.backup.library-changed": "La bibliothèque du téléphone a changé. Cette tâche ne peut pas continuer.",
  "shared.native.backup.account": "Connectez le compte Google choisi pour cette sauvegarde, puis réessayez.",
  "shared.native.backup.saved-task": "Terminez d’abord la tâche de sauvegarde enregistrée.",
  "shared.native.backup.select-backup": "Sélectionnez d’abord une sauvegarde de téléphone autonome.",
  "shared.native.backup.task-changed": "La tâche de sauvegarde sélectionnée a changé.",
  "shared.native.backup.identity": "La clé ou la connexion Google a changé. Connectez le compte choisi et réessayez.",
  "shared.native.backup.paused": "Tâche de sauvegarde en pause. Reprenez quand vous voulez.",
  "shared.native.backup.replacement-missing": "Le remplacement enregistré est introuvable. L’ancienne sauvegarde est conservée. Déconnectez la sauvegarde et gardez le contenu local du téléphone.",
  "shared.native.backup.replacement-duplicate": "Drive contient des fichiers de remplacement en double. L’ancienne sauvegarde est conservée. Déconnectez la sauvegarde et gardez le contenu local du téléphone.",
  "shared.native.backup.replacement-verification": "La vérification du remplacement a échoué. L’ancienne sauvegarde est conservée. Réessayez ou déconnectez la sauvegarde.",
  "shared.native.backup.replacement-retained": "Le remplacement n’a pas pu être vérifié. Les anciens fichiers restants sont conservés. Réessayez ou déconnectez la sauvegarde.",
  "shared.native.recovery.material": "Utilisez le code d’origine, un lien d’association ou le texte d’un fichier de récupération exporté du téléphone.",
  "shared.native.recovery.fingerprint": "La clé de récupération ne correspond pas à son empreinte.",
  "shared.native.recovery.unsupported": "Fichier de récupération non pris en charge.",
  "shared.native.recovery.identity": "La bibliothèque ou le compte Google a changé. Reconnectez-vous et réessayez.",
  "shared.native.recovery.name": "Le nom du fichier de récupération ne correspond pas à son contenu.",
  "shared.native.recovery.missing-setup": "Cette configuration manque dans Google Drive. Gardez le fichier et connectez le compte d’origine.",
  "shared.native.recovery.setup-mismatch": "Le fichier enregistré ne correspond pas à la configuration dans Drive.",
  "shared.native.recovery.verification": "La vérification a échoué. Gardez votre code de récupération d’origine.",
  "shared.native.recovery.select-file": "Sélectionnez le fichier enregistré pour cette configuration.",
  "shared.native.recovery.other-backup": "Ce fichier appartient à une autre sauvegarde téléphone.",
  "shared.native.recovery.prepare-first": "Préparez d’abord la récupération.",
  "shared.native.recovery.changed-while-saving": "La bibliothèque ou la récupération a changé pendant l’enregistrement. Enregistrez à nouveau le fichier.",

  "shared.native.google.timeout": "Google n’a pas répondu en 2 minutes (sa fenêtre s’est peut-être fermée). Réessayez.",
  "shared.native.google.renewal-timeout": "Google n’a pas répondu au renouvellement de connexion en 20 secondes.",
  "shared.native.secure.write": "La connexion n’a pas pu être enregistrée de manière sécurisée. Réessayez avant de quitter cette page.",
  "shared.native.network.timeout": "Impossible de vérifier le réseau.",
  "shared.native.recovery.kit-in-code": "C’est un fichier de récupération. Ouvrez-le avec Fichier dans Ouvrir avec.",
  "shared.native.recovery.passphrase-mismatch": "Les phrases secrètes de récupération ne correspondent pas.",
  "shared.native.recovery.file-limit": "Les fichiers de récupération doivent faire moins de 32 Kio.",
  "shared.native.network.network": "Impossible de vérifier le réseau.",










  "shared.native.google.denied": "Google Drive n’a pas été connecté.",
  "shared.native.google.consent": "Vous devez d’abord donner votre accord à Google Drive.",
  "shared.native.google.failed": "Échec de la connexion Google : {detail}",
  "shared.native.scanner.failed": "Le scanner n’a pas pu démarrer : {detail}",
  "shared.native.google.detail": "Connexion Google : {detail}",
  "shared.native.scanner.detail": "Scanner : {detail}",
  "shared.native.secure.detail": "Enregistrement sécurisé : {detail}",
  "shared.native.network.detail": "Connexion réseau : {detail}",
  "shared.native.vault.detail": "Opération sur le coffre : {detail}",
  "shared.native.recovery.detail": "Récupération : {detail}",
  "shared.native.backup.detail": "Sauvegarde : {detail}",
  "shared.native.openUri.detail": "Ouverture d’Obsidian : {detail}",
} as const satisfies Localized<typeof English>


