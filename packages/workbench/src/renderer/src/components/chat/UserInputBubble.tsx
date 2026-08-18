import { useEffect, useRef, useState, type ReactElement } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  CircleHelp,
  LoaderCircle,
  X
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock, UserInputAnswer, UserInputQuestion } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'

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

function ProgressDots({ current, total }: { current: number; total: number }): ReactElement {
  return (
    <div className="flex items-center gap-1.5" aria-hidden>
      {Array.from({ length: total }, (_, index) => (
        <span
          key={index}
          className={`size-1.5 rounded-full bg-ds-ink transition ${
            index === current ? 'scale-100 opacity-100' : index < current ? 'opacity-70' : 'opacity-30'
          }`}
        />
      ))}
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
  const [submitting, setSubmitting] = useState(false)
  const autoAdvanceTimer = useRef<number | undefined>(undefined)

  const total = block.questions.length
  const clampedStep = Math.min(step, Math.max(0, total - 1))
  const question = block.questions[clampedStep]
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
    setStep(0)
  }, [block.id])

  const isAnswered = (q: UserInputQuestion): boolean => {
    const answer = answers[q.id]
    if (!answer) return false
    if (answer.label === USER_INPUT_OTHER_LABEL) return answer.value.trim().length > 0
    return true
  }

  const goTo = (next: number): void => {
    clearAutoAdvance()
    setStep(next)
  }

  const chooseOption = (
    q: UserInputQuestion,
    label: string,
    value = label,
    autoAdvance = true
  ): void => {
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
    if (!canSubmit || submitting) return
    clearAutoAdvance()
    setSubmitting(true)
    void resolveUserInput(block.id, {
      kind: 'submit',
      answers: block.questions.map((q) => answers[q.id]).filter(Boolean)
    })
  }

  const cancel = (): void => {
    clearAutoAdvance()
    void resolveUserInput(block.id, { kind: 'cancel' })
  }

  const answer = question ? answers[question.id] : undefined
  const otherSelected = answer?.label === USER_INPUT_OTHER_LABEL
  const currentAnswered = question ? isAnswered(question) : false

  return (
    <div
      id={`block-${block.id}`}
      data-state={submitting ? 'submitting' : 'pending'}
      aria-busy={submitting}
      className="ds-user-input-pending w-full overflow-hidden rounded-2xl border border-ds-border bg-ds-subtle p-4 text-[13px] leading-5 text-ds-ink"
    >
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden
          className="mt-0.5 grid size-5 shrink-0 place-items-center text-ds-muted"
        >
          {submitting ? (
            <LoaderCircle className="size-4 animate-spin" strokeWidth={2} />
          ) : (
            <CircleHelp className="size-4" strokeWidth={2} />
          )}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate font-semibold tracking-[-0.02em] text-ds-ink">
              {question?.question || t('userInputTitle')}
            </span>
            {total > 1 ? (
              <span className="shrink-0 font-mono text-[11px] text-ds-faint">
                {clampedStep + 1}/{total}
              </span>
            ) : (
              <span className="shrink-0 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-400">
                {t('userInputTitle')}
              </span>
            )}
            {block.taskId ? (
              <span className="max-w-[8rem] truncate font-mono text-[11px] text-ds-faint">
                {t('userInputFromTask', { id: block.taskId })}
              </span>
            ) : null}
            <button
              type="button"
              aria-label={t('userInputCancel')}
              onClick={cancel}
              className="grid size-5 shrink-0 place-items-center rounded-full text-ds-faint transition hover:text-ds-ink"
            >
              <X className="size-3.5" strokeWidth={2} />
            </button>
          </div>

          {question ? (
            <div className="mt-2">
              {question.header ? (
                <div className="text-[11px] font-medium text-ds-muted">{question.header}</div>
              ) : null}
              <div className="mt-1.5 grid gap-0.5">
                {question.options.map((option) => {
                  const optionValue = option.value || option.label
                  const selected =
                    answer?.label === option.label && answer.value === optionValue
                  return (
                    <button
                      key={option.label}
                      type="button"
                      disabled={submitting}
                      onClick={() => chooseOption(question, option.label, optionValue)}
                      className={`flex items-start gap-2.5 rounded-lg px-1.5 py-1.5 text-left transition disabled:opacity-50 ${
                        selected ? 'bg-ds-card text-ds-ink' : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                      }`}
                    >
                      <span
                        aria-hidden
                        className={`mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border-2 transition ${
                          selected ? 'border-accent' : 'border-ds-border'
                        }`}
                      >
                        {selected ? <span className="size-2 rounded-full bg-accent" /> : null}
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[13px] font-medium text-ds-ink">
                          {option.label}
                        </span>
                        {option.description ? (
                          <span className="mt-0.5 block text-[11px] leading-[1.35] text-ds-faint">
                            {option.description}
                          </span>
                        ) : null}
                      </span>
                    </button>
                  )
                })}
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() =>
                    chooseOption(
                      question,
                      USER_INPUT_OTHER_LABEL,
                      answer?.label === USER_INPUT_OTHER_LABEL ? answer.value : '',
                      false
                    )
                  }
                  className={`flex items-start gap-2.5 rounded-lg px-1.5 py-1.5 text-left transition disabled:opacity-50 ${
                    otherSelected ? 'bg-ds-card text-ds-ink' : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                  }`}
                >
                  <span
                    aria-hidden
                    className={`mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border-2 transition ${
                      otherSelected ? 'border-accent' : 'border-ds-border'
                    }`}
                  >
                    {otherSelected ? <span className="size-2 rounded-full bg-accent" /> : null}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium text-ds-ink">
                      {t('userInputOther')}
                    </span>
                    <span className="mt-0.5 block text-[11px] leading-[1.35] text-ds-faint">
                      {t('userInputOtherDescription')}
                    </span>
                  </span>
                </button>
                {otherSelected ? (
                  <input
                    value={answer?.value ?? ''}
                    disabled={submitting}
                    onChange={(e) =>
                      chooseOption(question, USER_INPUT_OTHER_LABEL, e.target.value, false)
                    }
                    placeholder={t('userInputCustomPlaceholder')}
                    className="mt-1 h-10 w-full rounded-xl border-0 bg-ds-card px-3 text-[13px] text-ds-ink outline-none ring-0 placeholder:text-ds-faint focus:bg-ds-card"
                  />
                ) : null}
              </div>
            </div>
          ) : null}

          <div className="mt-3 flex items-center gap-1.5">
            <button
              type="button"
              aria-label={t('userInputBack')}
              disabled={submitting || clampedStep === 0}
              onClick={() => goTo(clampedStep - 1)}
              className="grid size-8 place-items-center rounded-full text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:pointer-events-none disabled:opacity-30"
            >
              <ArrowLeft className="size-4" strokeWidth={2} />
            </button>
            {total > 1 ? <ProgressDots current={clampedStep} total={total} /> : null}
            {isLast ? (
              <button
                type="button"
                disabled={submitting || !canSubmit}
                className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-full bg-ds-ink px-3 text-[12px] font-medium text-ds-canvas transition hover:opacity-90 disabled:pointer-events-none disabled:opacity-40"
                onClick={submit}
              >
                {submitting ? (
                  <LoaderCircle className="size-3.5 animate-spin" strokeWidth={2} />
                ) : (
                  <Check className="size-3.5" strokeWidth={2} />
                )}
                {t('userInputSubmit')}
              </button>
            ) : (
              <button
                type="button"
                aria-label={t('userInputNext')}
                disabled={submitting || !question || !currentAnswered}
                onClick={() => goTo(clampedStep + 1)}
                className="ml-auto grid size-8 place-items-center rounded-full bg-ds-ink text-ds-canvas transition hover:opacity-90 disabled:pointer-events-none disabled:opacity-40"
              >
                <ArrowRight className="size-4" strokeWidth={2} />
              </button>
            )}
          </div>
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
