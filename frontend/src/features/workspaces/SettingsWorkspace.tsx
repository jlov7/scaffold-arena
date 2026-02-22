import { Suspense, lazy } from 'react'
import type { ExperienceMode } from '../../components/journey/ExperienceModeCard'
import type { ModelMeta, ScaffoldMeta } from '../../types'
import type { TelemetryEvent } from '../../telemetry/events'

const TelemetryDashboard = lazy(() => import('../../components/TelemetryDashboard'))

interface RunOptions {
  temperature: number
  max_output_tokens: number
  timeout_s: number
}

export interface SettingsWorkspaceProps {
  userProfileLabel: string
  experienceMode: ExperienceMode
  theme: string
  llmApiKey: string
  showLlmKey: boolean
  onLlmApiKeyChange: (key: string) => void
  onToggleShowLlmKey: () => void
  onClearLlmKey: () => void
  runMode: string
  onRunModeChange: (mode: 'scaffold' | 'model') => void
  forceRerun: boolean
  onForceRerunChange: (value: boolean) => void
  runOptions: RunOptions
  onRunOptionsChange: React.Dispatch<React.SetStateAction<RunOptions>>
  enableModelMode: boolean
  modelModeScaffoldId: string
  onModelModeScaffoldChange: (id: string) => void
  secondaryModelId: string
  onSecondaryModelChange: (id: string) => void
  models: ModelMeta[]
  scaffolds: ScaffoldMeta[]
  modeScaffoldLabel: string
  modeModelLabel: string
  notificationPermission: string
  onRequestNotificationPermission: () => void
  hasApiToken: boolean
  telemetryConsent: boolean
  onTelemetryConsentChange: (value: boolean) => void
  telemetryEvents: TelemetryEvent[]
  customTaskName: string
  onCustomTaskNameChange: (name: string) => void
  customTaskPrompt: string
  onCustomTaskPromptChange: (prompt: string) => void
  customTaskSchemaText: string
  onCustomTaskSchemaTextChange: (text: string) => void
  onSaveCustomTask: () => void
  onNavigateToArena: () => void
  activeErrorMessage: string | null
}

export function SettingsWorkspace({
  userProfileLabel,
  experienceMode,
  theme,
  llmApiKey,
  showLlmKey,
  onLlmApiKeyChange,
  onToggleShowLlmKey,
  onClearLlmKey,
  runMode,
  onRunModeChange,
  forceRerun,
  onForceRerunChange,
  runOptions,
  onRunOptionsChange,
  enableModelMode,
  modelModeScaffoldId,
  onModelModeScaffoldChange,
  secondaryModelId,
  onSecondaryModelChange,
  models,
  scaffolds,
  modeScaffoldLabel,
  modeModelLabel,
  notificationPermission,
  onRequestNotificationPermission,
  hasApiToken,
  telemetryConsent,
  onTelemetryConsentChange,
  telemetryEvents,
  customTaskName,
  onCustomTaskNameChange,
  customTaskPrompt,
  onCustomTaskPromptChange,
  customTaskSchemaText,
  onCustomTaskSchemaTextChange,
  onSaveCustomTask,
  onNavigateToArena,
  activeErrorMessage,
}: SettingsWorkspaceProps) {
  return (
    <section className="max-w-5xl rounded-lg border border-border bg-bg-secondary p-4 font-mono text-xs">
      <div className="text-[10px] uppercase tracking-widest text-text-secondary">
        Settings &amp; Preferences
      </div>
      <div className="mt-3 rounded border border-border/70 bg-bg-primary p-3">
        <div className="text-[11px] text-text-secondary">Workspace profile</div>
        <div className="mt-1 text-text-primary">
          {userProfileLabel} ·{' '}
          {experienceMode === 'guided' ? 'Guided mode' : 'Advanced mode'}
        </div>
        <div className="mt-2 text-[11px] text-text-muted">
          Change these in the quick-start card on the Arena page.
        </div>
      </div>

      <div className="mt-3 rounded border border-accent-info/30 bg-bg-primary p-3">
        <div className="text-[11px] font-semibold text-accent-info">LLM API Key (BYOK)</div>
        <div className="mt-1 text-[11px] text-text-muted">
          Enter your own API key to run benchmarks. Stored in your browser only — never sent to our server for storage.
        </div>
        <div className="mt-2 flex items-center gap-2">
          <input
            type={showLlmKey ? 'text' : 'password'}
            value={llmApiKey}
            onChange={(e) => onLlmApiKeyChange(e.target.value)}
            placeholder="sk-... or your provider API key"
            autoComplete="off"
            spellCheck={false}
            className="flex-1 rounded border border-border bg-bg-secondary px-2 py-1.5 text-[11px] text-text-primary placeholder:text-text-muted focus:border-accent-info focus:outline-none"
          />
          <button
            type="button"
            onClick={onToggleShowLlmKey}
            className="rounded border border-border px-2 py-1.5 text-[11px] text-text-secondary hover:border-accent-info hover:text-accent-info"
          >
            {showLlmKey ? 'Hide' : 'Show'}
          </button>
          {llmApiKey && (
            <button
              type="button"
              onClick={onClearLlmKey}
              className="rounded border border-border px-2 py-1.5 text-[11px] text-red-400 hover:border-red-400"
            >
              Clear
            </button>
          )}
        </div>
        <div className="mt-1.5 text-[10px] text-text-muted">
          {llmApiKey ? '✓ Key configured — sent per-request via encrypted header' : 'No key set — server-side keys will be used if available'}
        </div>
      </div>

      <details
        className="mt-3 rounded border border-border/60 bg-bg-primary p-3"
        open={experienceMode === 'advanced'}
      >
        <summary className="cursor-pointer text-[11px] text-text-secondary">
          Advanced run controls
        </summary>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <span className="text-text-secondary uppercase tracking-widest text-[10px]">Run Mode</span>
          <button
            type="button"
            onClick={() => onRunModeChange('scaffold')}
            aria-label="Switch to scaffold comparison mode"
            className={[
              'rounded border px-2 py-1',
              runMode === 'scaffold'
                ? 'border-accent-info text-accent-info'
                : 'border-border text-text-secondary',
            ].join(' ')}
          >
            {modeScaffoldLabel}
          </button>
          {enableModelMode && (
            <button
              type="button"
              onClick={() => onRunModeChange('model')}
              aria-label="Switch to model comparison mode"
              className={[
                'rounded border px-2 py-1',
                runMode === 'model'
                  ? 'border-accent-info text-accent-info'
                  : 'border-border text-text-secondary',
              ].join(' ')}
            >
              {modeModelLabel}
            </button>
          )}

          <label className="ml-auto flex items-center gap-2 text-text-secondary">
            <input
              type="checkbox"
              checked={forceRerun}
              onChange={(e) => onForceRerunChange(e.target.checked)}
              aria-label="Force rerun even when cached results exist"
            />
            Force re-run
          </label>
        </div>
        <div className="mt-2 rounded border border-accent-warning/40 bg-accent-warning/10 px-2 py-1.5 text-[10px] text-accent-warning">
          Guardrail: Force re-run bypasses cache and triggers new API spend.
        </div>

        <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
          <label className="space-y-1">
            <div className="text-text-secondary">Temperature: {runOptions.temperature.toFixed(1)}</div>
            <input
              type="range"
              min={0}
              max={2}
              step={0.1}
              value={runOptions.temperature}
              onChange={(e) =>
                onRunOptionsChange((prev) => ({
                  ...prev,
                  temperature: Number(e.target.value),
                }))
              }
              aria-label="Temperature"
              className="w-full"
            />
          </label>
          <label className="space-y-1">
            <div className="text-text-secondary">Max tokens</div>
            <input
              type="number"
              min={64}
              max={32768}
              value={runOptions.max_output_tokens}
              onChange={(e) =>
                onRunOptionsChange((prev) => ({
                  ...prev,
                  max_output_tokens: Number(e.target.value),
                }))
              }
              aria-label="Maximum output tokens"
              className="w-full rounded border border-border bg-bg-secondary px-2 py-1"
            />
          </label>
          <label className="space-y-1">
            <div className="text-text-secondary">Timeout (s)</div>
            <input
              type="number"
              min={1}
              max={600}
              value={runOptions.timeout_s}
              onChange={(e) =>
                onRunOptionsChange((prev) => ({
                  ...prev,
                  timeout_s: Number(e.target.value),
                }))
              }
              aria-label="Request timeout in seconds"
              className="w-full rounded border border-border bg-bg-secondary px-2 py-1"
            />
          </label>
        </div>

        {enableModelMode && runMode === 'model' && (
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
            <label className="space-y-1">
              <div className="text-text-secondary">Scaffold</div>
              <select
                value={modelModeScaffoldId}
                onChange={(e) => onModelModeScaffoldChange(e.target.value)}
                aria-label="Select scaffold for model comparison"
                className="w-full rounded border border-border bg-bg-secondary px-2 py-1"
              >
                {scaffolds.map((scaffold) => (
                  <option key={scaffold.id} value={scaffold.id}>
                    {scaffold.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1">
              <div className="text-text-secondary">Second model</div>
              <select
                value={secondaryModelId || models[0]?.id || ''}
                onChange={(e) => onSecondaryModelChange(e.target.value)}
                aria-label="Select secondary model"
                className="w-full rounded border border-border bg-bg-secondary px-2 py-1"
              >
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        {!enableModelMode && (
          <div className="mt-3 text-[11px] text-text-muted">
            Model comparison is currently disabled by feature flag.
          </div>
        )}

        <details className="mt-3 rounded border border-border bg-bg-secondary p-3">
          <summary className="cursor-pointer text-text-secondary">Create custom task</summary>
          <div className="mt-3 space-y-2">
            <input
              value={customTaskName}
              onChange={(e) => onCustomTaskNameChange(e.target.value)}
              placeholder="Task name"
              aria-label="Custom task name"
              className="w-full rounded border border-border bg-bg-primary px-2 py-1"
            />
            <textarea
              value={customTaskPrompt}
              onChange={(e) => onCustomTaskPromptChange(e.target.value)}
              placeholder="Paste your prompt"
              aria-label="Custom task prompt"
              rows={4}
              className="w-full rounded border border-border bg-bg-primary px-2 py-1"
            />
            <textarea
              value={customTaskSchemaText}
              onChange={(e) => onCustomTaskSchemaTextChange(e.target.value)}
              placeholder="Optional JSON schema"
              aria-label="Custom task JSON schema"
              rows={3}
              className="w-full rounded border border-border bg-bg-primary px-2 py-1"
            />
            <button
              type="button"
              onClick={onSaveCustomTask}
              className="rounded border border-accent-info px-3 py-1 text-accent-info"
            >
              Save custom task
            </button>
          </div>
        </details>
      </details>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="rounded border border-border/60 bg-bg-primary p-3">
          <div className="text-[11px] text-text-secondary">Theme</div>
          <div className="mt-1 text-text-primary">{theme === 'dark' ? 'Dark' : 'Light'}</div>
        </div>
        <div className="rounded border border-border/60 bg-bg-primary p-3">
          <div className="text-[11px] text-text-secondary">Notifications</div>
          <div className="mt-1 text-text-primary">
            {notificationPermission}
          </div>
          <button
            type="button"
            onClick={onRequestNotificationPermission}
            className="mt-2 rounded border border-border px-2 py-1 text-[11px] text-text-secondary hover:border-accent-info hover:text-accent-info"
          >
            Request permission
          </button>
        </div>
        <div className="rounded border border-border/60 bg-bg-primary p-3">
          <div className="text-[11px] text-text-secondary">Session token</div>
          <div className="mt-1 text-text-primary">
            {hasApiToken ? 'Configured' : 'Missing'}
          </div>
          <div className="mt-1 text-[11px] text-text-muted">
            Set `VITE_API_TOKEN` or local storage token before running protected actions.
          </div>
        </div>
        <div className="rounded border border-border/60 bg-bg-primary p-3">
          <div className="text-[11px] text-text-secondary">Analytics consent</div>
          <label className="mt-2 inline-flex items-center gap-2 text-text-primary">
            <input
              type="checkbox"
              checked={telemetryConsent}
              onChange={(e) => onTelemetryConsentChange(e.target.checked)}
            />
            Enable telemetry events
          </label>
          <div className="mt-1 text-[11px] text-text-muted">
            Stores local product usage events for UX improvement.
          </div>
        </div>
      </div>
      <div className="mt-3">
        <Suspense fallback={<div className="text-xs text-text-muted">Loading telemetry...</div>}>
          <TelemetryDashboard events={telemetryEvents} />
        </Suspense>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border/60 pt-4">
        <button
          type="button"
          onClick={onNavigateToArena}
          className="rounded border border-accent-info px-3 py-1.5 text-xs font-mono text-accent-info hover:bg-accent-info/15"
        >
          Return to Arena
        </button>
        {activeErrorMessage && (
          <span className="text-[11px] text-accent-warning">
            An error was reported — returning to Arena may help resolve it.
          </span>
        )}
      </div>
    </section>
  )
}
