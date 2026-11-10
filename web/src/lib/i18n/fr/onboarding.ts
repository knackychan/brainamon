import type { messages as English } from '../en/onboarding.ts'
import type { Localized } from '../en/index.ts'

export const messages = {
  "onboarding.answer.skip": "Passer",
  "onboarding.answer.question": "Utilisez-vous Brainamon sur PC ?",
  "onboarding.answer.helpTitle": "Brainamon sur votre téléphone",
  "onboarding.answer.helpLabel": "À propos de l’application mobile",
  "onboarding.answer.help": "Cette application mobile vous permet de consulter votre bibliothèque PC partout. Gardez l’application PC pour toutes les fonctions, dont l’analyse vidéo et l’intégration de Claude Code.",
  "onboarding.answer.pc": "Oui, connecter mon PC",
  "onboarding.answer.pcHelp": "Votre bibliothèque PC apparaît ici",
  "onboarding.answer.phone": "Pas encore, commencer ici",
  "onboarding.answer.phoneHelp": "Enregistrez liens et notes ; connectez un PC plus tard",
  "onboarding.answer.desktop": "Obtenir l’application PC",
  "onboarding.task.title": "Premiers pas",
  "onboarding.task.done": "terminé",
  "onboarding.task.count": "{done} sur {total}",
  "onboarding.task.hide": "Masquer",
  "onboarding.task.doneSuffix": ", terminé",
  "onboarding.task.ready": "Brainamon est prêt.",
  "onboarding.task.install": "Installer Brainamon",
  "onboarding.task.save": "Enregistrer un premier lien",
  "onboarding.task.wiskit": "Activer Wiskit",
  "onboarding.coach.help": "Partagez vers Brainamon depuis une application, ou appuyez sur Ajouter.",
  "onboarding.coach.close": "Compris",
} as const satisfies Localized<typeof English>


