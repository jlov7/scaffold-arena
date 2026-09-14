import type { ReactNode } from 'react'

interface DataTableColumn<TRow> {
  key: string
  header: string
  render: (row: TRow) => ReactNode
  align?: 'left' | 'right'
}

interface DataTableProps<TRow> {
  columns: DataTableColumn<TRow>[]
  rows: TRow[]
  getRowKey: (row: TRow) => string
  emptyMessage?: string
}

export function DataTable<TRow>({
  columns,
  rows,
  getRowKey,
  emptyMessage = 'No records available.',
}: DataTableProps<TRow>) {
  if (rows.length === 0) {
    return <div className="lab-panel-inset p-4 text-sm text-text-secondary">{emptyMessage}</div>
  }

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="min-w-full divide-y divide-border text-sm">
        <thead className="bg-bg-primary text-text-muted">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={[
                  'px-3 py-2 font-mono text-[10px] uppercase tracking-[0.14em]',
                  column.align === 'right' ? 'text-right' : 'text-left',
                ].join(' ')}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/70 bg-bg-secondary">
          {rows.map((row) => (
            <tr key={getRowKey(row)} className="hover:bg-bg-tertiary/70">
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={[
                    'px-3 py-2 text-text-secondary',
                    column.align === 'right' ? 'text-right tabular-nums' : 'text-left',
                  ].join(' ')}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
