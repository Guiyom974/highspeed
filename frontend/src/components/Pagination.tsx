interface Props {
  count: number
  limit: number
  offset: number
  onOffset: (offset: number) => void
}

export default function Pagination({ count, limit, offset, onOffset }: Props) {
  if (count <= limit) return null
  const from = count === 0 ? 0 : offset + 1
  const to = Math.min(offset + limit, count)
  return (
    <div className="pagination">
      <button className="btn ghost sm" disabled={offset <= 0} onClick={() => onOffset(Math.max(0, offset - limit))}>
        ‹ Prev
      </button>
      <span className="progress-text num">{from}–{to} of {count}</span>
      <button className="btn ghost sm" disabled={offset + limit >= count} onClick={() => onOffset(offset + limit)}>
        Next ›
      </button>
    </div>
  )
}
