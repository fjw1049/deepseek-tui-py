import { type ReactElement } from 'react'
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

  return (
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
            onClick={() => void applyGoalCommand('pause')}
          >
            <Pause className="h-3.5 w-3.5" strokeWidth={1.9} />
            {t('goalPause')}
          </button>
        ) : null}
        {canResume ? (
          <button
            type="button"
            className="ds-goal-strip__btn"
            onClick={() => void applyGoalCommand('resume')}
          >
            <Play className="h-3.5 w-3.5" strokeWidth={1.9} />
            {t('goalResume')}
          </button>
        ) : null}
        <button
          type="button"
          className="ds-goal-strip__btn ds-goal-strip__btn--danger"
          onClick={() => {
            if (!window.confirm(t('goalCancelConfirm'))) return
            void applyGoalCommand('cancel')
          }}
        >
          <X className="h-3.5 w-3.5" strokeWidth={1.9} />
          {t('goalCancel')}
        </button>
      </div>
    </div>
  )
}
