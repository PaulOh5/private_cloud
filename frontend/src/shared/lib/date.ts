const dateTimeFormatter = new Intl.DateTimeFormat('ko-KR', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return '-'
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return dateTimeFormatter.format(date)
}

export function formatRelativeSeconds(seconds: number): string {
  if (seconds < 60) {
    return `${seconds}초`
  }

  const minutes = Math.floor(seconds / 60)
  const remainSeconds = seconds % 60
  return `${minutes}분 ${remainSeconds}초`
}
