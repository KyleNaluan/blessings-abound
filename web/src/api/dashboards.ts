import { unwrap } from './approval'
import { api } from './client'
import type { components } from './schema'

type Schemas = components['schemas']
export type Dashboards = Schemas['Dashboards']
export type Category = Schemas['Category']
export type PriceBand = Schemas['PriceBandRead']
export type HistorySpan = Schemas['HistorySpan']
export type SyntheticTimeToSell = Schemas['SyntheticTimeToSell']
export type LiveTimeToSell = Schemas['LiveTimeToSell']
export type SeasonMonth = Schemas['SeasonMonth']
export type FunnelCounts = Schemas['FunnelCounts']
export type SyntheticFunnel = Schemas['SyntheticFunnel']
export type SyncHealth = Schemas['SyncHealth']
export type ConflictKind = Schemas['ConflictKind']

export function loadDashboards() {
  return unwrap(api.GET('/dashboards'))
}

export type InsightAnswer = Schemas['InsightAnswer']
export type InsightFact = Schemas['InsightFact']

export function askInsight(question: string) {
  return unwrap(api.POST('/dashboards/ask', { body: { question } }))
}
