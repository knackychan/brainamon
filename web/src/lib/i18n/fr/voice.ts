import type { messages as English } from '../en/voice.ts'
import type { Localized } from '../en/index.ts'

export const messages = {
  'voice.unsaved': 'Un enregistrement n’a pas pu être sauvegardé. Réessayez ou supprimez-le.',
  'voice.retrySave': 'Réessayer de sauvegarder',
  'voice.discard': 'Supprimer l’enregistrement',
  "voice.record.unsupported": "Ce navigateur ne peut pas enregistrer d’audio. Utilisez l’application Brainamon.",
  "voice.record.denied": "Microphone refusé. Autorisez-le dans les paramètres du téléphone pour Brainamon.",
  "voice.record.startFailed": "L’enregistrement n’a pas pu démarrer : {message}",
  "voice.record.tooLong": "Trop long en une fois : enregistrez en plusieurs parties.",
  "voice.queue.waiting": "Enregistré sur ce téléphone. Sera transcrit lorsque vous serez en ligne.",
  "voice.record.noSpeech": "Aucune parole détectée.",
  "voice.queue.notSaved": "Transcription impossible : {message} L’enregistrement n’a pas pu être conservé sur ce téléphone.",
  "voice.queue.kept": "Transcription impossible : {message} L’enregistrement est conservé sur ce téléphone.",
  "voice.record.discarded": "Enregistrement abandonné.",
  "voice.record.clock": "Enregistrement {clock}",
  "voice.record.level": "Niveau du microphone",
  "voice.record.stop": "Arrêter et transcrire",
  "voice.record.discard": "Abandonner",
  "voice.record.busy": "Transcription audio…",
  "voice.record.transcribing": "Transcription",
  "voice.record.start": "Enregistrer",
  "voice.record.file": "Fichier audio",
  "voice.record.info": "Transcription audio",
  "voice.record.upload": "Enregistrer ou choisir un fichier audio l’envoie à OpenAI pour transcription, via le PC en mode PC direct.",
  "voice.record.retention": "Les frais du fournisseur sont distincts ; ses conditions et sa conservation s’appliquent. Les enregistrements hors ligne peuvent attendre ici puis être envoyés à la connexion.",
  "voice.record.keyNeeded": "Les notes vocales nécessitent une clé OpenAI sur ce téléphone (Paramètres > Wiskit sur ce téléphone).",
  "voice.queue.offline": "Hors ligne : l’enregistrement attend sur ce téléphone.",
} as const satisfies Localized<typeof English>


