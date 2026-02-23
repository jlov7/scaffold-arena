import { Modal } from './primitives/Modal'

interface TourStep {
  targetId: string
  title: string
  body: string
}

interface GuidedTourModalProps {
  isOpen: boolean
  step: number
  steps: TourStep[]
  onClose: () => void
  onNext: () => void
}

export default function GuidedTourModal({
  isOpen,
  step,
  steps,
  onClose,
  onNext,
}: GuidedTourModalProps) {
  const activeStep = steps[step]

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Guided Tour"
      className="max-w-lg font-mono"
      contentClassName="p-5"
    >
      <div className="text-xs uppercase tracking-widest text-text-secondary">Guided Tour</div>
      <div className="mt-3 text-sm text-text-primary">{activeStep?.title}</div>
      <div className="mt-2 text-xs text-text-secondary">{activeStep?.body}</div>
      <div className="mt-4 flex items-center justify-between">
        <button
          type="button"
          onClick={onClose}
          className="ui-control rounded border border-border min-h-11 px-3.5 py-2 text-xs text-text-secondary sm:min-h-0 sm:px-3 sm:py-1"
        >
          Skip
        </button>
        <button
          type="button"
          onClick={onNext}
          className="ui-control rounded border border-accent-info min-h-11 px-3.5 py-2 text-xs text-accent-info sm:min-h-0 sm:px-3 sm:py-1"
        >
          {step >= steps.length - 1 ? 'Done' : 'Next'}
        </button>
      </div>
    </Modal>
  )
}
