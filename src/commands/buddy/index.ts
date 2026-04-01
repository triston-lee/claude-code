import type { Command } from '../../commands.js'
import { isBuddyEnabled } from '../../buddy/enabled.js'

const buddy = {
  type: 'local',
  name: 'buddy',
  description: 'Hatch, pet, mute, and inspect your companion',
  argumentHint: '[status|pet|mute|unmute|rename <name>|reset]',
  supportsNonInteractive: true,
  isEnabled: isBuddyEnabled,
  load: () => import('./buddy.js'),
} satisfies Command

export default buddy
