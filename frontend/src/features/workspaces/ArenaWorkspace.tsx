import { useMemo, useState } from 'react'
import ArenaGrid from '../../components/ArenaGrid'
import BlockerGuideCard from '../../components/help/BlockerGuideCard'
import OnboardingChecklist from '../../components/help/OnboardingChecklist'
import { ContextHelp } from '../../components/journey/ContextHelp'
import { PrimaryCtaRail } from '../../components/journey/PrimaryCtaRail'
import { ProgressStepper } from '../../components/journey/ProgressStepper'
import { WorkspaceSection } from '../../components/layout/WorkspaceSection'
import StateCallout from '../../components/StateCallout'
import type { ExperienceMode, UserProfile } from '../../components/journey/ExperienceModeCard'
import type { JourneyStage, JourneyStep } from '../journey/useJourneyProgress'
import type { TroubleshootingPlaybook, PlaybookAction } from '../help/playbook'
import type { AppView } from '../../app/viewState'
import type { PanelState, RunResults } from '../../types'
import { COPY } from '../../content/copy'

type ArenaWorkspaceLane = 'onboarding' | 'configure' | 'live'

interface PersonaGuidance {
  lane: ArenaWorkspaceLane
  title: string
  body: string
  cta: string
}

const ARENA_LANE_COPY: Record<
  ArenaWorkspaceLane,
  { label: string; description: string }
> = {
  onboarding: {
    label: 'Onboarding',
    description: 'Set your role and follow the guided launch path before touching advanced controls.',
  },
  configure: {
    label: 'Configure',
    description: 'Pick task + model, verify spend estimate, and stage the run.',
  },
  live: {
    label: 'Live run',
    description: 'Watch streaming outputs and validate winners before jumping to Results.',
  },
}

const ONBOARDING_TIPS = [
  {
    id: 'first-run',
    label: 'How do I start?',
    detail: 'Choose one task and one model, then click "Run from configure lane". Do one run first before comparisons.',
  },
  {
    id: 'live',
    label: 'What is Live run?',
    detail: 'Live run streams each scaffold output in real time so you can spot quality differences before final scoring.',
  },
  {
    id: 'results',
    label: 'Where do I decide?',
    detail: 'Open Results after the run. Start in Summary for score/cost/time, then open Diagnostics only if needed.',
  },
  {
    id: 'blocked',
    label: 'What if I get stuck?',
    detail: 'Open Help Center from the header or use the blocker card. It gives exact next actions for auth, network, and provider issues.',
  },
] as const

export interface ArenaWorkspaceProps {
  arenaLane: ArenaWorkspaceLane
  onArenaLaneChange: (lane: ArenaWorkspaceLane) => void
  experienceMode: ExperienceMode
  personaGuidance: PersonaGuidance
  journeyStage: JourneyStage
  journeySteps: JourneyStep[]
  journeyHelpTitle: string
  journeyHelpBody: string
  journeySuccessCriteria: string
  isRunning: boolean
  isOnline: boolean
  hasRun: boolean
  hasTask: boolean
  hasModel: boolean
  hasResults: boolean
  hasComparison: boolean
  userProfile: UserProfile
  checklistHidden: boolean
  onChecklistHide: () => void
  onChecklistShow: () => void
  onTourOpen: () => void
  selectedTaskId: string
  selectedModelId: string
  panels: PanelState[]
  finalResults: RunResults | null
  winnerId: string | null
  railOrderVariant: 'compare_first' | 'export_first'
  currentPlaybook: TroubleshootingPlaybook
  safeFallbackMode: boolean
  showFrictionFeedback: boolean
  runFromCurrentSelection: () => void
  onNavigateToView: (view: AppView) => void
  onRunComparison: (winnerId: string) => Promise<void>
  onExportReport: () => Promise<void>
  onShareRun: () => Promise<void>
  onExecutePlaybookAction: (action: PlaybookAction) => void
  onOpenHelpCenter: (source: 'header' | 'banner' | 'keyboard' | 'card' | 'route' | 'unknown') => void
  enterSafeFallbackMode: () => void
  submitFrictionFeedback: (sentiment: 'helpful' | 'not_helpful') => void
  onDismissFrictionFeedback: () => void
}

export function ArenaWorkspace({
  arenaLane,
  onArenaLaneChange,
  experienceMode,
  personaGuidance,
  journeyStage,
  journeySteps,
  journeyHelpTitle,
  journeyHelpBody,
  journeySuccessCriteria,
  isRunning,
  isOnline,
  hasRun,
  hasTask,
  hasModel,
  hasResults,
  hasComparison,
  userProfile,
  checklistHidden,
  onChecklistHide,
  onChecklistShow,
  onTourOpen,
  selectedTaskId,
  selectedModelId,
  panels,
  finalResults,
  winnerId,
  railOrderVariant,
  currentPlaybook,
  safeFallbackMode,
  showFrictionFeedback,
  runFromCurrentSelection,
  onNavigateToView,
  onRunComparison,
  onExportReport,
  onShareRun,
  onExecutePlaybookAction,
  onOpenHelpCenter,
  enterSafeFallbackMode,
  submitFrictionFeedback,
  onDismissFrictionFeedback,
}: ArenaWorkspaceProps) {
  const [activeTipId, setActiveTipId] = useState<(typeof ONBOARDING_TIPS)[number]['id'] | null>(
    ONBOARDING_TIPS[0].id,
  )
  const activeTip = useMemo(
    () => ONBOARDING_TIPS.find((tip) => tip.id === activeTipId) ?? ONBOARDING_TIPS[0],
    [activeTipId],
  )

  return (
    <>
      <section className="space-y-3">
        <WorkspaceSection
          template="setup-heavy"
          priority="critical"
          className="stack-tight"
        >
          <div className="ui-heading-sm text-text-secondary">
            Arena workflow lane
          </div>
          <h2 className="ui-heading-lg text-text-primary">
            {ARENA_LANE_COPY[arenaLane].label}
          </h2>
          <p className="text-sm text-text-secondary">
            {ARENA_LANE_COPY[arenaLane].description}
          </p>
          <div className="grid gap-2 sm:grid-cols-3">
            {(['onboarding', 'configure', 'live'] as ArenaWorkspaceLane[]).map(
              (lane) => (
                <button
                  key={lane}
                  type="button"
                  onClick={() => onArenaLaneChange(lane)}
                  disabled={lane === 'live' && !hasRun && !isRunning}
                  title={ARENA_LANE_COPY[lane].description}
                  className={[
                    'rounded border px-3 py-2 text-left text-sm font-mono transition-colors disabled:cursor-not-allowed disabled:opacity-40',
                    arenaLane === lane
                      ? 'border-accent-info bg-accent-info/10 text-accent-info'
                      : 'border-border text-text-secondary hover:border-accent-info hover:text-accent-info',
                  ].join(' ')}
                >
                  {ARENA_LANE_COPY[lane].label}
                </button>
              ),
            )}
          </div>
        </WorkspaceSection>
        <ProgressStepper steps={journeySteps} />
        {arenaLane === 'onboarding' ? (
          <WorkspaceSection
            template="setup-heavy"
            priority="critical"
            className="stack-tight"
          >
            <div className="ui-heading-sm text-text-secondary">
              Role-specific onboarding
            </div>
            <h3 className="ui-heading-lg text-text-primary">
              {personaGuidance.title}
            </h3>
            <p className="text-sm text-text-secondary">
              {personaGuidance.body}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => onArenaLaneChange(personaGuidance.lane)}
                className="rounded border border-accent-info px-3 py-1.5 text-sm font-mono text-accent-info hover:bg-accent-info/15"
              >
                {personaGuidance.cta}
              </button>
              <button
                type="button"
                onClick={onTourOpen}
                className="rounded border border-border px-3 py-1.5 text-sm font-mono text-text-secondary hover:border-accent-info hover:text-accent-info"
              >
                Open guided tour
              </button>
            </div>
            <div className="rounded border border-border/60 bg-bg-primary px-3 py-2 text-sm text-text-secondary">
              Keep onboarding lightweight: pick your role, choose one task, run once,
              then move to Results summary before diagnostics.
            </div>
            <div className="rounded border border-border/60 bg-bg-primary px-3 py-3">
              <div className="ui-heading-sm text-text-secondary">
                Quick guidance
              </div>
              <p className="mt-1 text-sm text-text-secondary">
                Hover or tap any tip below for plain-language guidance.
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {ONBOARDING_TIPS.map((tip) => {
                  const isActive = tip.id === activeTip.id
                  return (
                    <button
                      key={tip.id}
                      type="button"
                      title={tip.detail}
                      onMouseEnter={() => setActiveTipId(tip.id)}
                      onFocus={() => setActiveTipId(tip.id)}
                      onClick={() => setActiveTipId(tip.id)}
                      className={[
                        'rounded border px-2.5 py-1.5 text-sm font-mono transition-colors',
                        isActive
                          ? 'border-accent-info bg-accent-info/10 text-accent-info'
                          : 'border-border text-text-secondary hover:border-accent-info hover:text-accent-info',
                      ].join(' ')}
                    >
                      {tip.label}
                    </button>
                  )
                })}
              </div>
              <p className="mt-3 rounded border border-accent-info/35 bg-accent-info/8 px-3 py-2 text-sm text-text-primary">
                {activeTip.detail}
              </p>
            </div>
            {experienceMode === 'guided' && !checklistHidden && (
              <OnboardingChecklist
                hasTask={hasTask}
                hasModel={hasModel}
                hasRun={hasRun}
                hasResults={hasResults}
                hasComparison={hasComparison}
                profile={userProfile}
                onHide={onChecklistHide}
              />
            )}
            {experienceMode === 'guided' && checklistHidden && (
              <WorkspaceSection
                template="setup-heavy"
                priority="optional"
                className="stack-tight"
              >
                <div className="text-xs font-mono text-text-secondary">
                  Checklist hidden for a cleaner workspace.
                </div>
                <button
                  type="button"
                  onClick={onChecklistShow}
                  className="rounded border border-accent-info px-3 py-1.5 text-sm font-mono text-accent-info hover:bg-accent-info/15"
                >
                  Resume checklist
                </button>
              </WorkspaceSection>
            )}
          </WorkspaceSection>
        ) : experienceMode === 'guided' ? (
          <ContextHelp
            title={journeyHelpTitle}
            body={journeyHelpBody}
            successCriteria={journeySuccessCriteria}
          />
        ) : null}
      </section>

      {currentPlaybook.blocker !== 'none' && (
        <div className="space-y-3">
          <BlockerGuideCard
            playbook={currentPlaybook}
            onPrimaryAction={() => onExecutePlaybookAction(currentPlaybook.primaryAction)}
            onOpenHelp={() => onOpenHelpCenter('card')}
          />
          {!safeFallbackMode && (
            <WorkspaceSection template="run-live" priority="important" className="font-mono stack-tight">
              <div className="ui-heading-sm text-accent-info">
                Safe fallback mode
              </div>
              <p className="text-sm text-text-secondary">
                If live execution stays blocked, continue with saved runs and evidence export while resolving the issue.
              </p>
              <button
                type="button"
                onClick={enterSafeFallbackMode}
                className="rounded border border-accent-info/70 px-3 py-1.5 text-sm text-accent-info hover:bg-accent-info/15"
              >
                Enable safe fallback mode
              </button>
            </WorkspaceSection>
          )}
        </div>
      )}

      {showFrictionFeedback && (
        <WorkspaceSection template="run-live" priority="important" className="font-mono stack-tight">
          <div className="ui-heading-sm text-accent-info">
            Quick feedback
          </div>
          <p className="text-sm text-text-secondary">
            Was the blocker guidance clear enough to unblock you?
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => submitFrictionFeedback('helpful')}
              className="rounded border border-accent-winner/70 px-3 py-1.5 text-sm text-accent-winner hover:bg-accent-winner/15"
            >
              Yes, helpful
            </button>
            <button
              type="button"
              onClick={() => submitFrictionFeedback('not_helpful')}
              className="rounded border border-accent-warning/70 px-3 py-1.5 text-sm text-accent-warning hover:bg-accent-warning/15"
            >
              Not clear enough
            </button>
            <button
              type="button"
              onClick={onDismissFrictionFeedback}
              className="rounded border border-border px-3 py-1.5 text-sm text-text-secondary hover:border-accent-info hover:text-accent-info"
            >
              Dismiss
            </button>
          </div>
        </WorkspaceSection>
      )}

      <PrimaryCtaRail
        stage={journeyStage}
        canRun={Boolean(
          arenaLane !== 'onboarding' &&
            selectedTaskId &&
            selectedModelId &&
            !isRunning &&
            isOnline,
        )}
        hasResults={Boolean(finalResults)}
        runDisabledReason={isOnline ? undefined : COPY.errors.offlineRunBlocked}
        orderVariant={railOrderVariant}
        showSecondary={experienceMode === 'advanced'}
        onOpenResults={() => onNavigateToView('results')}
        onRun={runFromCurrentSelection}
        onCompare={() => {
          if (!winnerId) return
          void onRunComparison(winnerId)
        }}
        onExport={() => {
          void onExportReport()
        }}
        onShare={() => {
          void onShareRun()
        }}
      />

      {arenaLane === 'onboarding' && (
        <div className="rounded-lg border border-border/50 bg-bg-secondary/50 p-6">
          <div className="text-xs text-text-muted uppercase tracking-widest font-mono mb-5">
            How this workspace unfolds
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div>
              <div className="text-accent-info font-mono text-sm font-bold mb-1.5">
                01 - Configure
              </div>
              <p className="text-sm text-text-secondary leading-relaxed">
                Select one task and one model so all scaffolds run against the same test.
              </p>
            </div>
            <div>
              <div className="text-accent-info font-mono text-sm font-bold mb-1.5">
                02 - Observe
              </div>
              <p className="text-sm text-text-secondary leading-relaxed">
                Move to Live run when ready and watch streamed output and panel state in real time.
              </p>
            </div>
            <div>
              <div className="text-accent-info font-mono text-sm font-bold mb-1.5">
                03 - Decide
              </div>
              <p className="text-sm text-text-secondary leading-relaxed">
                Open Results summary first, then diagnostics only when deeper evidence is needed.
              </p>
            </div>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => onArenaLaneChange('configure')}
              className="rounded border border-accent-info px-3 py-1.5 text-sm font-mono text-accent-info hover:bg-accent-info/15"
            >
              Start with configure lane
            </button>
            <button
              type="button"
              onClick={() => onNavigateToView('history')}
              className="rounded border border-border px-3 py-1.5 text-sm font-mono text-text-secondary hover:border-accent-info hover:text-accent-info"
            >
              Returning user? Open history
            </button>
          </div>
        </div>
      )}

      {arenaLane === 'configure' && (
        <WorkspaceSection
          template="setup-heavy"
          priority="important"
          className="stack-tight"
        >
          <div className="ui-heading-sm text-text-secondary">
            Configure lane
          </div>
          <h3 className="ui-heading-lg text-text-primary">
            Keep setup focused, then jump to live run
          </h3>
          <p className="text-sm text-text-secondary">
            Pick your benchmark inputs here. Move to Live run to monitor execution and
            avoid mixing setup with analysis.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={runFromCurrentSelection}
              disabled={!selectedTaskId || !selectedModelId || isRunning || !isOnline}
              className="rounded border border-accent-info px-3 py-1.5 text-sm font-mono text-accent-info hover:bg-accent-info/15 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Run from configure lane
            </button>
            <button
              type="button"
              onClick={() => onArenaLaneChange('live')}
              className="rounded border border-border px-3 py-1.5 text-sm font-mono text-text-secondary hover:border-accent-info hover:text-accent-info"
            >
              Open live run lane
            </button>
          </div>
        </WorkspaceSection>
      )}

      {arenaLane === 'live' && (
        <div className="space-y-6" id="arena-grid">
          <ArenaGrid panels={panels} />

          {!isRunning && !finalResults && (
            <StateCallout
              kind="empty"
              title="Live lane is ready"
              description="Start a run from the action rail, or return to configure lane to adjust task/model."
              actionLabel="Return to configure lane"
              onAction={() => onArenaLaneChange('configure')}
            />
          )}

          {finalResults && !isRunning && (
            <StateCallout
              kind="success"
              title="Run complete"
              description="Review the scoreboard in Results summary, then open diagnostics for deeper evidence."
              actionLabel="Open results workspace"
              onAction={() => onNavigateToView('results')}
            />
          )}
        </div>
      )}
    </>
  )
}
