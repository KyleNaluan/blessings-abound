import type {
  DecisionChoice,
  Destination,
  ItemCardRequest,
  OverrideReason,
  Recommendation,
  StoreDepartment,
} from '@/api/appraisal'

// The labels staff see for the values the API takes, in the order they are offered.

export const STORE_DEPARTMENTS = [
  ['clothing', 'Clothing and shoes'],
  ['electronics_games', 'Electronics and games'],
] as const satisfies readonly (readonly [StoreDepartment, string])[]

export const CONDITIONS = [
  ['new_with_tags', 'New with tags'],
  ['new_without_tags', 'New without tags'],
  ['pre_owned', 'Pre-owned'],
] as const satisfies readonly (readonly [ItemCardRequest['condition'], string])[]

export const FLAWS = [
  ['stains', 'Stains'],
  ['tears', 'Tears'],
  ['scuffs', 'Scuffs'],
  ['missing_parts', 'Missing parts'],
] as const satisfies readonly (readonly [ItemCardRequest['flaws'][number], string])[]

export const DEPARTMENTS = [
  ['mens', "Men's"],
  ['womens', "Women's"],
  ['kids', "Kids'"],
] as const satisfies readonly (readonly [NonNullable<ItemCardRequest['department']>, string])[]

export const SIZE_TYPES = ['Regular', 'Tall', 'Plus size', 'Petite'] as const

export const DESTINATIONS = [
  ['store_floor', 'Back to the store floor'],
  ['seasonal_storage', 'Seasonal storage'],
  ['discard_or_donate', 'Discard or donate onward'],
] as const satisfies readonly (readonly [Destination, string])[]

// Why staff go against the recommendation, in the words staff pick from.
export const OVERRIDE_REASON_LABELS: Record<OverrideReason, string> = {
  wrong_comps: "The listings aren't the same item",
  better_condition: "It's in better shape than the listings",
  sells_for_more: 'We know it sells for more',
  worse_condition: "It's in worse shape than the listings",
  sells_for_less: 'We know it sells for less',
  hard_to_ship: 'Too big or heavy to ship for the price',
  not_genuine: 'It may not be genuine',
  other: 'Something else',
}

// True when staff are making the other call from a yes or no recommendation. A check has no side.
export const goesAgainst = (recommendation: Recommendation, decision: DecisionChoice) =>
  recommendation !== 'check' && recommendation !== decision

// The reasons each call can give, as the API allows them, in the order they are offered.
export const OVERRIDE_REASONS: Record<DecisionChoice, OverrideReason[]> = {
  yes: ['wrong_comps', 'better_condition', 'sells_for_more', 'other'],
  no: ['wrong_comps', 'worse_condition', 'sells_for_less', 'hard_to_ship', 'not_genuine', 'other'],
}

// What the page says once a no is saved, one sentence for each place an item can go.
export const WHERE_IT_GOES: Record<Destination, string> = {
  store_floor: 'It goes back to the store floor.',
  seasonal_storage: 'It goes to seasonal storage.',
  discard_or_donate: 'It gets discarded or donated onward.',
}

export const label = <T extends string>(options: readonly (readonly [T, string])[], value: T) =>
  options.find(([option]) => option === value)?.[1] ?? value

// A photo staff chose, with the object URL its preview shows.
export type Photo = { file: File; url: string }

export const MAX_PHOTOS = 4
export const MAX_PHOTO_MB = 15
const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp']
export const PHOTO_ACCEPT = PHOTO_TYPES.join(',')

// The checks the API makes, so staff hear at once rather than after the upload. A file the browser
// gives no type for is left to the API, which reads the type from the file itself.
export function photoProblem(photo: File, number: number): string | null {
  if (photo.size === 0) return `Photo ${number} is empty.`
  if (photo.size > MAX_PHOTO_MB * 1024 * 1024) {
    return `Photo ${number} is over ${MAX_PHOTO_MB} MB, so choose a smaller copy.`
  }
  if (photo.type && !PHOTO_TYPES.includes(photo.type)) {
    return `Photo ${number} isn't a JPEG, PNG or WebP image.`
  }
  return null
}
