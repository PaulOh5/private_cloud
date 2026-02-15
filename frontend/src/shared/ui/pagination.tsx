import { ChevronLeft, ChevronRight } from 'lucide-react'

import { toTotalPages } from '@/shared/lib/pagination'
import { Button } from '@/shared/ui/button'

interface PaginationProps {
  total: number
  limit: number
  page: number
  onPageChange: (page: number) => void
}

export function Pagination({ total, limit, page, onPageChange }: PaginationProps) {
  const totalPages = toTotalPages(total, limit)

  return (
    <div className="mt-4 flex items-center justify-between rounded-lg border border-border bg-card px-3 py-2">
      <p className="text-sm text-muted-foreground">
        총 <strong className="text-foreground">{total}</strong>건, {page}/{totalPages} 페이지
      </p>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page <= 1}
        >
          <ChevronLeft className="mr-1 h-4 w-4" /> 이전
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages}
        >
          다음 <ChevronRight className="ml-1 h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
