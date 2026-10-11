'use client'

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Coins, Gauge, TrendingUp, Wallet } from 'lucide-react'
import {
  type CostAccountingResponse,
  type CostAlert,
  type CreditLotState,
  fetchCostAccounting,
  type ProviderUtilization,
} from '@/lib/api'
import { formatCurrency } from '@/lib/formatters'
import { cn } from '@/lib/utils'

const PROVIDER_NAMES: Record<string, string> = {
  claude: 'Claude Code',
  codex: 'Codex',
  other: 'Other',
}

function providerName(provider: string): string {
  return PROVIDER_NAMES[provider] ?? provider
}

function usd(value: number): string {
  return value >= 100
    ? `$${Math.round(value).toLocaleString()}`
    : formatCurrency(value)
}

function credits(value: number): string {
  return Math.round(value).toLocaleString()
}

/** "in 2d 4h" / "in 35m" for a future instant; null when absent or past. */
export function timeUntil(
  iso: string | null,
  now: Date = new Date(),
): string | null {
  if (!iso) return null
  const mins = Math.round((new Date(iso).getTime() - now.getTime()) / 60000)
  if (mins <= 0) return null
  if (mins < 60) return `in ${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `in ${hours}h ${mins % 60}m`
  return `in ${Math.floor(hours / 24)}d ${hours % 24}h`
}

function Card({
  title,
  icon: Icon,
  children,
}: {
  title: string
  icon: React.ComponentType<{ className?: string }>
  children: React.ReactNode
}) {
  return (
    <section className="rounded-2xl border border-slate-800/80 bg-slate-900/65 p-4">
      <h3 className="mb-3 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
        <Icon className="h-3.5 w-3.5 text-amber-500" />
        {title}
      </h3>
      {children}
    </section>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-slate-400">{label}</span>
      <span className="font-mono text-slate-200">{value}</span>
    </div>
  )
}

const ALERT_STYLES: Record<CostAlert['severity'], string> = {
  critical: 'border-red-800/60 bg-red-900/20 text-red-300',
  warning: 'border-amber-800/60 bg-amber-900/20 text-amber-200',
  info: 'border-slate-700/60 bg-slate-800/40 text-slate-300',
}

function Alerts({ alerts }: { alerts: CostAlert[] }) {
  if (alerts.length === 0) return null
  return (
    <ul className="mb-4 space-y-2">
      {alerts.map((alert) => (
        <li
          key={alert.code}
          className={cn(
            'flex items-start gap-2 rounded-xl border px-3 py-2 text-sm',
            ALERT_STYLES[alert.severity],
          )}
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{alert.message}</span>
        </li>
      ))}
    </ul>
  )
}

function CashCard({ data }: { data: CostAccountingResponse }) {
  const { cash, window } = data
  return (
    <Card title={`Cash, last ${window.days} days`} icon={Wallet}>
      <p className="mb-3 font-mono text-2xl text-slate-100">
        {usd(cash.total_usd)}
      </p>
      <div className="space-y-1.5">
        {cash.subscriptions.map((sub) => (
          <Row
            key={`${sub.provider}-${sub.plan}-${sub.monthly_usd}`}
            label={`${providerName(sub.provider)} ${sub.plan}${sub.monthly_usd == null ? ' (price unverified)' : ` at $${sub.monthly_usd}/mo`}`}
            value={usd(sub.amortized_usd)}
          />
        ))}
        <Row label="Metered API" value={usd(cash.metered_api_usd)} />
        <Row label="Credit purchases" value={usd(cash.credit_purchases_usd)} />
      </div>
      <p className="mt-3 border-t border-slate-800 pt-2 text-xs text-slate-400">
        This month {usd(cash.month_to_date_usd)} so far, about{' '}
        {usd(cash.projected_month_usd)} by month end.
      </p>
    </Card>
  )
}

function WindowBar({ used }: { used: number }) {
  const color =
    used >= 100 ? 'bg-red-500' : used >= 80 ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div
      className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800"
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={used}
    >
      <div
        className={cn('h-full', color)}
        style={{ width: `${Math.min(used, 100)}%` }}
      />
    </div>
  )
}

function HeadroomCard({ utilization }: { utilization: ProviderUtilization[] }) {
  return (
    <Card title="Plan limits used" icon={Gauge}>
      {utilization.length === 0 ? (
        <p className="text-sm text-slate-400">No usage-limit readings yet.</p>
      ) : (
        <div className="space-y-3">
          {utilization.map((prov) => (
            <div key={prov.provider}>
              <p className="mb-1.5 text-sm text-slate-200">
                {providerName(prov.provider)}
                {prov.plan_type && (
                  <span className="text-slate-500"> · {prov.plan_type}</span>
                )}
              </p>
              {prov.windows.map((w) => {
                const reset = timeUntil(w.resets_at)
                return (
                  <div key={w.window_minutes} className="mb-2">
                    <div className="mb-1 flex justify-between text-xs text-slate-400">
                      <span>
                        {w.label} {w.used_percent.toFixed(0)}%
                      </span>
                      <span>
                        {w.reset_since_observed
                          ? 'reset since last reading'
                          : reset
                            ? `resets ${reset}`
                            : ''}
                      </span>
                    </div>
                    <WindowBar used={w.used_percent} />
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function lotLine(lot: CreditLotState): string {
  const source =
    lot.source === 'grant'
      ? 'Grant'
      : lot.source === 'purchase'
        ? 'Purchased'
        : 'Unclassified'
  const parts = [
    `${source}: ${credits(lot.remaining)} of ${credits(lot.credits)} left`,
  ]
  if (lot.source === 'grant' && lot.remaining_value_usd != null) {
    parts.push(`worth ${usd(lot.remaining_value_usd)} at list price`)
  }
  if (lot.days_to_expiry != null)
    parts.push(`expires in ${Math.round(lot.days_to_expiry)} days`)
  return parts.join(', ')
}

function CreditsCard({ data }: { data: CostAccountingResponse }) {
  const c = data.credits
  return (
    <Card title="Codex credits" icon={Coins}>
      <div className="space-y-1.5">
        <Row
          label={`Used, last ${data.window.days} days`}
          value={credits(c.used_in_window)}
        />
        <Row label="Balance" value={credits(c.balance)} />
        <Row
          label="Average per day, last 7 days"
          value={credits(c.burn_per_day_7d)}
        />
      </div>
      {c.lots.length === 0 ? (
        <p className="mt-3 text-xs text-slate-400">
          No credit grants or purchases recorded.
        </p>
      ) : (
        <ul className="mt-3 space-y-1 border-t border-slate-800 pt-2 text-xs text-slate-400">
          {c.lots.map((lot) => (
            <li key={lot.id}>
              {lotLine(lot)}
              {lot.projected_unused_at_expiry != null &&
                lot.projected_unused_at_expiry > 0 && (
                  <span className="text-amber-300">
                    {' '}
                    About {credits(lot.projected_unused_at_expiry)} would expire
                    unused at this pace.
                  </span>
                )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function ValueCard({ data }: { data: CostAccountingResponse }) {
  const v = data.api_equivalent
  return (
    <Card title="API-equivalent value" icon={TrendingUp}>
      <p className="mb-1 font-mono text-2xl text-slate-100">
        {usd(v.total_usd)}
      </p>
      <p className="mb-3 text-xs text-slate-400">
        What this usage would cost at API list prices. Not money spent.
      </p>
      <div className="space-y-1.5">
        {v.by_provider.map((p) => (
          <Row
            key={p.provider}
            label={`${providerName(p.provider)}${p.fee_usd ? ` for ${usd(p.fee_usd)} in fees` : ''}`}
            value={`${usd(p.api_equiv_usd)}${p.leverage != null ? ` (${p.leverage}x)` : ''}`}
          />
        ))}
      </div>
      {v.by_project.length > 0 && (
        <div className="mt-3 border-t border-slate-800 pt-2">
          <p className="mb-1 text-xs text-slate-500">Fee share by project</p>
          {v.by_project.slice(0, 5).map((p) => (
            <Row
              key={p.project}
              label={p.project}
              value={usd(p.allocated_fee_usd)}
            />
          ))}
        </div>
      )}
    </Card>
  )
}

export function CostAccountingSection({ daysRange }: { daysRange: number }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['cost-accounting', daysRange],
    queryFn: () => fetchCostAccounting(daysRange),
    refetchInterval: 5 * 60 * 1000,
  })

  return (
    <div
      id="subscription-costs"
      className="panel-surface col-span-12 scroll-mt-4 p-5 lg:p-6"
    >
      <div className="mb-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
          Subscription costs
        </p>
        <p className="mt-1 text-sm text-slate-300">
          Cash paid, how much of each plan's limits is used, and Codex credits.
        </p>
      </div>
      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-48 animate-pulse rounded-2xl bg-slate-800/60"
            />
          ))}
        </div>
      ) : error || !data ? (
        <p className="text-sm text-red-400">
          Cost accounting unavailable:{' '}
          {error instanceof Error ? error.message : 'no data'}
        </p>
      ) : (
        <>
          <Alerts alerts={data.alerts} />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <CashCard data={data} />
            <HeadroomCard utilization={data.utilization} />
            <CreditsCard data={data} />
            <ValueCard data={data} />
          </div>
        </>
      )}
    </div>
  )
}
