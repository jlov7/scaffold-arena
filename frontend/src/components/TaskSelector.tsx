import { useState } from 'react'
import type { TaskMeta, ModelMeta } from '../types'

interface TaskSelectorProps {
  tasks: TaskMeta[]
  models: ModelMeta[]
  isRunning: boolean
  onRun: (taskId: string, modelId: string) => void
  onCancel: () => void
}

export function TaskSelector({ tasks, models, isRunning, onRun, onCancel }: TaskSelectorProps) {
  const [selectedTaskId, setSelectedTaskId] = useState<string>(tasks[0]?.id ?? '')
  const [selectedModelId, setSelectedModelId] = useState<string>(models[0]?.id ?? '')

  function handleRunOrCancel() {
    if (isRunning) {
      onCancel()
    } else if (selectedTaskId) {
      onRun(selectedTaskId, selectedModelId)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 p-3 bg-bg-secondary border-b border-border font-mono">
      {/* Task cards */}
      <div className="flex flex-wrap gap-2 flex-1 min-w-0">
        {tasks.map((task) => {
          const isSelected = task.id === selectedTaskId
          return (
            <button
              key={task.id}
              onClick={() => setSelectedTaskId(task.id)}
              className={[
                'relative flex flex-col items-start px-3 py-2 rounded border text-left transition-colors',
                isSelected
                  ? 'border-accent-info bg-accent-info/10 text-text-primary'
                  : 'border-border bg-bg-tertiary text-text-muted hover:border-border-hover hover:text-text-secondary',
              ].join(' ')}
            >
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-bold leading-tight">{task.name}</span>
                {task.synthetic_sources && (
                  <span
                    title="Uses synthetic sources"
                    className="text-accent-warning text-xs leading-none"
                    aria-label="synthetic sources"
                  >
                    ⚠
                  </span>
                )}
              </div>
              {task.subtitle && (
                <span className="text-[10px] text-text-muted leading-tight mt-0.5 max-w-[160px] truncate">
                  {task.subtitle}
                </span>
              )}
              <span
                className={[
                  'mt-1 text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded',
                  isSelected
                    ? 'bg-accent-info/20 text-accent-info'
                    : 'bg-bg-primary text-text-muted',
                ].join(' ')}
              >
                {task.type}
              </span>
            </button>
          )
        })}
      </div>

      {/* Model dropdown */}
      <select
        value={selectedModelId}
        onChange={(e) => setSelectedModelId(e.target.value)}
        disabled={isRunning}
        className="bg-bg-tertiary border border-border text-text-primary text-xs rounded px-2 py-2 font-mono cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:border-accent-info"
      >
        {models.map((model) => (
          <option key={model.id} value={model.id}>
            {model.label} (${model.input_per_mtok}/${model.output_per_mtok})
          </option>
        ))}
      </select>

      {/* Run / Cancel button */}
      <button
        onClick={handleRunOrCancel}
        disabled={!isRunning && !selectedTaskId}
        className={[
          'px-4 py-2 rounded text-xs font-bold font-mono transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap',
          isRunning
            ? 'bg-accent-loser text-white hover:opacity-90'
            : 'bg-accent-info text-white hover:opacity-90',
        ].join(' ')}
      >
        {isRunning ? 'Cancel' : 'Run Arena'}
      </button>
    </div>
  )
}
