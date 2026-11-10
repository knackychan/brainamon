export const messages = {
  "onboarding.answer.skip": "Skip",
  "onboarding.answer.question": "Do you use Brainamon on a PC?",
  "onboarding.answer.helpTitle": "Brainamon on your phone",
  "onboarding.answer.helpLabel": "About the mobile app",
  "onboarding.answer.help": "This mobile companion lets you browse your desktop library anywhere. Keep the desktop app for the full experience, including video analysis and Claude Code integration.",
  "onboarding.answer.pc": "Yes, connect my PC",
  "onboarding.answer.pcHelp": "Your PC library shows up here",
  "onboarding.answer.phone": "Not yet, start on this phone",
  "onboarding.answer.phoneHelp": "Save links and notes; connect a PC later",
  "onboarding.answer.desktop": "Get the desktop app",
  "onboarding.task.title": "Get started",
  "onboarding.task.done": "done",
  "onboarding.task.count": "{done} of {total}",
  "onboarding.task.hide": "Hide",
  "onboarding.task.doneSuffix": ", done",
  "onboarding.task.ready": "Brainamon is ready.",
  "onboarding.task.install": "Install Brainamon",
  "onboarding.task.save": "Save your first link",
  "onboarding.task.wiskit": "Turn on Wiskit",
  "onboarding.coach.help": "Share to Brainamon from any app, or tap Add.",
  "onboarding.coach.close": "Got it",
} as const

export const budgets = {
  "onboarding.answer.skip": { limit: 20, params: {} },
  "onboarding.answer.desktop": { limit: 48, params: {} },
  "onboarding.task.title": { limit: 26, params: {} },
  "onboarding.task.done": { limit: 20, params: {} },
  "onboarding.task.count": { limit: 24, params: {"done":1,"total":3} },
  "onboarding.task.hide": { limit: 20, params: {} },
  "onboarding.coach.close": { limit: 20, params: {} },
} as const

