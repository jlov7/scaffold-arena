export type BuildMeta = {
  schema_version: string
  app_version: string
  protocol_version: string
  git_sha: string
  build_environment: string
  build_time: string
}

export function resolveGitSha(
  environment?: Record<string, string | undefined>,
  resolveHead?: () => string | null,
): string

export function isFullCommitSha(value: unknown): boolean

export function buildMeta(options: {
  appVersion: string
  environment?: Record<string, string | undefined>
  now?: Date
  resolveHead?: () => string | null
}): BuildMeta
