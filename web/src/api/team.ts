import { unwrap } from './approval'
import { api } from './client'
import type { components } from './schema'

type Schemas = components['schemas']
export type Person = Schemas['PersonRead']
export type Role = Schemas['Role']
export type AccountStatus = Schemas['AccountStatus']
export type NewPerson = Schemas['CreateWithTemporaryPasswordRequest']
// The only time a temporary password is shown, because the API stores it nowhere.
export type PersonWithTemporaryPassword = Schemas['PersonWithTemporaryPassword']

const person = (authUserId: string) => ({ params: { path: { auth_user_id: authUserId } } })

export function loadPeople() {
  return unwrap(api.GET('/team/people'))
}

export function invitePerson(body: NewPerson & { email: string }) {
  return unwrap(api.POST('/team/people/invite', { body }))
}

export function createWithTemporaryPassword(body: NewPerson) {
  return unwrap(api.POST('/team/people/temporary-password', { body }))
}

export function issueTemporaryPassword(authUserId: string) {
  return unwrap(api.POST('/team/people/{auth_user_id}/temporary-password', person(authUserId)))
}

export function changeRole(authUserId: string, role: Role) {
  return unwrap(api.PATCH('/team/people/{auth_user_id}', { ...person(authUserId), body: { role } }))
}

export function deactivatePerson(authUserId: string) {
  return unwrap(api.POST('/team/people/{auth_user_id}/deactivate', person(authUserId)))
}

export function reactivatePerson(authUserId: string) {
  return unwrap(api.POST('/team/people/{auth_user_id}/reactivate', person(authUserId)))
}
