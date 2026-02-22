export default function LoadingSkeletons() {
  const lastPath =
    typeof window !== 'undefined' ? window.location.pathname : '/arena'
  const isSettings = lastPath.includes('/settings')
  const isHistory = lastPath.includes('/history')
  const isLeaderboard = lastPath.includes('/leaderboard')
  const isResults = lastPath.includes('/results')

  return (
    <div className="min-h-screen bg-bg-primary">
      <div className="border-b border-border px-6 py-4">
        <div className="skeleton-shimmer h-7 w-56 rounded" />
        <div className="skeleton-shimmer mt-2 h-4 w-80 rounded" />
      </div>
      <div className="border-b border-border bg-bg-secondary p-3">
        <div className="flex flex-wrap gap-2">
          <div className="skeleton-shimmer h-12 w-40 rounded" />
          <div className="skeleton-shimmer h-12 w-40 rounded" />
          <div className="skeleton-shimmer h-12 w-40 rounded" />
          <div className="skeleton-shimmer h-12 w-40 rounded" />
          <div className="skeleton-shimmer h-12 w-36 rounded" />
        </div>
      </div>
      <main className="p-6">
        {isSettings ? (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {Array.from({ length: 4 }).map((_, idx) => (
              <div
                key={idx}
                className="rounded-lg border border-border bg-bg-secondary p-4"
              >
                <div className="skeleton-shimmer h-4 w-36 rounded" />
                <div className="skeleton-shimmer mt-3 h-9 w-full rounded" />
                <div className="skeleton-shimmer mt-2 h-9 w-full rounded" />
              </div>
            ))}
          </div>
        ) : isLeaderboard ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-border bg-bg-secondary p-4">
              <div className="skeleton-shimmer h-4 w-40 rounded" />
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
                {Array.from({ length: 3 }).map((_, idx) => (
                  <div key={idx} className="skeleton-shimmer h-20 w-full rounded" />
                ))}
              </div>
            </div>
            <div className="rounded-lg border border-border bg-bg-secondary p-4">
              <div className="skeleton-shimmer h-4 w-48 rounded" />
              <div className="skeleton-shimmer mt-3 h-56 w-full rounded" />
            </div>
          </div>
        ) : isHistory ? (
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, idx) => (
              <div
                key={idx}
                className="rounded-lg border border-border bg-bg-secondary p-4"
              >
                <div className="flex items-center justify-between">
                  <div className="skeleton-shimmer h-4 w-40 rounded" />
                  <div className="skeleton-shimmer h-4 w-24 rounded" />
                </div>
                <div className="skeleton-shimmer mt-3 h-3 w-3/4 rounded" />
              </div>
            ))}
          </div>
        ) : isResults ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-border bg-bg-secondary p-4">
              <div className="skeleton-shimmer h-4 w-44 rounded" />
              <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
                {Array.from({ length: 3 }).map((_, idx) => (
                  <div key={idx} className="skeleton-shimmer h-16 w-full rounded" />
                ))}
              </div>
            </div>
            <div className="rounded-lg border border-border bg-bg-secondary p-4">
              <div className="skeleton-shimmer h-4 w-36 rounded" />
              <div className="skeleton-shimmer mt-3 h-24 w-full rounded" />
              <div className="skeleton-shimmer mt-3 h-36 w-full rounded" />
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="rounded-lg border border-border bg-bg-secondary p-4">
              <div className="skeleton-shimmer h-4 w-36 rounded" />
              <div className="skeleton-shimmer mt-3 h-12 w-full rounded" />
              <div className="skeleton-shimmer mt-2 h-12 w-full rounded" />
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-2">
            {Array.from({ length: 4 }).map((_, idx) => (
              <div
                key={idx}
                className="rounded-lg border border-border bg-bg-secondary p-4"
              >
                <div className="skeleton-shimmer h-5 w-32 rounded" />
                <div className="skeleton-shimmer mt-3 h-4 w-24 rounded" />
                <div className="skeleton-shimmer mt-4 h-48 w-full rounded" />
                <div className="skeleton-shimmer mt-3 h-4 w-40 rounded" />
              </div>
            ))}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
