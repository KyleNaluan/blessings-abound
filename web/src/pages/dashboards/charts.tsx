import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'

import type { Category } from '@/api/dashboards'
import { cn } from '@/lib/utils'

import { CATEGORY_NAMES, SOURCE_LINE, type Source } from './format'

// The charts are drawn here rather than with a chart library, because they are a few bars and one
// line chart, and each one keeps its numbers as text that a screen reader and a phone can read.

const SERIES_STROKE: Record<Category, string> = {
  apparel: 'var(--series-apparel)',
  electronics_games: 'var(--series-games)',
}

// The page's footnote says what each kind is, so the tag only has to name it.
const SOURCE_TEXT: Record<Source, string> = {
  history: 'Demo history',
  live: 'Live test sales',
}

// The tag under a chart's title, and under an insight answer, that says where its numbers are from.
export function SourceNote({ source }: { source: Source }) {
  return (
    <span
      className={cn(
        'mt-1 inline-block rounded-full px-2.5 py-0.5 text-[0.8125rem] font-semibold',
        source === 'history' ? 'bg-plain-soft text-plain-ink' : 'bg-info-soft text-info-ink',
      )}
    >
      {SOURCE_TEXT[source]}
    </span>
  )
}

// Every chart says where its numbers come from, and the two kinds never share a chart.
export function Chart({
  source,
  title,
  description,
  children,
}: {
  source: Source
  title: string
  description?: ReactNode
  children: ReactNode
}) {
  return (
    <figure className={cn('mb-8 border-l-4 pl-4 wide:pl-5', SOURCE_LINE[source])}>
      <figcaption className="mb-3">
        <span className="block font-bold">{title}</span>
        <SourceNote source={source} />
        {description && (
          <span className="mt-1 block text-sm text-muted-foreground">{description}</span>
        )}
      </figcaption>
      {children}
    </figure>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="border-y border-rule py-3.5">{children}</p>
}

export type Bar = {
  label: string
  // How long the bar is against the list's full length, or null for no bar.
  value: number | null
  text: string
  note?: string
  color?: string
}

const BAR_COLUMNS = 'grid grid-cols-[1fr_auto] gap-x-3 wide:grid-cols-[9.5rem_1fr_auto]'

// Lists of bars inside share one set of columns, so bars in different lists line up too.
export function BarColumns({ children }: { children: ReactNode }) {
  return <div className={BAR_COLUMNS}>{children}</div>
}

// A list of labeled bars. On a phone each bar sits under its label and value, and on a wider
// screen the label, bar and value share one row. The rows share the list's columns, so every bar
// starts and ends at the same place while the value column fits its longest text. Inside
// BarColumns, the list takes those columns instead of its own.
export function Bars({
  bars,
  max,
  label,
  inColumns = false,
}: {
  bars: Bar[]
  max: number
  label: string
  inColumns?: boolean
}) {
  return (
    <ul
      aria-label={label}
      className={cn(
        'border-t border-rule',
        inColumns ? 'col-span-full grid grid-cols-subgrid' : BAR_COLUMNS,
      )}
    >
      {bars.map((bar) => {
        const width = bar.value === null || max <= 0 ? 0 : Math.min(bar.value / max, 1) * 100
        return (
          <li
            key={bar.label}
            className="col-span-full grid grid-cols-subgrid items-center gap-y-1.5 border-b border-rule py-2.5"
          >
            <span className="text-[0.9375rem]">{bar.label}</span>
            <span className="text-right wide:order-last">
              <span className="block text-[0.9375rem] font-bold">{bar.text}</span>
              {bar.note && <span className="block text-sm text-muted-foreground">{bar.note}</span>}
            </span>
            <span aria-hidden="true" className="col-span-2 block h-3 bg-plain-soft wide:col-span-1">
              <span
                className={cn('block h-full', bar.color ?? 'bg-primary')}
                style={{ width: `${width}%` }}
              />
            </span>
          </li>
        )
      })}
    </ul>
  )
}

// The width the chart has to draw in, so its text stays the same size on a phone and a desktop.
function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(fallback)

  useLayoutEffect(() => {
    const element = ref.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return [ref, width] as const
}

export type Series = { category: Category; points: (number | null)[] }

const HEIGHT = 240
const PAD = { top: 12, right: 12, bottom: 30, left: 36 }
const NARROW = 480

// Four or five gridlines at a round step, so the axis reads 0, 2, 4, 6, 8 rather than 1.8, 3.5.
function gridSteps(value: number) {
  if (value <= 0) return [0, 1]
  const rough = value / 4
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((m) => m >= rough) ?? rough
  const steps = Math.ceil(value / step)
  return Array.from({ length: steps + 1 }, (_, index) => Number((index * step).toPrecision(6)))
}

// Apparel is a solid line with round points, and games a dashed line with square points, so the
// two read apart without color.
function Marker({ category, x, y }: { category: Category; x: number; y: number }) {
  const fill = SERIES_STROKE[category]
  if (category === 'apparel') return <circle cx={x} cy={y} r={3.5} fill={fill} />
  return <rect x={x - 3.5} y={y - 3.5} width={7} height={7} fill={fill} />
}

export function Legend({ categories }: { categories: Category[] }) {
  return (
    <ul className="mb-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
      {categories.map((category) => (
        <li key={category} className="flex items-center gap-2">
          <svg width="28" height="10" aria-hidden="true">
            <line
              x1="0"
              x2="28"
              y1="5"
              y2="5"
              stroke={SERIES_STROKE[category]}
              strokeWidth="2.5"
              strokeDasharray={category === 'apparel' ? undefined : '6 4'}
            />
            <Marker category={category} x={14} y={5} />
          </svg>
          {CATEGORY_NAMES[category]}
        </li>
      ))}
    </ul>
  )
}

// One line per category across the twelve months, with a gap where a month has no value.
export function MonthLines({ series, label }: { series: Series[]; label: string }) {
  const [ref, width] = useWidth(640)
  const narrow = width < NARROW
  const plotWidth = Math.max(width - PAD.left - PAD.right, 1)
  const plotHeight = HEIGHT - PAD.top - PAD.bottom
  const values = series.flatMap((line) => line.points.filter((point) => point !== null))
  const ticks = gridSteps(Math.max(0, ...values))
  const top = ticks[ticks.length - 1]
  const x = (month: number) => PAD.left + (plotWidth * (month + 0.5)) / 12
  const y = (value: number) => PAD.top + plotHeight * (1 - value / top)

  return (
    <div ref={ref}>
      <svg width={width} height={HEIGHT} role="img" aria-label={label} className="block">
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={PAD.left}
              x2={width - PAD.right}
              y1={y(tick)}
              y2={y(tick)}
              stroke="var(--rule)"
            />
            <text
              x={PAD.left - 6}
              y={y(tick)}
              textAnchor="end"
              dominantBaseline="middle"
              fontSize="12"
              fill="var(--muted-foreground)"
            >
              {tick}
            </text>
          </g>
        ))}
        {Array.from({ length: 12 }, (_, month) => (
          <text
            key={month}
            x={x(month)}
            y={HEIGHT - 10}
            textAnchor="middle"
            fontSize="12"
            fill="var(--muted-foreground)"
          >
            {new Date(2026, month, 1).toLocaleString(undefined, {
              month: narrow ? 'narrow' : 'short',
            })}
          </text>
        ))}
        {series.map((line) => {
          const path = line.points
            .map((point, month) =>
              point === null
                ? null
                : `${month === 0 || line.points[month - 1] === null ? 'M' : 'L'}${x(month)},${y(point)}`,
            )
            .filter(Boolean)
            .join(' ')
          return (
            <g key={line.category}>
              <path
                d={path}
                fill="none"
                stroke={SERIES_STROKE[line.category]}
                strokeWidth="2.5"
                strokeDasharray={line.category === 'apparel' ? undefined : '6 4'}
              />
              {line.points.map((point, month) =>
                point === null ? null : (
                  <Marker key={month} category={line.category} x={x(month)} y={y(point)} />
                ),
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
