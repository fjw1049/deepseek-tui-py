import { useEffect, useState, type ReactElement } from 'react'
import { CheckCircle2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock, UserInputAnswer, UserInputQuestion } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'

const USER_INPUT_OTHER_LABEL = 'Other'

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

/** Cursor-like Q→A rows for the collapsed questionnaire summary. */
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

/**
 * After submit: left-aligned, process-stream summary (not a user chat bubble).
 * Mirrors Cursor’s collapsed AskQuestion — quiet header + selected picks only.
 */
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
          className="size-3.5 shrink-0 text-ds-ink/45"
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
  const statusLabel =
    block.status === 'cancelled' ? t('userInputCancelled') : t('userInputFailed')
  return (
    <div
      id={`block-${block.id}`}
      className={`flex items-center gap-1.5 text-[12px] leading-5 ${
        block.status === 'error' ? 'text-ds-danger' : 'text-ds-faint'
      }`}
    >
      <span
        aria-hidden
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
          block.status === 'error' ? 'bg-ds-danger' : 'bg-ds-border-strong'
        }`}
      />
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
  // Wizard: show one question at a time (like the reference stepper), instead
  // of stacking all questions in one card.
  const [step, setStep] = useState(0)

  const total = block.questions.length
  const clampedStep = Math.min(step, Math.max(0, total - 1))
  const question = block.questions[clampedStep]
  const isLast = clampedStep >= total - 1

  useEffect(() => {
    setAnswers(answersByQuestionId(block.answers))
  }, [block.id, block.answers])

  // Reset to the first question whenever a new prompt arrives.
  useEffect(() => {
    setStep(0)
  }, [block.id])

  const isAnswered = (q: UserInputQuestion): boolean => {
    const answer = answers[q.id]
    if (!answer) return false
    if (answer.label === USER_INPUT_OTHER_LABEL) return answer.value.trim().length > 0
    return true
  }

  const chooseOption = (
    q: UserInputQuestion,
    label: string,
    value = label
  ): void => {
    setAnswers((prev) => ({
      ...prev,
      [q.id]: { id: q.id, label, value }
    }))
    // Auto-advance on a concrete pick (not the free-text "Other"), so answering
    // flows forward like the reference. Never auto-advance past the last step.
    if (label !== USER_INPUT_OTHER_LABEL && clampedStep < total - 1) {
      setStep(clampedStep + 1)
    }
  }

  const canSubmit = block.questions.every(isAnswered)

  const submit = (): void => {
    if (!canSubmit) return
    const ordered = block.questions.map((q) => answers[q.id]).filter(Boolean)
    void resolveUserInput(block.id, { kind: 'submit', answers: ordered })
  }

  const cancel = (): void => {
    void resolveUserInput(block.id, { kind: 'cancel' })
  }

  const answer = question ? answers[question.id] : undefined
  const otherSelected = answer?.label === USER_INPUT_OTHER_LABEL

  return (
    <div
      id={`block-${block.id}`}
      className="ds-user-input-pending rounded-2xl border border-ds-border bg-ds-card px-3 py-2.5 text-[12px] leading-5 text-ds-ink shadow-panel"
    >
      <div className="flex items-center gap-1.5">
        <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
        <span className="text-[12px] font-semibold tracking-[-0.01em] text-ds-ink">
          {t('userInputTitle')}
        </span>
        {block.taskId ? (
          <span className="truncate font-mono text-[11px] text-ds-faint">
            {t('userInputFromTask', { id: block.taskId })}
          </span>
        ) : null}
        <span className="text-[11px] text-ds-faint">{t('userInputPending')}</span>
        {total > 1 ? (
          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              aria-label="previous"
              disabled={clampedStep === 0}
              onClick={() => setStep(clampedStep - 1)}
              className="grid h-5 w-5 place-items-center rounded text-ds-muted transition hover:bg-ds-hover disabled:opacity-30 disabled:hover:bg-transparent"
            >
              ‹
            </button>
            <span className="font-mono text-[11px] text-ds-faint">
              {clampedStep + 1} / {total}
            </span>
            <button
              type="button"
              aria-label="next"
              disabled={isLast}
              onClick={() => setStep(clampedStep + 1)}
              className="grid h-5 w-5 place-items-center rounded text-ds-muted transition hover:bg-ds-hover disabled:opacity-30 disabled:hover:bg-transparent"
            >
              ›
            </button>
          </div>
        ) : null}
      </div>

      {question ? (
        <div className="mt-2 rounded-lg bg-ds-subtle p-2">
          <div className="text-[10.5px] font-medium text-ds-muted">{question.header}</div>
          <p className="mt-0.5 whitespace-pre-wrap text-[12.5px] font-semibold tracking-[-0.01em] text-ds-ink">
            {question.question}
          </p>
          <div className="mt-1.5 grid gap-1">
            {question.options.map((option) => {
              const optionValue = option.value || option.label
              const selected =
                answer?.label === option.label && answer.value === optionValue
              return (
                <button
                  key={option.label}
                  type="button"
                  onClick={() => chooseOption(question, option.label, optionValue)}
                  className={`flex items-start gap-2 rounded-lg border px-2 py-1.5 text-left transition ${
                    selected
                      ? 'border-accent/50 bg-accent-soft text-ds-ink'
                      : 'border-transparent bg-ds-card text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                  }`}
                >
                  <span
                    aria-hidden
                    className={`mt-[3px] h-2.5 w-2.5 shrink-0 rounded-full border transition ${
                      selected ? 'border-accent bg-accent' : 'border-ds-border'
                    }`}
                  >
                    {selected ? (
                      <span className="block h-full w-full scale-[0.4] rounded-full bg-white" />
                    ) : null}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[12px] font-semibold text-ds-ink">
                      {option.label}
                    </span>
                    <span className="mt-0.5 block text-[11px] leading-[1.3] text-ds-faint">
                      {option.description}
                    </span>
                  </span>
                </button>
              )
            })}
            <button
              type="button"
              onClick={() =>
                chooseOption(
                  question,
                  USER_INPUT_OTHER_LABEL,
                  answer?.label === USER_INPUT_OTHER_LABEL ? answer.value : ''
                )
              }
              className={`flex items-start gap-2 rounded-lg border px-2 py-1.5 text-left transition ${
                otherSelected
                  ? 'border-accent/50 bg-accent-soft text-ds-ink'
                  : 'border-transparent bg-ds-card text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
              }`}
            >
              <span
                aria-hidden
                className={`mt-[3px] h-2.5 w-2.5 shrink-0 rounded-full border transition ${
                  otherSelected ? 'border-accent bg-accent' : 'border-ds-border'
                }`}
              >
                {otherSelected ? (
                  <span className="block h-full w-full scale-[0.4] rounded-full bg-white" />
                ) : null}
              </span>
              <span className="min-w-0">
                <span className="block text-[12px] font-semibold text-ds-ink">
                  {t('userInputOther')}
                </span>
                <span className="mt-0.5 block text-[11px] leading-[1.3] text-ds-faint">
                  {t('userInputOtherDescription')}
                </span>
              </span>
            </button>
            {otherSelected ? (
              <textarea
                rows={2}
                value={answer?.value ?? ''}
                onChange={(e) => chooseOption(question, USER_INPUT_OTHER_LABEL, e.target.value)}
                placeholder={t('userInputCustomPlaceholder')}
                className="min-h-14 resize-y rounded-lg border border-ds-border bg-ds-card px-2 py-1.5 text-[12px] leading-5 text-ds-ink outline-none transition placeholder:text-ds-faint focus:border-accent/60"
              />
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-ds-border-muted pt-2">
        {isLast ? (
          <button
            type="button"
            disabled={!canSubmit}
            className="rounded-lg bg-accent px-3 py-1 text-[12px] font-medium text-white shadow-sm transition hover:brightness-[1.06] active:brightness-95 disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none"
            onClick={submit}
          >
            {t('userInputSubmit')}
          </button>
        ) : (
          <button
            type="button"
            disabled={!question || !isAnswered(question)}
            className="rounded-lg bg-accent px-3 py-1 text-[12px] font-medium text-white shadow-sm transition hover:brightness-[1.06] active:brightness-95 disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none"
            onClick={() => setStep(clampedStep + 1)}
          >
            {t('userInputNext')}
          </button>
        )}
        {clampedStep > 0 ? (
          <button
            type="button"
            className="rounded-lg px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
            onClick={() => setStep(clampedStep - 1)}
          >
            {t('userInputBack')}
          </button>
        ) : null}
        <button
          type="button"
          className="ml-auto rounded-lg px-2.5 py-1 text-[12px] font-medium text-ds-faint transition hover:bg-ds-hover hover:text-ds-muted"
          onClick={cancel}
        >
          {t('userInputCancel')}
        </button>
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
