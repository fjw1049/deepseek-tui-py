import { type ReactElement, useState } from 'react'
import { Pause, Play, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { GoalSnapshotJson } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'

function tokenBudget(goal: GoalSnapshotJson): number | null {
  const limit = goal.budget_limits?.token_budget
  return typeof limit === 'number' && limit > 0 ? limit : null
}

export function GoalStrip(): ReactElement | null {
  const { t } = useTranslation('common')
  const goal = useChatStore((s) => s.currentGoal)
  const applyGoalCommand = useChatStore((s) => s.applyGoalCommand)
  if (!goal) return null

  const budget = tokenBudget(goal)
  const used = goal.tokens_used ?? 0
  const progress = budget == null ? null : Math.min(100, Math.round((used / budget) * 100))
  const canResume = goal.status === 'paused' || goal.status === 'blocked'
  const canPause = goal.status === 'active'
  const complete = goal.status === 'complete'
  const items = goal.checklist ?? []
  const requirements = goal.requirements ?? []

  return (
    <div className="ds-goal-strip-container">
      <div className="ds-goal-strip" data-status={goal.status}>
        <div className="ds-goal-strip__main">
          <span className="ds-goal-strip__status">{t(`goalStatus_${goal.status}`)}</span>
          <span className="ds-goal-strip__objective" title={goal.objective}>
            {goal.objective}
          </span>
          {progress != null ? (
            <span className="ds-goal-strip__budget" title={`${used} / ${budget}`}>
              <span className="ds-goal-strip__budget-bar" style={{ width: `${progress}%` }} />
              <span className="ds-goal-strip__budget-label">
                {t('goalTokenBudget', { used, budget })}
              </span>
            </span>
          ) : null}
        </div>
        <div className="ds-goal-strip__actions">
          {canPause ? (
            <button
              type="button"
              className="ds-goal-strip__btn"
              onClick={() => void applyGoalCommand('pause', { expectedGoalId: goal.goal_id })}
            >
              <Pause className="h-3.5 w-3.5" strokeWidth={1.9} />
              {t('goalPause')}
            </button>
          ) : null}
          {canResume ? (
            <button
              type="button"
              className="ds-goal-strip__btn"
              onClick={() => void applyGoalCommand('resume', { expectedGoalId: goal.goal_id })}
            >
              <Play className="h-3.5 w-3.5" strokeWidth={1.9} />
              {t('goalResume')}
            </button>
          ) : null}
          {complete ? (
            <button type="button" className="ds-goal-strip__btn"
              onClick={() => void applyGoalCommand('reopen', { expectedGoalId: goal.goal_id })}>
              {t('goalReopen')}
            </button>
          ) : null}
          <button
            type="button"
            className="ds-goal-strip__btn ds-goal-strip__btn--danger"
            onClick={() => {
              if (!complete && !window.confirm(t('goalCancelConfirm'))) return
              void applyGoalCommand('cancel', { expectedGoalId: goal.goal_id })
            }}
          >
            <X className="h-3.5 w-3.5" strokeWidth={1.9} />
            {t(complete ? 'goalClear' : 'goalCancel')}
          </button>
        </div>
      </div>
      {goal.terminal_reason || items.length > 0 || requirements.length > 0 ? (
        <details className="ds-goal-details" open={goal.status === 'budget_limited'}>
          <summary>{t('goalDetails')}{items.length > 0
            ? ` · ${items.filter((item) => item.status === 'completed').length}/${items.length}` : ''}</summary>
          {goal.terminal_reason ? <p>{goal.terminal_reason}</p> : null}
          {requirements.length > 0 ? <>
            <p>{t('goalRequirements')}</p>
            <ul>{requirements.map((item) => {
              const check = complete ? goal.completion_audit?.checks?.find(
                (entry) => entry.requirement_id === item.id
              ) : undefined
              return <li key={item.id}>
                {check ? '✓' : '○'} {item.content}
                {check ? <p>{check.explanation}</p> : null}
              </li>
            })}</ul>
          </> : null}
          <ul>{items.map((item) => <li key={item.id}>
            {item.status === 'completed' ? '✓' : item.status === 'cancelled' ? '−' : '○'} {item.content}
          </li>)}</ul>
          {complete && goal.completion_evidence?.length ? (
            <ul>{goal.completion_evidence.map((id) => {
              const evidence = goal.evidence?.find((item) => item.tool_call_id === id)
              return <li key={id}>{evidence?.description ?? id}</li>
            })}</ul>
          ) : null}
        </details>
      ) : null}
      {goal.status === 'budget_limited' ? <GoalBudgetEditor key={goal.goal_id} goal={goal} /> : null}
    </div>
  )
}

function GoalBudgetEditor({ goal }: { goal: GoalSnapshotJson }): ReactElement {
  const { t } = useTranslation('common')
  const applyGoalCommand = useChatStore((s) => s.applyGoalCommand)
  const [limits, setLimits] = useState({
    tokens: goal.budget_limits?.token_budget ?? 0,
    turns: goal.budget_limits?.turn_budget ?? 0,
    seconds: Math.ceil((goal.budget_limits?.wall_clock_budget_ms ?? 0) / 1000)
  })
  const [saving, setSaving] = useState(false)
  const used = {
    tokens: goal.tokens_used ?? 0,
    turns: goal.turns_used ?? 0,
    seconds: Math.floor((goal.wall_clock_ms ?? 0) / 1000)
  }
  const enabled = {
    tokens: goal.budget_limits?.token_budget != null,
    turns: goal.budget_limits?.turn_budget != null,
    seconds: goal.budget_limits?.wall_clock_budget_ms != null
  }
  return (
    <form className="ds-goal-budget-editor" onSubmit={async (event) => {
      event.preventDefault()
      setSaving(true)
      try {
        const args = Object.entries(limits)
          .filter(([, value]) => value > 0)
          .map(([unit, value]) => `${unit} ${value}`).join(' ')
        await applyGoalCommand(`budget ${args}`, {
          expectedGoalId: goal.goal_id, resumeAfterBudget: true
        })
      } finally {
        setSaving(false)
      }
    }}>
      <p>{t('goalBudgetHelp')}</p>
      {(['tokens', 'turns', 'seconds'] as const).filter((unit) => enabled[unit]).map((unit) => (
        <label key={unit}>
          {t(`goalBudget_${unit}`)}
          <input
            type="number"
            required
            step={1}
            min={used[unit] + 1}
            max={unit === 'seconds' ? 86400 : Number.MAX_SAFE_INTEGER}
            value={limits[unit]}
            onChange={(event) => setLimits((current) => ({
              ...current,
              [unit]: Number(event.target.value)
            }))}
          />
        </label>
      ))}
      <button type="submit" className="ds-goal-strip__btn" disabled={saving}>
        {t('goalBudgetResume')}
      </button>
    </form>
  )
}
