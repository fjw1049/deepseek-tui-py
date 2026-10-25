/** Process arguments are diagnostic text, not a place to expose credentials. */
export function redactRuntimeCommand(command: string): string {
  return command.replace(
    /((?:--(?:auth-token|api-key|runtime-token)|(?:DEEPSEEK_API_KEY|DEEPSEEK_RUNTIME_TOKEN))\s*(?:=|\s)\s*)(?:"[^"]*"|'[^']*'|\S+)/gi,
    '$1[redacted]'
  )
}
