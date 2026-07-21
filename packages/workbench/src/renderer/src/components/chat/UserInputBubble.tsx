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
  const pending = block.status === 'pending'
  const done = block.status !== 'pending'

  useEffect(() => {
    setAnswers(answersByQuestionId(block.answers))
  }, [block.id, block.answers])

  const chooseOption = (question: UserInputQuestion, label: string, value = label): void => {
    setAnswers((prev) => ({
      ...prev,
      [question.id]: { id: question.id, label, value }
    }))
  }

  const canSubmit = block.questions.every((question) => {
    const answer = answers[question.id]
    if (!answer) return false
    if (answer.label === USER_INPUT_OTHER_LABEL) return answer.value.trim().length > 0
    return true
  })

  const submit = (): void => {
    if (!canSubmit || !pending) return
    const ordered = block.questions.map((question) => answers[question.id]).filter(Boolean)
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

  return (
    <div
      id={`block-${block.id}`}
      className={`rounded-[14px] border px-4 py-4 text-[13px] leading-6 shadow-[0_12px_30px_rgba(86,103,136,0.04)] ${
        block.status === 'error'
          ? 'border-red-300/80 bg-red-500/10 dark:border-red-800/60 dark:bg-red-950/35'
          : 'border-accent/35 bg-[linear-gradient(180deg,rgba(79,124,255,0.07),rgba(79,124,255,0.11))] text-ds-ink'
      }`}
    >
      <div className="font-semibold text-accent">{t('userInputTitle')}</div>
      <p className="mt-1 text-[12px] text-ds-muted">{statusLabel}</p>

      <div className="mt-3 flex flex-col gap-4">
        {block.questions.map((question, index) => {
          const answer = answers[question.id]
          const otherSelected = answer?.label === USER_INPUT_OTHER_LABEL
          return (
            <div key={question.id} className="rounded-xl border border-ds-border bg-ds-card/60 p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="text-[12px] font-semibold uppercase tracking-[0.12em] text-ds-muted">
                  {question.header}
                </div>
                <div className="text-[12px] text-ds-faint">
                  {t('userInputQuestionProgress', {
                    current: index + 1,
                    total: block.questions.length
                  })}
                </div>
              </div>
              <p className="mt-1.5 whitespace-pre-wrap text-[14px] font-medium text-ds-ink">
                {question.question}
              </p>
              <div className="mt-3 grid gap-2">
                {question.options.map((option) => {
                  const selected = answer?.label === option.label && answer.value === option.label
                  return (
                    <button
                      key={option.label}
                      type="button"
                      disabled={done}
                      onClick={() => chooseOption(question, option.label)}
                      className={`rounded-lg border px-3 py-2 text-left transition disabled:cursor-default ${
                        selected
                          ? 'border-accent/60 bg-accent/10 text-ds-ink'
                          : 'border-ds-border bg-ds-card text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                      }`}
                    >
                      <span className="block text-[13px] font-semibold">{option.label}</span>
                      <span className="mt-0.5 block text-[12px] leading-5 text-ds-faint">
                        {option.description}
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
                  className={`rounded-lg border px-3 py-2 text-left transition disabled:cursor-default ${
                    otherSelected
                      ? 'border-accent/60 bg-accent/10 text-ds-ink'
                      : 'border-ds-border bg-ds-card text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
                  }`}
                >
                  <span className="block text-[13px] font-semibold">{t('userInputOther')}</span>
                  <span className="mt-0.5 block text-[12px] leading-5 text-ds-faint">
                    {t('userInputOtherDescription')}
                  </span>
                </button>
                {otherSelected ? (
                  <textarea
                    rows={2}
                    disabled={done}
                    value={answer?.value ?? ''}
                    onChange={(e) =>
                      chooseOption(question, USER_INPUT_OTHER_LABEL, e.target.value)
                    }
                    placeholder={t('userInputCustomPlaceholder')}
                    className="min-h-20 resize-y rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[13px] leading-5 text-ds-ink outline-none transition placeholder:text-ds-faint focus:border-accent/60 disabled:cursor-default disabled:opacity-80"
                  />
                ) : null}
              </div>
            </div>
          )
        })}
      </div>

      {block.errorMessage ? (
        <p className="mt-3 text-[12px] text-red-700 dark:text-red-300">{block.errorMessage}</p>
      ) : null}

      {block.answers && block.answers.length > 0 && block.status === 'submitted' ? (
        <div className="mt-3 rounded-lg bg-ds-card px-3 py-2 text-[12px] text-ds-muted">
          {block.answers.map((answer) => (
            <div key={answer.id} className="flex gap-2">
              <span className="font-mono text-ds-faint">{answer.id}</span>
              <span className="min-w-0 flex-1 break-words">{answer.value || answer.label}</span>
            </div>
          ))}
        </div>
      ) : null}

      {pending ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!canSubmit}
            className="rounded-lg bg-accent px-3 py-1.5 text-[13px] font-medium text-white hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={submit}
          >
            {t('userInputSubmit')}
          </button>
          <button
            type="button"
            className="rounded-lg border border-ds-border bg-ds-card px-3 py-1.5 text-[13px] font-medium text-ds-ink hover:bg-ds-hover"
            onClick={cancel}
          >
            {t('userInputCancel')}
          </button>
        </div>
      ) : null}
    </div>
  )
}
