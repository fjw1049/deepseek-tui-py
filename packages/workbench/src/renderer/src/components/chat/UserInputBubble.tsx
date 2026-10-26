import { useEffect, useRef, useState, type ReactElement } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  LoaderCircle,
  X
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock, UserInputAnswer, UserInputQuestion } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'
import './user-input.css'

const USER_INPUT_OTHER_LABEL = 'Other'
const AUTO_ADVANCE_MS = 240

type UserInputBlock = Extract<ChatBlock, { kind: 'user_input' }>

type SubmittedAnswerRow = {
  id: string
  header: string
  text: string
}

function answersByQuestionId(
  answers: UserInputAnswer[] | undefined
): Record<string, UserInputAnswer> {
  const out: Record<string, UserInputAnswer> = {}
  for (const answer of answers ?? []) {
    out[answer.id] = answer
  }
  return out
}

function answerDisplayText(answer: UserInputAnswer): string {
  const label = answer.label.trim()
  const value = answer.value.trim()
  if (label && label !== USER_INPUT_OTHER_LABEL) return label
  return value || label
}

function submittedAnswerRows(block: UserInputBlock): SubmittedAnswerRow[] {
  const answers = block.answers ?? []
  if (answers.length === 0) return []
  const questionById = new Map(block.questions.map((q) => [q.id, q]))
  return answers.map((answer) => {
    const question = questionById.get(answer.id)
    return {
      id: answer.id,
      header: question?.header?.trim() || answer.id,
      text: answerDisplayText(answer)
    }
  })
}

function SubmittedUserInputBubble({
  block
}: {
  block: UserInputBlock
}): ReactElement {
  const { t } = useTranslation('common')
  const rows = submittedAnswerRows(block)
  return (
    <div id={`block-${block.id}`} className="ds-user-input-bubble min-w-0 max-w-xl py-0.5">
      <div className="flex items-center gap-1.5 text-[12px] leading-4 text-ds-faint">
        <CheckCircle2
          aria-hidden
          className="size-3.5 shrink-0 text-emerald-600/80 dark:text-emerald-400/80"
          strokeWidth={1.9}
        />
        <span className="font-medium tracking-[-0.01em]">{t('userInputAnswered')}</span>
      </div>
      {rows.length > 0 ? (
        <div className="mt-1.5 space-y-2 border-l border-[color-mix(in_srgb,var(--ds-text)_12%,transparent)] pl-3">
          {rows.map((row) => (
            <div key={row.id} className="min-w-0">
              <div className="text-[11px] leading-4 text-ds-faint">{row.header}</div>
              <div className="mt-0.5 whitespace-pre-wrap break-words text-[13px] font-medium leading-5 tracking-[-0.01em] text-ds-ink">
                {row.text}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-1 pl-5 text-[12px] text-ds-faint">{t('userInputSubmitted')}</p>
      )}
    </div>
  )
}

function ResolvedUserInputStatus({ block }: { block: UserInputBlock }): ReactElement {
  const { t } = useTranslation('common')
  const failed = block.status === 'error'
  const statusLabel = failed ? t('userInputFailed') : t('userInputCancelled')
  return (
    <div
      id={`block-${block.id}`}
      className={`flex items-center gap-1.5 text-[12px] leading-5 ${
        failed ? 'text-ds-danger' : 'text-ds-faint'
      }`}
    >
      <X aria-hidden className="size-3.5 shrink-0" strokeWidth={2} />
      <span>{block.errorMessage?.trim() || statusLabel}</span>
    </div>
  )
}

function PendingUserInputCard({ block }: { block: UserInputBlock }): ReactElement {
  const { t } = useTranslation('common')
  const resolveUserInput = useChatStore((s) => s.resolveUserInput)
  const [answers, setAnswers] = useState<Record<string, UserInputAnswer>>(() =>
    answersByQuestionId(block.answers)
  )
  const [step, setStep] = useState(0)
  const [localSubmitting, setSubmitting] = useState(false)
  const submitting = localSubmitting || Boolean(block.submitting)
  const cardRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const inFlight = useRef(false)
  const autoAdvanceTimer = useRef<number | undefined>(undefined)

  const total = block.questions.length
  const clampedStep = Math.min(step, Math.max(0, total - 1))
  const question = block.questions[clampedStep]
  const allowCustom = question?.allow_custom !== false
  const isLast = clampedStep >= total - 1

  const clearAutoAdvance = (): void => {
    if (autoAdvanceTimer.current === undefined) return
    window.clearTimeout(autoAdvanceTimer.current)
    autoAdvanceTimer.current = undefined
  }

  useEffect(() => () => clearAutoAdvance(), [])

  useEffect(() => {
    setAnswers(answersByQuestionId(block.answers))
  }, [block.id, block.answers])

  useEffect(() => {
    clearAutoAdvance()
    setSubmitting(false)
    inFlight.current = false
    setStep(0)
  }, [block.id])

  const isAnswered = (q: UserInputQuestion): boolean => {
    const answer = answers[q.id]
    if (!answer) return false
    if (answer.label === USER_INPUT_OTHER_LABEL) return answer.value.trim().length > 0
    return true
  }

  const goTo = (next: number): void => {
    if (submitting) return
    clearAutoAdvance()
    setStep(next)
  }

  const chooseOption = (
    q: UserInputQuestion,
    label: string,
    value = label,
    autoAdvance = true
  ): void => {
    if (submitting || inFlight.current) return
    setAnswers((prev) => ({
      ...prev,
      [q.id]: { id: q.id, label, value }
    }))
    if (!autoAdvance || label === USER_INPUT_OTHER_LABEL || clampedStep >= total - 1) {
      clearAutoAdvance()
      return
    }
    clearAutoAdvance()
    autoAdvanceTimer.current = window.setTimeout(() => {
      setStep(clampedStep + 1)
    }, AUTO_ADVANCE_MS)
  }

  const canSubmit = block.questions.every(isAnswered)

  const submit = (): void => {
    if (!canSubmit || submitting || inFlight.current) return
    inFlight.current = true
    clearAutoAdvance()
    setSubmitting(true)
    void resolveUserInput(block.id, {
      kind: 'submit',
      answers: block.questions.map((q) => answers[q.id]).filter(Boolean)
    }).finally(() => { inFlight.current = false; setSubmitting(false) })
  }

  const cancel = (): void => {
    if (submitting || inFlight.current) return
    clearAutoAdvance()
    inFlight.current = true
    setSubmitting(true)
    void resolveUserInput(block.id, { kind: 'cancel' }).finally(() => {
      inFlight.current = false
      setSubmitting(false)
    })
  }

  const answer = question ? answers[question.id] : undefined
  const otherSelected = answer?.label === USER_INPUT_OTHER_LABEL || question?.options.length === 0
  const currentAnswered = question ? isAnswered(question) : false

  useEffect(() => {
    // Only move focus when it already belongs to this question card.
    if (!cardRef.current?.contains(document.activeElement)) return
    if (otherSelected) inputRef.current?.focus()
    else cardRef.current?.focus()
  }, [clampedStep, otherSelected])

  return (
    <div
      ref={cardRef}
      id={`block-${block.id}`}
      data-state={submitting ? 'submitting' : 'pending'}
      aria-busy={submitting}
      role="group"
      aria-labelledby={`question-${block.id}`}
      tabIndex={0}
      className="ds-user-input-pending"
      onKeyDown={(event) => {
        if (event.defaultPrevented || event.repeat || event.nativeEvent.isComposing ||
          event.metaKey || event.ctrlKey || event.altKey || submitting || !question) return
        if ((event.target as HTMLElement).closest('input, textarea, [contenteditable="true"]')) return
        const index = Number(event.key) - 1
        if (/^[1-9]$/.test(event.key) && question.options[index]) {
          event.preventDefault()
          const option = question.options[index]
          chooseOption(question, option.label, option.value || option.label)
        }
      }}
    >
      <div className="ds-question-meta">
        <span aria-live="polite">{t('userInputQuestionProgress', { current: total ? clampedStep + 1 : 0, total })}</span>
        {block.taskId ? <span className="ds-question-source" title={t('userInputFromTask', { id: block.taskId })}>
          {t('userInputFromTask', { id: block.taskId })}
        </span> : null}
      </div>
      <h3 id={`question-${block.id}`} className="ds-question-title">
        {question?.question || t('userInputTitle')}
      </h3>
      {question?.description ? <p className="ds-question-description">{question.description}</p> : null}
      {question ? <div className="ds-question-options" role="group" aria-labelledby={`question-${block.id}`}>
        {question.options.map((option, index) => {
          const optionValue = option.value || option.label
          const selected = answer?.label === option.label && answer.value === optionValue
          return <button
            key={option.label}
            type="button"
            disabled={submitting}
            aria-pressed={selected}
            aria-keyshortcuts={index < 9 ? String(index + 1) : undefined}
            onClick={() => chooseOption(question, option.label, optionValue)}
            className="ds-question-option"
          >
            <span className="ds-question-option-copy">
              <span className="ds-question-option-label">{option.label}</span>
              {option.description ? <span className="ds-question-option-description">{option.description}</span> : null}
            </span>
            <span className="ds-question-key" aria-hidden>{selected ? <Check size={14} /> : index + 1}</span>
          </button>
        })}
        {allowCustom && question.options.length > 0 ? <button
          type="button"
          disabled={submitting}
          aria-pressed={otherSelected}
          className="ds-question-option"
          onClick={() => chooseOption(question, USER_INPUT_OTHER_LABEL,
            answer?.label === USER_INPUT_OTHER_LABEL ? answer.value : '', false)}
        >
          <span className="ds-question-option-copy">
            <span className="ds-question-option-label">{t('userInputOther')}</span>{' '}
            <span className="ds-question-option-description">{t('userInputOtherDescription')}</span>
          </span>
          <span className="ds-question-key" aria-hidden>{otherSelected ? <Check size={14} /> : null}</span>
        </button> : null}
        {allowCustom && otherSelected ? <input
          ref={inputRef}
          value={answer?.value ?? ''}
          disabled={submitting}
          aria-label={question.question}
          onChange={(event) => chooseOption(question, USER_INPUT_OTHER_LABEL, event.target.value, false)}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' || event.nativeEvent.isComposing || event.repeat) return
            event.preventDefault()
            if (isLast) submit()
            else if (currentAnswered) goTo(clampedStep + 1)
          }}
          placeholder={t('userInputCustomPlaceholder')}
          className="ds-question-input"
        /> : null}
      </div> : null}
      <div className="ds-question-footer">
        {clampedStep > 0 ? <button type="button" disabled={submitting} onClick={() => goTo(clampedStep - 1)}>
          <ArrowLeft size={15} aria-hidden />{t('userInputBack')}
        </button> : null}
        <div className="ds-question-actions">
          <button type="button" disabled={submitting} onClick={cancel}>{t('userInputCancel')}</button>
          {isLast ? <button type="button" disabled={submitting || !canSubmit || !total} onClick={submit}>
            {t('userInputSubmit')}
            {submitting ? <LoaderCircle size={15} className="animate-spin" aria-hidden /> : <ArrowRight size={15} aria-hidden />}
          </button> : <button type="button" disabled={submitting || !currentAnswered} onClick={() => goTo(clampedStep + 1)}>
            {t('userInputNext')}<ArrowRight size={15} aria-hidden />
          </button>}
        </div>
      </div>
    </div>
  )
}

export function UserInputBubble({ block }: { block: UserInputBlock }): ReactElement {
  if (block.status === 'submitted') {
    return <SubmittedUserInputBubble block={block} />
  }
  if (block.status === 'cancelled' || block.status === 'error') {
    return <ResolvedUserInputStatus block={block} />
  }
  return <PendingUserInputCard block={block} />
}
