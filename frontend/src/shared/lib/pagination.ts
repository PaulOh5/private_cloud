export function toOffset(page: number, limit: number): number {
  return Math.max(0, (page - 1) * limit)
}

export function toTotalPages(total: number, limit: number): number {
  if (limit <= 0) {
    return 1
  }

  return Math.max(1, Math.ceil(total / limit))
}
