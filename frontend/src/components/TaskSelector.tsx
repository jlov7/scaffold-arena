import { TriangleAlert } from 'lucide-react'
import type { TaskMeta, ModelMeta } from '../types'
import { COPY } from '../content/copy'
import { Button } from './primitives/Button'
import { Select } from './primitives/Select'
import { Tag } from './primitives/Tag'
import { Icon } from './primitives/Icon'

interface TaskSelectorProps {
  tasks: TaskMeta[]
  models: ModelMeta[]
  isRunning: boolean
  selectedTaskId: string
  selectedModelId: string
  estimatedCostUsd: number | null
  onSelectTask: (taskId: string) => void
  onSelectModel: (modelId: string) => void
  onRun: (taskId: string, modelId: string) => void
  onCancel: () => void
  showMobileActionBar?: boolean
  showRunControls?: boolean
}

function inferProviderFromModelId(modelId: string): string {
  if (modelId.startsWith('claude-')) return 'anthropic'
  if (modelId.startsWith('gpt-')) return 'openai'
  if (modelId.startsWith('gemini-')) return 'gemini'
  if (modelId.startsWith('openrouter/')) return 'openrouter'
  return 'unknown'
}

function getProviderLabel(model: Pick<ModelMeta, 'id'> & { provider?: string | null }): string {
  const provider = model.provider?.trim()
  if (provider) return provider
  return inferProviderFromModelId(model.id)
}

export function TaskSelector({
  tasks,
  models,
  isRunning,
  selectedTaskId,
  selectedModelId,
  estimatedCostUsd,
  onSelectTask,
  onSelectModel,
  onRun,
  onCancel,
  showMobileActionBar = true,
  showRunControls = true,
}: TaskSelectorProps) {
  function handleRunOrCancel() {
    if (isRunning) {
      onCancel()
    } else if (selectedTaskId) {
      onRun(selectedTaskId, selectedModelId)
    }
  }

  return (
    <section
      className="lab-panel overflow-hidden"
      aria-label="Task and model selection"
    >
      <div className="flex flex-col gap-3 p-4 pb-20 sm:pb-4">
        <div className="lab-label">
          Benchmark setup
        </div>
      {/* Task cards */}
      <div className="flex snap-x snap-mandatory gap-2 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-visible">
        {tasks.map((task) => {
          const isSelected = task.id === selectedTaskId
          return (
            <button
              key={task.id}
              type="button"
              onClick={() => onSelectTask(task.id)}
              disabled={isRunning}
              aria-label={`Select task ${task.name}`}
              className={[
                'ui-control relative flex min-w-[180px] snap-start flex-col items-start rounded-md border px-3 py-2 text-left transition-colors sm:min-w-0',
                isSelected
                  ? 'border-accent-info bg-accent-info/10 text-text-primary'
                  : 'border-border bg-bg-tertiary text-text-muted hover:border-border-hover hover:text-text-secondary',
                isRunning ? 'cursor-not-allowed opacity-70' : '',
              ].join(' ')}
            >
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-semibold leading-tight">{task.name}</span>
                {task.synthetic_sources && (
                  <span title="Uses synthetic sources" aria-label="synthetic sources">
                    <TriangleAlert
                      className="h-3.5 w-3.5 text-accent-warning"
                      strokeWidth={1.8}
                    />
                  </span>
                )}
              </div>
              {task.subtitle && (
                <span className="mt-1 max-w-[180px] truncate text-xs leading-tight text-text-muted">
                  {task.subtitle}
                </span>
              )}
              <span className="mt-1">
                <Tag tone={isSelected ? 'info' : 'neutral'}>
                {task.type}
                </Tag>
              </span>
            </button>
          )
        })}
      </div>

      <div className="grid gap-2 sm:grid-cols-[1fr_auto_auto] sm:items-center">
        {/* Model dropdown */}
        <label className="text-sm text-text-secondary">
          Model
          <Select
            aria-label="Select model"
            value={selectedModelId}
            onChange={(e) => onSelectModel(e.target.value)}
            disabled={isRunning}
            className="mt-1 w-full cursor-pointer bg-bg-tertiary disabled:cursor-not-allowed disabled:opacity-50"
          >
            {models.map((model) => (
              <option key={model.id} value={model.id}>
                {`[${getProviderLabel(model)}] ${model.label} ($${model.input_usd_per_mtok}/$${model.output_usd_per_mtok})`}
              </option>
            ))}
          </Select>
        </label>

        <div
          className="lab-row px-3 py-2 text-sm text-text-secondary"
          title="Estimated token cost for one arena run (approximate)."
        >
          Est. {estimatedCostUsd === null ? '—' : `$${estimatedCostUsd.toFixed(4)}`}
        </div>

        {showRunControls && (
          <Button
            type="button"
            onClick={handleRunOrCancel}
            disabled={!isRunning && !selectedTaskId}
            aria-label={isRunning ? 'Cancel current run' : 'Start arena run'}
            tone={isRunning ? 'danger' : 'primary'}
            className="hidden whitespace-nowrap px-4 py-2 font-bold sm:inline-flex"
          >
            <span className="inline-flex items-center gap-1.5">
              <Icon name={isRunning ? 'stop' : 'play'} className="h-3 w-3" />
              {isRunning ? COPY.actions.cancelRun : COPY.actions.runArena}
            </span>
          </Button>
        )}
      </div>
      </div>

      {/* Sticky action bar (mobile) */}
      {showMobileActionBar && showRunControls && (
        <div className="fixed inset-x-0 bottom-0 z-50 border-t border-border bg-bg-secondary px-3 py-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] sm:hidden">
          <Button
            type="button"
            onClick={handleRunOrCancel}
            disabled={!isRunning && !selectedTaskId}
            aria-label={isRunning ? 'Cancel current run' : 'Start arena run'}
            tone={isRunning ? 'danger' : 'primary'}
            className="w-full py-3 font-bold"
          >
            <span className="inline-flex items-center gap-1.5">
              <Icon name={isRunning ? 'stop' : 'play'} className="h-3 w-3" />
              {isRunning ? COPY.actions.cancelRun : COPY.actions.runArena}
            </span>
          </Button>
        </div>
      )}
    </section>
  )
}
