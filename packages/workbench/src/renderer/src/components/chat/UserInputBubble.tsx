import { useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock, UserInputAnswer, UserInputQuestion } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'

const USER_INPUT_OTHER_LABEL = 'Other'

type UserInputBlock = Extract<ChatBlock, { kind: 'user_input' }>

function answersByQuestionId(
  answers: UserInputAnswer[] | undefined
): Record<string, UserInputAnswer> {
  const out: Record<string, UserInputAnswer> = {}
  for (const answer of answers ?? []) {
    out[answer.id] = answer
  }
  return out
}

export function UserInputBubble({ block }: { block: UserInputBlock }): ReactElement {
  const { t } = useTranslation('common')
  const resolveUserInput = useChatStore((s) => s.resolveUserInput)
  const [answers, setAnswers] = useState<Record<string, UserInputAnswer>>(() =>
    answersByQuestionId(block.answers)
  )
  // Wizard: show one question at a time (like the reference stepper), instead
  // of stacking all questions in one card.
  const [step, setStep] = useState(0)
  const pending = block.status === 'pending'
  const done = block.status !== 'pending'

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

  const chooseOption = (q: UserInputQuestion, label: string, value = label): void => {
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
    if (!canSubmit || !pending) return
    const ordered = block.questions.map((q) => answers[q.id]).filter(Boolean)
    void resolveUserInput(block.id, { kind: 'submit', answers: ordered })
  }

  const cancel = (): void => {
    if (!pending) return
    void resolveUserInput(block.id, { kind: 'cancel' })
  }

  const statusLabel =
    block.status === 'submitted'
      ? t('userInputSubmitted')
      : block.status === 'cancelled'
        ? t('userInputCancelled')
        : block.status === 'error'
          ? t('userInputFailed')
          : t('userInputPending')

  const answer = question ? answers[question.id] : undefined
  const otherSelected = answer?.label === USER_INPUT_OTHER_LABEL

  return (
    <div
      id={`block-${block.id}`}
      className={`rounded-2xl border px-3 py-2.5 text-[12px] leading-5 shadow-panel ${
        block.status === 'error'
          ? 'border-ds-danger/25 bg-ds-danger-soft text-ds-ink'
          : 'border-ds-border bg-ds-card text-ds-ink'
      }`}
    >
      <div className="flex items-center gap-1.5">
        <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
        <span className="text-[12px] font-semibold tracking-[-0.01em] text-ds-ink">
          {t('userInputTitle')}
        </span>
        <span className="text-[11px] text-ds-faint">{statusLabel}</span>
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
              const selected = answer?.label === option.label && answer.value === option.label
              return (
                <button
                  key={option.label}
                  type="button"
                  disabled={done}
                  onClick={() => chooseOption(question, option.label)}
                  className={`flex items-start gap-2 rounded-lg border px-2 py-1.5 text-left transition disabled:cursor-default ${
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
              disabled={done}
              onClick={() =>
                chooseOption(
                  question,
                  USER_INPUT_OTHER_LABEL,
                  answer?.label === USER_INPUT_OTHER_LABEL ? answer.value : ''
                )
              }
              className={`flex items-start gap-2 rounded-lg border px-2 py-1.5 text-left transition disabled:cursor-default ${
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
                disabled={done}
                value={answer?.value ?? ''}
                onChange={(e) => chooseOption(question, USER_INPUT_OTHER_LABEL, e.target.value)}
                placeholder={t('userInputCustomPlaceholder')}
                className="min-h-14 resize-y rounded-lg border border-ds-border bg-ds-card px-2 py-1.5 text-[12px] leading-5 text-ds-ink outline-none transition placeholder:text-ds-faint focus:border-accent/60 disabled:cursor-default disabled:opacity-80"
              />
            ) : null}
          </div>
        </div>
      ) : null}

      {block.errorMessage ? (
        <p className="mt-3 text-[12px] text-ds-danger">{block.errorMessage}</p>
      ) : null}

      {block.answers && block.answers.length > 0 && block.status === 'submitted' ? (
        <div className="mt-3 rounded-[10px] bg-ds-subtle px-3 py-2 text-[12px] text-ds-muted">
          {block.answers.map((a) => (
            <div key={a.id} className="flex gap-2">
              <span className="font-mono text-ds-faint">{a.id}</span>
              <span className="min-w-0 flex-1 break-words">{a.value || a.label}</span>
            </div>
          ))}
        </div>
      ) : null}

      {pending ? (
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
      ) : null}
    </div>
  )
}
