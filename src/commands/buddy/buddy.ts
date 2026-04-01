import {
  companionUserId,
  getCompanion,
  roll,
  rollWithSeed,
} from '../../buddy/companion.js'
import { RARITY_STARS, type CompanionSoul } from '../../buddy/types.js'
import type { LocalCommandCall } from '../../types/command.js'
import { getGlobalConfig, saveGlobalConfig } from '../../utils/config.js'

const NAME_PREFIXES = [
  'Mochi',
  'Scout',
  'Pixel',
  'Nib',
  'Echo',
  'Pico',
  'Nova',
  'Bean',
  'Patch',
  'Sprocket',
] as const

const NAME_SUFFIXES = [
  '',
  'bit',
  'loop',
  'puff',
  'zip',
  'bean',
  'dot',
  'spark',
  'pop',
  'prime',
] as const

const PERSONALITIES = [
  'Curious, quietly supportive, and always watching for the next useful hint.',
  'A steady pair-programmer who loves clean diffs and tiny wins.',
  'Playful, observant, and likely to celebrate whenever you ship something neat.',
  'Calm under pressure, a little mischievous, and weirdly proud of good refactors.',
  'Soft-spoken, loyal, and happiest when the terminal is full of forward progress.',
] as const

const PET_REACTIONS = [
  'puffs up with pride.',
  'does a tiny victory wiggle.',
  'leans closer to the prompt box.',
  'looks delighted to still be on the job.',
  'seems ready for the next refactor.',
] as const

function usage(): string {
  return 'Usage: /buddy [status|pet|mute|unmute|rename <name>|reset]'
}

function buildSoul(): CompanionSoul {
  const seed = `${companionUserId()}:buddy-soul`
  const { bones } = roll(companionUserId())
  const { inspirationSeed } = rollWithSeed(seed)
  const prefix = NAME_PREFIXES[inspirationSeed % NAME_PREFIXES.length]
  const suffix =
    NAME_SUFFIXES[(Math.floor(inspirationSeed / 11)) % NAME_SUFFIXES.length]
  const rawName = suffix ? `${prefix}${suffix}` : prefix
  const name = rawName.charAt(0).toUpperCase() + rawName.slice(1)
  const personality =
    PERSONALITIES[(Math.floor(inspirationSeed / 97)) % PERSONALITIES.length]
  const speciesHint =
    bones.rarity === 'legendary'
      ? ' Carries itself like a tiny legend.'
      : bones.rarity === 'epic'
        ? ' Has a dramatic streak.'
        : ''
  return { name, personality: `${personality}${speciesHint}` }
}

function formatStatus(): string {
  const companion = getCompanion()
  const config = getGlobalConfig()
  if (!companion) {
    return 'No buddy hatched yet. Run /buddy to hatch one.'
  }
  return [
    `${companion.name} is active${config.companionMuted ? ' (muted)' : ''}.`,
    `Species: ${companion.species}`,
    `Rarity: ${companion.rarity} ${RARITY_STARS[companion.rarity]}`,
    `Personality: ${companion.personality}`,
  ].join('\n')
}

function setReaction(
  context: Parameters<LocalCommandCall>[1],
  reaction?: string,
): void {
  context.setAppState(prev => ({
    ...prev,
    companionReaction: reaction,
  }))
}

function setPetBurst(context: Parameters<LocalCommandCall>[1]): void {
  context.setAppState(prev => ({
    ...prev,
    companionPetAt: Date.now(),
  }))
}

export const call: LocalCommandCall = async (args, context) => {
  const trimmed = args.trim()
  const [command, ...rest] = trimmed.split(/\s+/).filter(Boolean)
  const action = command?.toLowerCase()
  const existing = getCompanion()
  const config = getGlobalConfig()

  if (!trimmed) {
    if (!existing) {
      const soul = buildSoul()
      const hatchedAt = Date.now()
      saveGlobalConfig(current => ({
        ...current,
        companion: { ...soul, hatchedAt },
        companionMuted: false,
      }))
      setReaction(
        context,
        `${soul.name} the ${roll(companionUserId()).bones.species} hatched and is ready to pair.`,
      )
      return {
        type: 'text',
        value: [
          `${soul.name} hatched.`,
          `Personality: ${soul.personality}`,
          'Run /buddy status to inspect it, or /buddy again to pet it.',
        ].join('\n'),
      }
    }

    if (config.companionMuted) {
      saveGlobalConfig(current => ({
        ...current,
        companionMuted: false,
      }))
      setReaction(context, `${existing.name} is back on duty.`)
      return {
        type: 'text',
        value: `${existing.name} is unmuted.`,
      }
    }

    setPetBurst(context)
    setReaction(
      context,
      `${existing.name} ${PET_REACTIONS[Date.now() % PET_REACTIONS.length]}`,
    )
    return {
      type: 'text',
      value: `You pet ${existing.name}.`,
    }
  }

  if (action === 'status') {
    return { type: 'text', value: formatStatus() }
  }

  if (action === 'pet') {
    if (!existing) {
      return {
        type: 'text',
        value: 'No buddy hatched yet. Run /buddy first.',
      }
    }
    if (config.companionMuted) {
      return {
        type: 'text',
        value: `${existing.name} is muted. Run /buddy unmute first.`,
      }
    }
    setPetBurst(context)
    setReaction(
      context,
      `${existing.name} ${PET_REACTIONS[Date.now() % PET_REACTIONS.length]}`,
    )
    return { type: 'text', value: `You pet ${existing.name}.` }
  }

  if (action === 'mute') {
    if (!existing) {
      return {
        type: 'text',
        value: 'No buddy hatched yet. Run /buddy first.',
      }
    }
    if (config.companionMuted) {
      return { type: 'text', value: `${existing.name} is already muted.` }
    }
    saveGlobalConfig(current => ({
      ...current,
      companionMuted: true,
    }))
    setReaction(context, undefined)
    return { type: 'text', value: `${existing.name} is muted.` }
  }

  if (action === 'unmute') {
    if (!existing) {
      return {
        type: 'text',
        value: 'No buddy hatched yet. Run /buddy first.',
      }
    }
    if (!config.companionMuted) {
      return { type: 'text', value: `${existing.name} is already active.` }
    }
    saveGlobalConfig(current => ({
      ...current,
      companionMuted: false,
    }))
    setReaction(context, `${existing.name} hops back into view.`)
    return { type: 'text', value: `${existing.name} is unmuted.` }
  }

  if (action === 'rename') {
    if (!existing) {
      return {
        type: 'text',
        value: 'No buddy hatched yet. Run /buddy first.',
      }
    }
    const nextName = rest.join(' ').trim()
    if (!nextName || nextName.length > 24 || /[\r\n]/.test(nextName)) {
      return {
        type: 'text',
        value: 'Please provide a single-line name up to 24 characters.',
      }
    }
    saveGlobalConfig(current =>
      current.companion
        ? {
            ...current,
            companion: {
              ...current.companion,
              name: nextName,
            },
          }
        : current,
    )
    setReaction(context, `${nextName} approves of the rename.`)
    return { type: 'text', value: `Buddy renamed to ${nextName}.` }
  }

  if (action === 'reset') {
    if (!existing) {
      return {
        type: 'text',
        value: 'No buddy hatched yet. Nothing to reset.',
      }
    }
    saveGlobalConfig(current => {
      const {
        companion: _companion,
        companionMuted: _companionMuted,
        ...rest
      } = current
      return rest
    })
    context.setAppState(prev => ({
      ...prev,
      companionReaction: undefined,
      companionPetAt: undefined,
    }))
    return {
      type: 'text',
      value: `${existing.name} was reset. Run /buddy to hatch a fresh companion.`,
    }
  }

  if (action === 'help') {
    return { type: 'text', value: usage() }
  }

  return { type: 'text', value: usage() }
}
