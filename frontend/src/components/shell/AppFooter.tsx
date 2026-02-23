interface AppFooterProps {
  version: string
}

export function AppFooter({ version }: AppFooterProps) {
  return (
    <footer className="border-t border-border/60 px-6 py-3 text-[10px] text-text-muted font-mono flex items-center justify-between">
      <span>Scaffold Arena v{version}</span>
      <span>Built for Scaffold Engineering evaluation</span>
    </footer>
  )
}
