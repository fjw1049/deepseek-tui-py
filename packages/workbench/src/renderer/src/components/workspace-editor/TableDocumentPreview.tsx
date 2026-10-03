import { useEffect, useMemo, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { parseTablePreview, tableColumnLabel } from '../../lib/table-preview'

export function TableDocumentPreview({ content, path }: { content: string; path: string }): ReactElement {
  const { t } = useTranslation('common')
  const rows = useMemo(() => parseTablePreview(content, path), [content, path])
  const columns = rows.reduce((max, row) => Math.max(max, row.length), 0)
  const visibleColumns = Math.min(columns, 50)
  const [page, setPage] = useState(0)
  useEffect(() => setPage(0), [content, path])
  const pages = Math.max(1, Math.ceil(Math.min(rows.length, 500) / 50))
  const offset = Math.min(page, pages - 1) * 50
  const visibleRows = rows.slice(offset, Math.min(offset + 50, 500))
  return (
    <div className="ds-table-document">
      <div className="ds-table-document__summary">
        {t('workspaceTableDimensions', { rows: rows.length, columns })}
        {rows.length > 500 || columns > 50 ? (
          <span>{t('workspaceTableLimited', { rows: Math.min(rows.length, 500), columns: visibleColumns })}</span>
        ) : null}
      </div>
      {pages > 1 ? <div className="flex items-center gap-3 px-4 py-2">
        <button type="button" disabled={page === 0} onClick={() => setPage((current) => current - 1)}>{t('workspaceTablePrevious')}</button>
        <span>{t('workspaceTablePage', { page: Math.min(page + 1, pages), pages })}</span>
        <button type="button" disabled={page >= pages - 1} onClick={() => setPage((current) => current + 1)}>{t('workspaceTableNext')}</button>
      </div> : null}
      <div className="ds-table-document__scroll">
        <table aria-label={path}>
          <thead><tr>
            <th scope="col">#</th>
            {Array.from({ length: visibleColumns }, (_, col) => <th scope="col" key={col}>{tableColumnLabel(col)}</th>)}
          </tr></thead>
          <tbody>{visibleRows.map((row, index) => (
            <tr key={index}>
              <th scope="row">{offset + index + 1}</th>
              {Array.from({ length: visibleColumns }, (_, col) => <td key={col}>{row[col] ?? ''}</td>)}
            </tr>
          ))}</tbody>
        </table>
        {rows.length === 0 ? <div className="ds-table-document__empty">{t('workspaceTableEmpty')}</div> : null}
      </div>
    </div>
  )
}
