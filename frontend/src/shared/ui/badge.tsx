import { cva, type VariantProps } from 'class-variance-authority'
import type { HTMLAttributes } from 'react'

import { cn } from '@/shared/lib/utils'

const badgeVariants = cva('inline-flex items-center rounded-md px-2 py-1 text-xs font-semibold', {
  variants: {
    tone: {
      neutral: 'bg-muted text-muted-foreground',
      success: 'bg-emerald-500/15 text-emerald-700',
      warning: 'bg-amber-500/15 text-amber-700',
      danger: 'bg-red-500/15 text-red-700',
    },
  },
  defaultVariants: {
    tone: 'neutral',
  },
})

interface BadgeProps extends HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />
}
