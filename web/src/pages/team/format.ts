import type { AccountStatus, Person, Role } from '@/api/team'

export const ROLE_NAMES: Record<Role, string> = { staff: 'Staff', manager: 'Manager' }

export const STATUS_NAMES: Record<AccountStatus, string> = {
  active: 'Active',
  invited: 'Invited',
  temporary_password: 'Temporary password',
  deactivated: 'Deactivated',
}

// The colour each status is written in, so the ones that need a manager's eye stand out.
export const STATUS_CLASSES: Record<AccountStatus, string> = {
  active: 'text-yes-ink',
  invited: 'text-info-ink',
  temporary_password: 'text-warn-ink',
  deactivated: 'text-muted-foreground',
}

export const byUsername = (a: Person, b: Person) => a.username.localeCompare(b.username)

// True for the only active manager left, whom the API won't let anyone deactivate or make staff.
export function isLastActiveManager(person: Person, people: Person[]) {
  if (person.role !== 'manager' || person.status === 'deactivated') return false
  return !people.some(
    (other) =>
      other.auth_user_id !== person.auth_user_id &&
      other.role === 'manager' &&
      other.status !== 'deactivated',
  )
}
