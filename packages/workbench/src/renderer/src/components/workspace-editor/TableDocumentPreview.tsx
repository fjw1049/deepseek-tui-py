import { useMemo, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { parseTablePreview, tableColumnLabel } from '../../lib/table-preview'

export function TableDocumentPreview({ content, path }: { content: string; path: string }): ReactElement {
  const { t } = useTranslation('common')
  const rows = useMemo(() => parseTablePreview(content, path), [content, path])
  const columns = rows.reduce((max, row) => Math.max(max, row.length), 0)
  const visibleColumns = Math.min(columns, 50)
  const visibleRows = rows.slice(0, 500)
  return (
    <div className="ds-table-document">
      <div className="ds-table-document__summary">
        {t('workspaceTableDimensions', { rows: rows.length, columns })}
        {rows.length > 500 || columns > 50 ? (
          <span>{t('workspaceTableLimited', { rows: visibleRows.length, columns: visibleColumns })}</span>
        ) : null}
      </div>
      <div className="ds-table-document__scroll">
        <table aria-label={path}>
          <thead><tr>
            <th scope="col">#</th>
            {Array.from({ length: visibleColumns }, (_, col) => <th scope="col" key={col}>{tableColumnLabel(col)}</th>)}
          </tr></thead>
          <tbody>{visibleRows.map((row, index) => (
            <tr key={index}>
              <th scope="row">{index + 1}</th>
              {Array.from({ length: visibleColumns }, (_, col) => <td key={col}>{row[col] ?? ''}</td>)}
            </tr>
          ))}</tbody>
        </table>
        {rows.length === 0 ? <div className="ds-table-document__empty">{t('workspaceTableEmpty')}</div> : null}
      </div>
    </div>
  )
}
