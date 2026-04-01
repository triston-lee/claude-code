import { feature } from 'bun:bundle'
import { isEnvTruthy } from '../utils/envUtils.js'

export function isBuddyEnabled(): boolean {
  if (feature('BUDDY')) {
    return true
  }
  return isEnvTruthy(process.env.CLAUDE_CODE_ENABLE_BUDDY)
}
